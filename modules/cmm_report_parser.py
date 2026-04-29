"""Parse CMM report files and persist report metadata plus flat measurements."""

import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from time import strftime

from modules.custom_logger import CustomLogger
from modules.cmm_native_parser import (
    parse_blocks_with_backend_and_telemetry,
)
from modules.pdf_backend import require_pdf_backend, resolve_pdf_backend_module_name
from modules.cmm_parsing import add_tolerances_to_blocks
from modules.base_report_parser import BaseReportParser
from modules.header_ocr_backend import (
    DEFAULT_HEADER_OCR_BACKEND,
    RapidOcrLatinBackendConfig,
    default_rapidocr_latin_model_paths,
    get_cached_rapidocr_latin_backend,
    missing_rapidocr_latin_model_paths,
    rapidocr_latin_runtime_config_from_env,
)
from modules.header_ocr_corrections import (
    canonicalize_header_label,
    compact_token,
    postprocess_header_ocr_items,
)
from modules.header_ocr_geometry import convert_ocr_records_to_header_items, select_header_crop
from modules.report_identity import build_report_identity_hash
from modules.report_metadata_extractor import extract_report_metadata
from modules.report_metadata_models import MetadataExtractionContext
from modules.report_metadata_normalizers import (
    normalize_reference,
    normalize_report_date,
    normalize_sample_number,
)
from modules.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE
from modules.report_repository import ReportRepository
from modules.report_schema import ensure_report_schema
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    MeasurementBlockV2,
    MeasurementV2,
    ParseMetaV2,
    ParseResultV2,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    ReportInfoV2,
)


logger = logging.getLogger(__name__)
HEADER_OCR_THREADS_ENV = "METROLIZA_HEADER_OCR_THREADS"
DEFAULT_HEADER_OCR_MAX_THREADS = 4
METADATA_PARSING_MODE_LIGHT = "light"
METADATA_PARSING_MODE_COMPLETE = "complete"
SUPPORTED_METADATA_PARSING_MODES = {
    METADATA_PARSING_MODE_LIGHT,
    METADATA_PARSING_MODE_COMPLETE,
}

def _resolve_pymupdf_backend_module() -> str | None:
    """Return the import name for a valid PyMuPDF backend, if available."""
    return resolve_pdf_backend_module_name()



def _load_pdf_backend():
    return require_pdf_backend()



class CMMReportParser(BaseReportParser, BaseReportParserPlugin):
    """Class to parse and convert PDF CMM report."""

    manifest = PluginManifest(
        plugin_id="cmm",
        display_name="CMM PDF Parser",
        version="1.1.0",
        supported_formats=("pdf",),
        supported_locales=("*",),
        template_ids=("default",),
        priority=100,
        capabilities={"ocr_required": False, "table_extraction_mode": "mixed"},
    )

    @classmethod
    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
        """Return parser detection result for a candidate report file."""

        path_text = str(input_ref)
        if path_text.lower().endswith(".pdf"):
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=100,
                matched_template_id="default",
                reasons=("pdf_extension",),
            )

        return ProbeResult(
            plugin_id=cls.manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("unsupported_extension",),
        )

    def __init__(
        self,
        file_path: str,
        database: str,
        connection=None,
        metadata_parsing_mode: str = METADATA_PARSING_MODE_COMPLETE,
    ):
        """Initialize parser for one CMM report file."""
        super().__init__(file_path=file_path, database=database, connection=connection)
        self.metadata_parsing_mode = self._normalize_metadata_parsing_mode(metadata_parsing_mode)
        self.parse_backend_used = "unknown"
        self.persistence_backend_used = "unknown"
        self.stage_timings_s: dict[str, float] = {}
        self._prepared_measurement_rows = None
        self._metadata_selection_result = None
        self._metadata_identity_hash = None
        self._page_count = None
        self._first_page_width = None
        self._first_page_height = None
        self._first_page_header_items = []
        self._header_extraction_diagnostics = {
            "header_extraction_mode": "none",
            "metadata_parsing_mode": self.metadata_parsing_mode,
            "header_word_count": 0,
            "header_required_fields_found": 0,
        }

    @staticmethod
    def _normalize_metadata_parsing_mode(value: str | None) -> str:
        mode = str(value or METADATA_PARSING_MODE_COMPLETE).strip().lower()
        if mode in SUPPORTED_METADATA_PARSING_MODES:
            return mode
        return METADATA_PARSING_MODE_COMPLETE

    def open_database_and_check_filename(self):
        """Handle `open_database_and_check_filename` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            ensure_report_schema(
                self.database,
                connection=self.connection,
                retries=4,
                retry_delay_s=1,
            )

            self.open_report()
            self.split_text_to_blocks()
            self.add_tolerances()
            self.extract_metadata()
            self.to_sqlite()
        except Exception as e:
            self.log_and_exit(e)

    def _require_pdf_backend(self):
        return _load_pdf_backend()

    @staticmethod
    def _resolve_page_count(pdf_report) -> int | None:
        try:
            return len(pdf_report)
        except TypeError:
            return None

    @staticmethod
    def _page_size(page) -> tuple[float | None, float | None]:
        rect = getattr(page, "rect", None)
        width = getattr(rect, "width", None)
        height = getattr(rect, "height", None)
        return width, height

    @staticmethod
    def _profile_label_aliases() -> tuple[str, ...]:
        labels: set[str] = set()
        for aliases in DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.label_aliases.values():
            for alias in aliases:
                labels.add(alias.upper().rstrip(":"))
                canonical = canonicalize_header_label(alias)
                if canonical:
                    labels.add(canonical.upper().rstrip(":"))
        return tuple(sorted(labels, key=len, reverse=True))

    @classmethod
    def _build_header_items_from_lines(cls, lines, *, page_height=None):
        """Build selector-friendly label/value header items from page text lines."""

        header_items = []
        aliases = cls._profile_label_aliases()
        row_height = 8.0
        for row_index, line in enumerate(lines):
            raw_line = str(line or "").strip()
            if not raw_line:
                continue

            normalized_line = raw_line.upper()
            matches = []
            for alias in aliases:
                start = normalized_line.find(alias)
                if start < 0:
                    continue
                end = start + len(alias)
                matches.append((start, end, alias))

            selected_matches = []
            occupied_ranges: list[tuple[int, int]] = []
            for start, end, alias in sorted(matches, key=lambda match: (match[0], -(match[1] - match[0]))):
                if any(start < used_end and end > used_start for used_start, used_end in occupied_ranges):
                    continue
                selected_matches.append((start, end, alias))
                occupied_ranges.append((start, end))

            selected_matches.sort(key=lambda match: match[0])
            if not selected_matches:
                continue

            y0 = 8.0 + (row_index * row_height)
            if page_height is not None and y0 > float(page_height) * DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.header_band_fraction:
                continue

            for match_index, (start, end, alias) in enumerate(selected_matches):
                next_start = selected_matches[match_index + 1][0] if match_index + 1 < len(selected_matches) else len(raw_line)
                raw_value = raw_line[end:next_start].strip(" :-\t")
                x0 = float(start)
                header_items.append(
                    {
                        "text": alias,
                        "x0": x0,
                        "y0": y0,
                        "x1": float(end),
                        "y1": y0 + 5.0,
                        "page_number": 1,
                        "region_name": "page1_header_band",
                    }
                )
                if raw_value:
                    header_items.append(
                        {
                            "text": raw_value,
                            "x0": float(end + 1),
                            "y0": y0,
                            "x1": float(next_start),
                            "y1": y0 + 5.0,
                            "page_number": 1,
                            "region_name": "page1_header_band",
                        }
                    )

        return header_items

    @staticmethod
    def _bbox_tuple(bbox) -> tuple[float, float, float, float] | None:
        if bbox is None:
            return None
        try:
            return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError, IndexError):
            return None

    @classmethod
    def _header_region_bbox(cls, page) -> tuple[float, float, float, float] | None:
        selection = cls._header_crop_selection(page)
        return selection.bbox if selection is not None else None

    @classmethod
    def _header_crop_selection(cls, page):
        width, height = cls._page_size(page)
        if width is None or height is None:
            return None

        try:
            return select_header_crop(
                page,
                header_band_fraction=DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.header_band_fraction,
            )
        except Exception:
            return None

    @staticmethod
    def _word_in_bbox(word, bbox: tuple[float, float, float, float]) -> bool:
        try:
            x0, y0, x1, y1 = (float(word[0]), float(word[1]), float(word[2]), float(word[3]))
        except (TypeError, ValueError, IndexError):
            return False
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        return bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]

    @classmethod
    def _header_items_from_words(cls, page, bbox: tuple[float, float, float, float]):
        try:
            words = page.get_text("words")
        except Exception:
            return []

        header_items = []
        for word in words:
            if not cls._word_in_bbox(word, bbox):
                continue
            text = str(word[4]).strip() if len(word) > 4 else ""
            if not text:
                continue
            header_items.append(
                {
                    "text": text,
                    "x0": float(word[0]),
                    "y0": float(word[1]),
                    "x1": float(word[2]),
                    "y1": float(word[3]),
                    "page_number": 1,
                    "region_name": "page1_header_band_words",
                }
            )
        return header_items

    @classmethod
    def _header_required_fields_found(cls, header_items) -> int:
        if not header_items:
            return 0
        header_text = " ".join(str(item.get("text", "")) for item in header_items)
        header_compact = compact_token(header_text)
        found = set()
        required_fields = ("part_name", "reference", "revision", "stats_count_raw", "operator_name", "comment")
        for field_name in required_fields:
            aliases = DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.label_aliases.get(field_name, ())
            if any(compact_token(canonicalize_header_label(alias) or alias) in header_compact for alias in aliases):
                found.add(field_name)
        return len(found)

    @staticmethod
    def _header_ocr_thread_count() -> int:
        cpu_count = os.cpu_count() or 1
        raw_value = os.environ.get(HEADER_OCR_THREADS_ENV)
        if raw_value is None or str(raw_value).strip() == "":
            return max(1, min(DEFAULT_HEADER_OCR_MAX_THREADS, cpu_count - 1 if cpu_count > 1 else 1))
        try:
            requested = int(str(raw_value).strip())
        except ValueError:
            return max(1, min(DEFAULT_HEADER_OCR_MAX_THREADS, cpu_count - 1 if cpu_count > 1 else 1))
        return max(1, min(cpu_count, requested))

    @classmethod
    def _ocr_header_items_from_pixmap(
        cls,
        page,
        bbox: tuple[float, float, float, float],
        pdf_backend,
    ) -> tuple[list[dict], str | None]:
        backend_name = os.environ.get("METROLIZA_HEADER_OCR_BACKEND", DEFAULT_HEADER_OCR_BACKEND).strip().lower()
        if backend_name in {"", "none", "off", "disabled"}:
            return [], "header_ocr_disabled"
        if backend_name != DEFAULT_HEADER_OCR_BACKEND:
            return [], f"unsupported_header_ocr_backend:{backend_name}"

        try:
            zoom = float(os.environ.get("METROLIZA_HEADER_OCR_ZOOM", "4"))
            matrix = pdf_backend.Matrix(zoom, zoom)
            clip = pdf_backend.Rect(*bbox)
            pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            model_paths = default_rapidocr_latin_model_paths(
                os.environ.get("METROLIZA_HEADER_OCR_MODEL_DIR") or None
            )
            missing_model_paths = missing_rapidocr_latin_model_paths(model_paths)
            if missing_model_paths:
                missing_names = ", ".join(path.name for path in missing_model_paths)
                return [], f"header_ocr_models_missing:{missing_names}"

            ocr_thread_count = cls._header_ocr_thread_count()
            runtime_config = rapidocr_latin_runtime_config_from_env(
                ocr_thread_count=ocr_thread_count
            )
            backend = get_cached_rapidocr_latin_backend(
                RapidOcrLatinBackendConfig(
                    model_paths=model_paths,
                    params=runtime_config.params,
                )
            )
            with tempfile.TemporaryDirectory(prefix="metroliza_header_ocr_") as temp_dir:
                image_path = Path(temp_dir) / "header.png"
                pixmap.save(str(image_path))
                ocr_start = perf_counter()
                run = backend.recognize(image_path)
                ocr_runtime_s = perf_counter() - ocr_start

            if not run.records:
                return [], "header_ocr_no_records"

            pixel_width = float(getattr(pixmap, "width", 0.0) or 0.0)
            pixel_height = float(getattr(pixmap, "height", 0.0) or 0.0)
            if pixel_width <= 0 or pixel_height <= 0:
                return [], "ocr_pixmap_size_unavailable"

            items = convert_ocr_records_to_header_items(
                run.records,
                crop_bbox=bbox,
                crop_pixel_size=(pixel_width, pixel_height),
                page_number=1,
                region_name="page1_header_band_ocr",
                source_name=DEFAULT_HEADER_OCR_BACKEND,
            )
            if not items:
                return [], "header_ocr_no_header_items"
            run_diagnostics = dict(run.diagnostics)
            run_diagnostics["ocr_runtime_s"] = round(ocr_runtime_s, 4)
            run_diagnostics["ocr_thread_count"] = ocr_thread_count
            run_diagnostics["ocr_runtime_engine"] = runtime_config.engine
            run_diagnostics["ocr_runtime_accelerator"] = runtime_config.accelerator
            for item in items:
                item["ocr_run_diagnostics"] = run_diagnostics
            return postprocess_header_ocr_items(items), None
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"

    @classmethod
    def _extract_first_page_header_items(
        cls,
        page,
        pdf_backend,
        metadata_parsing_mode: str = METADATA_PARSING_MODE_COMPLETE,
    ) -> tuple[list[dict], dict]:
        metadata_mode = cls._normalize_metadata_parsing_mode(metadata_parsing_mode)
        selection = cls._header_crop_selection(page)
        if selection is None:
            return [], {
                "header_extraction_mode": "none",
                "metadata_parsing_mode": metadata_mode,
                "header_word_count": 0,
                "header_required_fields_found": 0,
            }
        bbox = selection.bbox

        word_items = postprocess_header_ocr_items(cls._header_items_from_words(page, bbox))
        word_required_fields = cls._header_required_fields_found(word_items)
        diagnostics = {
            "header_extraction_mode": "words" if word_items else "none",
            "metadata_parsing_mode": metadata_mode,
            "header_word_count": len(word_items),
            "header_required_fields_found": word_required_fields,
            "header_region_bbox": tuple(round(value, 3) for value in bbox),
            "header_region_source": selection.source,
            "header_image_candidate_count": selection.candidate_count,
            "header_crop_diagnostics": selection.diagnostics,
        }

        if word_required_fields >= 2:
            return word_items, diagnostics

        if metadata_mode == METADATA_PARSING_MODE_LIGHT:
            diagnostics["header_ocr_skipped"] = "light_metadata_mode"
            return word_items, diagnostics

        ocr_items, ocr_error = cls._ocr_header_items_from_pixmap(page, bbox, pdf_backend)
        if ocr_items:
            ocr_required_fields = cls._header_required_fields_found(ocr_items)
            first_ocr_item = ocr_items[0]
            ocr_run_diagnostics = first_ocr_item.get("ocr_run_diagnostics") or {}
            diagnostics.update(
                {
                    "header_extraction_mode": "ocr",
                    "header_word_count": len(ocr_items),
                    "header_structured_word_count": len(word_items),
                    "header_required_fields_found": ocr_required_fields,
                    "header_ocr_engine": first_ocr_item.get("ocr_source")
                    or first_ocr_item.get("source")
                    or DEFAULT_HEADER_OCR_BACKEND,
                    "header_ocr_model": DEFAULT_HEADER_OCR_BACKEND,
                    "header_ocr_runtime_s": ocr_run_diagnostics.get("ocr_runtime_s"),
                    "header_ocr_thread_count": ocr_run_diagnostics.get("ocr_thread_count"),
                    "header_ocr_runtime_engine": ocr_run_diagnostics.get("ocr_runtime_engine"),
                    "header_ocr_runtime_accelerator": ocr_run_diagnostics.get(
                        "ocr_runtime_accelerator"
                    ),
                }
            )
            return ocr_items, diagnostics

        if ocr_error:
            diagnostics["header_ocr_error"] = ocr_error
        return word_items, diagnostics

    def open_report(self):
        """Handle `cmm_open` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to open the CMM PDF file and store the text inside the pdf_raw_text attribute.
            It uses the PyMuPDF library (fitz) to open the PDF file and extract the text from each page.
            """
            pdf_backend = self._require_pdf_backend()
            pdf_path = Path(self.file_path) / self.file_name
            with pdf_backend.open(str(pdf_path)) as pdf_report:
                self._page_count = self._resolve_page_count(pdf_report)
                page_counter = 0
                for page in pdf_report:
                    page_counter += 1
                    if page_counter == 1:
                        self._first_page_width, self._first_page_height = self._page_size(page)
                    page_text = page.get_text().splitlines()
                    if page_counter == 1:
                        (
                            self._first_page_header_items,
                            self._header_extraction_diagnostics,
                        ) = self._extract_first_page_header_items(
                            page,
                            pdf_backend,
                            metadata_parsing_mode=self.metadata_parsing_mode,
                        )
                    for line in page_text:
                        self.raw_text.append(line)
                if self._page_count is None:
                    self._page_count = page_counter
        except Exception as e:
            self.log_and_exit(e)


    def cmm_open(self):
        """Backward-compatible alias for open_report."""
        return self.open_report()

    def show_raw_text(self):
        """Handle `show_raw_text` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the raw text inside the PDF.
            It iterates over each line of text in the pdf_raw_text attribute and prints it.
            """
            for line in self.raw_text:
                logger.debug("%s", line)
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text(self):
        """Handle `show_blocks_text` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints each line within the block.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                for line in block:
                    logger.debug("%s (len(line)=%s)", line, len(line))
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text2(self):
        """Handle `show_blocks_text2` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints the entire block as a string.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                logger.debug("%s", block)
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def split_text_to_blocks(self):
        """Handle `split_text_to_blocks` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """Method to split raw text from pdf to blocks - split by measurements"""
            parse_start = perf_counter()
            parse_result = parse_blocks_with_backend_and_telemetry(self.pdf_raw_text)
            self.blocks_text = parse_result.blocks
            self.parse_backend_used = parse_result.backend
            self.stage_timings_s["parse_batch_runtime"] = perf_counter() - parse_start
        except Exception as e:
            self.log_and_exit(e)

    def parse_to_v2(self) -> ParseResultV2:
        """Parse report into canonical V2 result."""

        if not self.raw_text:
            self.open_report()
        if not self.blocks_text:
            self.split_text_to_blocks()
            self.add_tolerances()
        if self._metadata_selection_result is None:
            self.extract_metadata()

        metadata = self._metadata_selection_result.metadata

        blocks_v2: list[MeasurementBlockV2] = []
        for block_index, block in enumerate(self.blocks_text):
            header_tokens = []
            for token in block[0]:
                if isinstance(token, str):
                    header_tokens.append(token)
                elif isinstance(token, list):
                    header_tokens.extend(str(item) for item in token if isinstance(item, str))

            header_normalized = ", ".join(token for token in header_tokens if token)
            dimensions: list[MeasurementV2] = []
            for row in block[1]:
                dimensions.append(
                    MeasurementV2(
                        axis_code=str(row[0]) if len(row) > 0 else "",
                        nominal=row[1] if len(row) > 1 else None,
                        tol_plus=row[2] if len(row) > 2 else None,
                        tol_minus=row[3] if len(row) > 3 else None,
                        bonus=row[4] if len(row) > 4 else None,
                        measured=row[5] if len(row) > 5 else None,
                        deviation=row[6] if len(row) > 6 else None,
                        out_of_tolerance=row[7] if len(row) > 7 else None,
                        raw_tokens=tuple(str(value) for value in row),
                    )
                )

            blocks_v2.append(
                MeasurementBlockV2(
                    header_raw=tuple(header_tokens),
                    header_normalized=header_normalized,
                    dimensions=tuple(dimensions),
                    block_index=block_index,
                )
            )

        return ParseResultV2(
            meta=ParseMetaV2(
                source_file=str(Path(self.file_path) / self.file_name),
                source_format="pdf",
                plugin_id=self.manifest.plugin_id,
                plugin_version=self.manifest.version,
                template_id=metadata.template_family,
                parse_timestamp=strftime("%Y-%m-%dT%H:%M:%SZ"),
                locale_detected=None,
                confidence=int(round(metadata.metadata_confidence * 100)),
            ),
            report=ReportInfoV2(
                reference=metadata.reference or "",
                report_date=metadata.report_date or "",
                sample_number=metadata.sample_number or "",
                file_name=self.file_name,
                file_path=self.file_path,
            ),
            blocks=tuple(blocks_v2),
        )

    @staticmethod
    def to_legacy_blocks(parse_result_v2: ParseResultV2):
        """Convert V2 blocks back to legacy ``blocks_text`` shape."""

        legacy_blocks = []
        for block in parse_result_v2.blocks:
            header = [list(block.header_raw)]
            rows = []
            for row in block.dimensions:
                rows.append(
                    [
                        row.axis_code,
                        row.nominal,
                        row.tol_plus,
                        row.tol_minus,
                        row.bonus,
                        row.measured,
                        row.deviation,
                        row.out_of_tolerance,
                    ]
                )
            legacy_blocks.append([header, rows])
        return legacy_blocks

    def add_tolerances(self):
        """Handle `add_tolerances` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.blocks_text = add_tolerances_to_blocks(self.blocks_text)
        except Exception as e:
            self.log_and_exit(e)

    def extract_metadata(self):
        """Extract canonical metadata using the configured report metadata profile."""

        context = MetadataExtractionContext(
            source_file_id=None,
            parser_id=DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id,
            source_path=self.source_path,
            file_name=self.file_name,
            source_format="pdf",
            page_count=self._page_count,
            first_page_width=self._first_page_width,
            first_page_height=self._first_page_height,
        )
        self._metadata_selection_result = extract_report_metadata(
            context,
            header_items=self._first_page_header_items,
            filename=self.file_name,
        )
        self._metadata_selection_result = self._apply_legacy_metadata_fallbacks(self._metadata_selection_result)
        self._metadata_selection_result = self._apply_header_extraction_diagnostics(self._metadata_selection_result)
        self.canonical_metadata = self._metadata_selection_result.metadata
        self._metadata_identity_hash = build_report_identity_hash(self.canonical_metadata)
        return self._metadata_selection_result

    def _apply_header_extraction_diagnostics(self, selection_result):
        """Persist first-page header extraction diagnostics in canonical metadata JSON."""

        if not self._header_extraction_diagnostics:
            return selection_result
        metadata = selection_result.metadata
        metadata_json = dict(metadata.metadata_json or {})
        metadata_json.update(self._header_extraction_diagnostics)
        return replace(selection_result, metadata=replace(metadata, metadata_json=metadata_json))

    def _apply_legacy_metadata_fallbacks(self, selection_result):
        """Preserve direct parser-state metadata for non-PDF/synthetic callers."""

        metadata = selection_result.metadata
        fallback_values = {
            "reference": normalize_reference(self._reference),
            "report_date": normalize_report_date(self._date) or self._date,
            "sample_number": normalize_sample_number(self._sample_number),
        }
        replacement_values = {}
        fallback_fields = {}

        for field_name, fallback_value in fallback_values.items():
            if getattr(metadata, field_name) or not fallback_value:
                continue
            replacement_values[field_name] = fallback_value
            fallback_fields[field_name] = "legacy_parser_state"

        if "reference" in replacement_values and not metadata.reference_raw:
            replacement_values["reference_raw"] = self._reference

        if "sample_number" in replacement_values and metadata.sample_number_kind in (None, "unknown"):
            replacement_values["sample_number_kind"] = "unknown"

        if not replacement_values:
            return selection_result

        metadata_json = dict(metadata.metadata_json or {})
        field_sources = dict(metadata_json.get("field_sources") or {})
        field_sources.update(fallback_fields)
        metadata_json["field_sources"] = field_sources
        metadata_json["legacy_fallback_fields"] = tuple(sorted(fallback_fields))
        replacement_values["metadata_json"] = metadata_json

        return replace(selection_result, metadata=replace(metadata, **replacement_values))

    def detect_template_family(self):
        """Return the current template family and variant if metadata is available."""

        if self._metadata_selection_result is None:
            self.extract_metadata()
        metadata = self._metadata_selection_result.metadata
        return metadata.template_family, metadata.template_variant

    @staticmethod
    def _normalize_header(block_header) -> str:
        parts: list[str] = []
        for item in block_header:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, (list, tuple)):
                parts.extend(str(nested) for nested in item if isinstance(nested, str))
        return ", ".join(value.strip() for value in parts if str(value).strip()).replace('"', '')

    @staticmethod
    def _coerce_number(value):
        if value in ("", None):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _status_from_outtol(outtol_value) -> tuple[bool, str]:
        outtol = CMMReportParser._coerce_number(outtol_value)
        if outtol is None:
            return False, "unknown"
        if outtol > 0:
            return True, "nok"
        return False, "ok"

    @staticmethod
    def _characteristic_family(axis_code) -> str:
        normalized = str(axis_code or "").upper()
        if normalized in {"X", "Y", "Z", "TP"}:
            return "LOC"
        if normalized in {"D", "D1", "D2", "D3", "D4", "M"}:
            return "DIST"
        if normalized == "RN":
            return "RNOUT"
        if normalized == "DF":
            return "FLAT"
        if normalized == "PR":
            return "PROF"
        if normalized == "PA":
            return "PARL"
        return "other"

    def parse_measurements(self):
        """Convert parsed measurement blocks into flat report measurement rows."""

        measurement_rows = []
        row_order = 0
        for block in self.blocks_text:
            header = self._normalize_header(block[0]) if len(block) > 0 else ""
            section_name = header or None
            feature_label = header or None
            for row in block[1] if len(block) > 1 else ():
                if not row:
                    continue
                padded = list(row) + [""] * max(0, 8 - len(row))
                row_order += 1
                is_nok, status_code = self._status_from_outtol(padded[7])
                characteristic_family = self._characteristic_family(padded[0])
                measurement_rows.append(
                    {
                        "page_number": None,
                        "row_order": row_order,
                        "header": header,
                        "section_name": section_name,
                        "feature_label": feature_label,
                        "characteristic_name": characteristic_family,
                        "characteristic_family": characteristic_family,
                        "description": header,
                        "ax": str(padded[0]) if padded[0] is not None else "",
                        "nominal": self._coerce_number(padded[1]),
                        "tol_plus": self._coerce_number(padded[2]),
                        "tol_minus": self._coerce_number(padded[3]),
                        "bonus": self._coerce_number(padded[4]),
                        "meas": self._coerce_number(padded[5]),
                        "dev": self._coerce_number(padded[6]),
                        "outtol": self._coerce_number(padded[7]),
                        "is_nok": is_nok,
                        "status_code": status_code,
                        "raw_measurement_json": {
                            "tokens": [str(value) for value in row],
                            "header": header,
                        },
                    }
                )
        self._prepared_measurement_rows = measurement_rows
        return measurement_rows

    def build_report_identity_hash(self):
        """Build a semantic identity hash from selected canonical metadata."""

        if self._metadata_selection_result is None:
            self.extract_metadata()
        self._metadata_identity_hash = build_report_identity_hash(self._metadata_selection_result.metadata)
        return self._metadata_identity_hash

    def to_sqlite(self):
        """Handle `to_sqlite` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            if not any(lst[1] for lst in self.blocks_text):
                logger.warning(
                    "Report '%s' has no measurements data; skipping database insertion.",
                    self.file_name,
                )
                return

            if self._metadata_selection_result is None:
                self.extract_metadata()

            normalize_start = perf_counter()
            measurement_rows = self._normalized_rows_for_persistence()
            self.stage_timings_s["normalize_runtime"] = perf_counter() - normalize_start

            nok_count = sum(1 for row in measurement_rows if row.get("is_nok"))
            measurement_count = len(measurement_rows)
            metadata = self._metadata_selection_result.metadata
            warnings = metadata.warnings
            identity_hash = self._metadata_identity_hash or self.build_report_identity_hash()

            db_write_start = perf_counter()
            repository = ReportRepository(self.database, connection=self.connection)
            repository.persist_parsed_report(
                source_path=Path(self.file_path) / self.file_name,
                parser_id=metadata.parser_id,
                parser_version=self.manifest.version,
                template_family=metadata.template_family,
                template_variant=metadata.template_variant,
                parse_status="parsed_with_warnings" if warnings else "parsed",
                metadata=metadata,
                candidates=self._metadata_selection_result.candidates,
                warnings=warnings,
                measurements=measurement_rows,
                metadata_version="report_metadata_v1",
                metadata_profile_id=DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.template_family,
                metadata_profile_version="1",
                page_count=self._page_count or metadata.page_count,
                measurement_count=measurement_count,
                has_nok=nok_count > 0,
                nok_count=nok_count,
                metadata_confidence=metadata.metadata_confidence,
                identity_hash=identity_hash,
                raw_report_json={
                    "parse_backend": self.parse_backend_used,
                    "measurement_blocks": len(self.blocks_text),
                },
            )
            self.persistence_backend_used = "python"
            self.stage_timings_s["db_write_runtime"] = perf_counter() - db_write_start
            logger.info("Report '%s' measurements inserted into the database.", self.file_name)
            return
        except Exception as e:
            self.log_and_exit(e)

    def _normalized_rows_for_persistence(self, use_native=False):
        if self._prepared_measurement_rows is not None:
            return self._prepared_measurement_rows

        return self.parse_measurements()

    def prepare_for_two_stage_pipeline(self):
        """Prepare parser state and normalized rows for deferred single-writer persistence.

        This stage performs file open/parsing/token normalization work only and stores
        normalized rows on the parser instance so stage 2 can commit without re-parsing.
        """
        prepare_start = perf_counter()
        if not self.raw_text:
            self.open_report()
        if not self.blocks_text:
            self.split_text_to_blocks()
            self.add_tolerances()

        normalize_start = perf_counter()
        if self._metadata_selection_result is None:
            self.extract_metadata()
        self._prepared_measurement_rows = self.parse_measurements()
        self.stage_timings_s["normalize_runtime"] = perf_counter() - normalize_start
        self.stage_timings_s["prepare_pipeline_runtime"] = perf_counter() - prepare_start

    def persist_prepared_report(self):
        """Persist report data prepared during stage 1 of the two-stage pipeline.

        Falls back to legacy open+check behavior when preparation did not complete.
        """
        if not self.blocks_text:
            return self.open_database_and_check_filename()

        return self.to_sqlite()

    def show_df(self):
        """Handle `show_df` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """Prints the dataframe with measurements"""
            logger.debug("%s", self.df)
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        """Handle `log_and_exit` for `CMMReportParser`.

        Args:
            exception (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        CustomLogger(exception, reraise=False)
