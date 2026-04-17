"""Metadata candidate scoring and selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Mapping, Sequence

from modules.report_metadata_models import (
    CanonicalReportMetadata,
    MetadataCandidate,
    MetadataSelectionResult,
    MetadataWarning,
)
from modules.report_metadata_normalizers import (
    normalize_part_name,
    normalize_reference,
    normalize_report_date,
    normalize_sample_number,
    normalize_stats_count,
)
from modules.report_metadata_profiles import MetadataProfile


@dataclass(frozen=True)
class HeaderTextItem:
    text: str
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    page_number: int | None = None
    region_name: str | None = None


_SPACE_RE = re.compile(r"\s+")
_REFERENCE_RE = re.compile(r"^(?P<reference>([A-Z][A-Za-z0-9]{4,}\d{1,5}(?:_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5}))")
_DATE_RE = re.compile(r"(\d{4}[.\-/_]\d{1,2}[.\-/_]\d{1,2})")


def _collapse_spaces(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def _normalize_label_text(value: str) -> str:
    text = _collapse_spaces(value).upper()
    return text[:-1] if text.endswith(":") else text


def _as_text_item(item) -> HeaderTextItem:
    if isinstance(item, HeaderTextItem):
        return item
    if isinstance(item, str):
        return HeaderTextItem(text=item)
    if isinstance(item, Mapping):
        return HeaderTextItem(
            text=str(item.get("text", "")),
            x0=item.get("x0"),
            y0=item.get("y0"),
            x1=item.get("x1"),
            y1=item.get("y1"),
            page_number=item.get("page_number"),
            region_name=item.get("region_name"),
        )
    raise TypeError(f"Unsupported header item type: {type(item)!r}")


def _within_header_band(item: HeaderTextItem, page_height: float | None, header_band_fraction: float) -> bool:
    if page_height is None or item.y0 is None:
        return True
    return item.y0 <= page_height * header_band_fraction


def _group_rows(items: Sequence[HeaderTextItem], page_height: float | None, header_band_fraction: float) -> list[list[HeaderTextItem]]:
    selected = [item for item in items if item.text.strip() and _within_header_band(item, page_height, header_band_fraction)]
    if not selected:
        return []

    selected.sort(key=lambda item: ((item.y0 if item.y0 is not None else 0.0), (item.x0 if item.x0 is not None else 0.0)))

    rows: list[list[HeaderTextItem]] = []
    current_row: list[HeaderTextItem] = []
    current_y: float | None = None
    for item in selected:
        y_value = item.y0 if item.y0 is not None else 0.0
        if current_row and current_y is not None and abs(y_value - current_y) > 4.0:
            rows.append(current_row)
            current_row = [item]
            current_y = y_value
        else:
            current_row.append(item)
            current_y = y_value if current_y is None else (current_y + y_value) / 2.0
    if current_row:
        rows.append(current_row)
    return rows


def _row_text(row: Sequence[HeaderTextItem]) -> str:
    return _collapse_spaces(" ".join(item.text for item in row if item.text))


def _header_text(items: Sequence[HeaderTextItem], page_height: float | None, header_band_fraction: float) -> str:
    return " | ".join(_row_text(row) for row in _group_rows(items, page_height, header_band_fraction))


def _filename_parts(file_name: str) -> tuple[str | None, str | None, str | None, str | None]:
    stem = Path(file_name).stem
    tokens = [token for token in stem.split("_") if token]

    date_index = None
    date_value = None
    sample_value = None
    for index, token in enumerate(tokens):
        normalized_date = normalize_report_date(token)
        if normalized_date:
            date_index = index
            date_value = normalized_date
            break

    prefix_tokens = tokens[:date_index] if date_index is not None else tokens
    prefix_text = "_".join(prefix_tokens)
    reference_match = _REFERENCE_RE.match(prefix_text)
    reference = reference_match.group("reference") if reference_match else None

    remainder = prefix_text[len(reference):].lstrip("_") if reference else prefix_text
    part_tokens = [token for token in remainder.split("_") if token]

    if date_index is not None:
        tail_tokens = tokens[date_index + 1 :]
        if tail_tokens:
            sample_value = tail_tokens[-1]
    elif len(tokens) > 1:
        sample_value = tokens[-1]
        part_tokens = tokens[:-1]

    part_name = normalize_part_name("_".join(part_tokens), from_filename=True) if part_tokens else None
    return reference, date_value, part_name, sample_value


def _label_lookup(profile: MetadataProfile, field_name: str) -> dict[str, str]:
    aliases = profile.label_aliases.get(field_name, ())
    exact_label = field_name.replace("_", " ").upper()
    lookup = {exact_label: "header_exact"}
    for alias in aliases:
        lookup[_normalize_label_text(alias)] = "header_alias" if _normalize_label_text(alias) != exact_label else "header_exact"
    return lookup


def _value_candidates_from_rows(
    rows: Sequence[Sequence[HeaderTextItem]],
    profile: MetadataProfile,
) -> list[MetadataCandidate]:
    candidates: list[MetadataCandidate] = []
    header_region = "page1_header_band"
    for row in rows:
        normalized_row = [item for item in row if item.text.strip()]
        if not normalized_row:
            continue

        row_raw_text = _row_text(normalized_row)
        index = 0
        while index < len(normalized_row):
            token = normalized_row[index]
            token_label = _normalize_label_text(token.text)
            matched_field = None
            source_type = None
            for field_name in profile.label_aliases:
                label_lookup = _label_lookup(profile, field_name)
                if token_label in label_lookup:
                    matched_field = field_name
                    source_type = label_lookup[token_label]
                    break
            if matched_field is None:
                index += 1
                continue

            value_tokens: list[str] = []
            value_items: list[HeaderTextItem] = []
            lookahead = index + 1
            while lookahead < len(normalized_row):
                next_item = normalized_row[lookahead]
                next_label = _normalize_label_text(next_item.text)
                if any(next_label in _label_lookup(profile, field_name) for field_name in profile.label_aliases):
                    break
                value_tokens.append(next_item.text)
                value_items.append(next_item)
                lookahead += 1

            raw_value = _collapse_spaces(" ".join(value_tokens)) if value_tokens else None
            normalizer = profile.field_normalizers.get(matched_field)
            normalized_value = None
            stats_count_int = None
            if normalizer is not None:
                normalized = normalizer(raw_value)
                if matched_field == "stats_count_raw" and isinstance(normalized, tuple):
                    normalized_value, stats_count_int = normalized
                elif isinstance(normalized, tuple):
                    normalized_value = normalized[0]
                else:
                    normalized_value = normalized

            candidates.append(
                MetadataCandidate(
                    field_name=matched_field,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    source_type=source_type or "header_alias",
                    source_detail=token.text,
                    page_number=token.page_number,
                    region_name=token.region_name or header_region,
                    label_text=token.text,
                    rule_id=f"header:{_normalize_label_text(token.text)}",
                    confidence=0.99 if source_type == "header_exact" else 0.94,
                    evidence_text=row_raw_text,
                )
            )

            index = lookahead

    return candidates


def _filename_candidates(profile: MetadataProfile, file_name: str) -> list[MetadataCandidate]:
    reference, date_value, part_name, sample_tail = _filename_parts(file_name)
    stem = Path(file_name).stem
    candidates: list[MetadataCandidate] = []

    if reference:
        candidates.append(
            MetadataCandidate(
                field_name="reference",
                raw_value=reference,
                normalized_value=normalize_reference(reference),
                source_type="filename_candidate",
                source_detail="filename_reference",
                page_number=1,
                region_name="filename",
                label_text=None,
                rule_id="filename:reference",
                confidence=0.74,
                evidence_text=stem,
            )
        )

    if date_value:
        candidates.append(
            MetadataCandidate(
                field_name="report_date",
                raw_value=date_value,
                normalized_value=date_value,
                source_type="filename_candidate",
                source_detail="filename_date",
                page_number=1,
                region_name="filename",
                label_text=None,
                rule_id="filename:date",
                confidence=0.72,
                evidence_text=stem,
            )
        )

    if part_name:
        candidates.append(
            MetadataCandidate(
                field_name="part_name",
                raw_value=part_name,
                normalized_value=normalize_part_name(part_name, from_filename=False),
                source_type="filename_candidate",
                source_detail="filename_middle_tokens",
                page_number=1,
                region_name="filename",
                label_text=None,
                rule_id="filename:part_name",
                confidence=0.66,
                evidence_text=stem,
            )
        )

    if sample_tail:
        normalized_tail, tail_int = normalize_stats_count(sample_tail)
        candidates.append(
            MetadataCandidate(
                field_name="stats_count_raw",
                raw_value=sample_tail,
                normalized_value=normalized_tail,
                source_type="filename_candidate",
                source_detail="filename_tail",
                page_number=1,
                region_name="filename",
                label_text=None,
                rule_id="filename:tail",
                confidence=0.68 if tail_int is not None else 0.45,
                evidence_text=stem,
            )
        )

    return candidates


def _project_sample_number(stats_candidate: MetadataCandidate | None) -> MetadataCandidate | None:
    if stats_candidate is None or stats_candidate.normalized_value is None:
        return None
    return MetadataCandidate(
        field_name="sample_number",
        raw_value=stats_candidate.raw_value,
        normalized_value=normalize_sample_number(stats_candidate.normalized_value),
        source_type="projected_from_stats_count",
        source_detail=stats_candidate.source_detail,
        page_number=stats_candidate.page_number,
        region_name=stats_candidate.region_name,
        label_text=stats_candidate.label_text,
        rule_id="projection:stats_count_to_sample_number",
        confidence=min(stats_candidate.confidence, 0.93),
        evidence_text=stats_candidate.evidence_text,
    )


def _field_selected_source(candidates: Sequence[MetadataCandidate], field_name: str) -> MetadataCandidate | None:
    field_candidates = [candidate for candidate in candidates if candidate.field_name == field_name]
    if not field_candidates:
        return None

    ranking = {
        "header_exact": 0,
        "header_alias": 1,
        "projected_from_stats_count": 2,
        "filename_candidate": 3,
        "ocr_candidate": 4,
        "unknown": 5,
    }
    return sorted(
        field_candidates,
        key=lambda candidate: (
            ranking.get(candidate.source_type, 99),
            -candidate.confidence,
            candidate.rule_id,
        ),
    )[0]


def _build_warning(code: str, field_name: str | None, message: str, *, severity: str = "warning", **details) -> MetadataWarning:
    return MetadataWarning(code=code, field_name=field_name, severity=severity, message=message, details=details)


def _apply_conflict_warnings(
    selected: dict[str, MetadataCandidate | None],
    filename_candidates: dict[str, MetadataCandidate | None],
) -> tuple[MetadataWarning, ...]:
    warnings: list[MetadataWarning] = []

    conflict_map = {
        "reference": "header_reference_conflicts_with_filename",
        "report_date": "header_date_conflicts_with_filename",
        "stats_count_raw": "stats_count_conflicts_with_filename_tail",
    }
    missing_map = {
        "reference": "missing_header_reference_fallback_to_filename",
        "report_date": "missing_header_date_fallback_to_filename",
        "stats_count_raw": "missing_header_stats_count_fallback_to_filename",
    }

    for field_name, conflict_code in conflict_map.items():
        chosen = selected.get(field_name)
        fallback = filename_candidates.get(field_name)
        if chosen is not None and fallback is not None:
            if chosen.normalized_value != fallback.normalized_value and chosen.source_type != "filename_candidate":
                warnings.append(
                    _build_warning(
                        conflict_code,
                        field_name,
                        f"Header value for {field_name} conflicts with filename fallback.",
                        chosen=chosen.normalized_value,
                        filename=fallback.normalized_value,
                    )
                )
        elif chosen is None and fallback is not None:
            warnings.append(
                _build_warning(
                    missing_map[field_name],
                    field_name,
                    f"Selected {field_name} from filename fallback.",
                    filename=fallback.normalized_value,
                )
            )

    return tuple(warnings)


def select_report_metadata(
    *,
    context,
    profile: MetadataProfile,
    header_items: Sequence[object] | None = None,
    filename: str | None = None,
    ocr_fallback=None,
) -> MetadataSelectionResult:
    items = [_as_text_item(item) for item in (header_items or ())]
    page_height = context.first_page_height
    header_rows = _group_rows(items, page_height, profile.header_band_fraction)
    header_text = _header_text(items, page_height, profile.header_band_fraction)

    warnings: list[MetadataWarning] = []
    if not header_rows:
        warnings.append(
            _build_warning(
                "insufficient_header_text",
                None,
                "No structured header text was available in the first-page header band.",
            )
        )

    variant, variant_warnings = profile.template_variant_detector(header_text)
    warnings.extend(variant_warnings)

    header_candidates = _value_candidates_from_rows(header_rows, profile)
    filename_candidates = _filename_candidates(profile, filename or context.file_name)
    all_candidates = header_candidates + filename_candidates

    selected: dict[str, MetadataCandidate | None] = {}
    for field_name in (
        "reference",
        "report_date",
        "report_time",
        "part_name",
        "revision",
        "stats_count_raw",
        "sample_number",
        "operator_name",
        "comment",
    ):
        candidate = _field_selected_source(all_candidates, field_name)
        selected[field_name] = candidate

    sample_candidate = selected.get("sample_number")
    if sample_candidate is None:
        sample_candidate = _project_sample_number(selected.get("stats_count_raw"))
        if sample_candidate is not None:
            selected["sample_number"] = sample_candidate
            warnings.append(
                _build_warning(
                    "sample_number_projected_from_stats_count",
                    "sample_number",
                    "Sample number was projected from stats count.",
                )
            )

    if not any(candidate.source_type.startswith("header") for candidate in header_candidates):
        if ocr_fallback is None and header_rows:
            warnings.append(
                _build_warning(
                    "ocr_unavailable_for_header_fallback",
                    None,
                    "OCR fallback was unavailable while structured header extraction remained insufficient.",
                    severity="info",
                )
            )

    warnings.extend(_apply_conflict_warnings(selected, {
        "reference": _field_selected_source(filename_candidates, "reference"),
        "report_date": _field_selected_source(filename_candidates, "report_date"),
        "stats_count_raw": _field_selected_source(filename_candidates, "stats_count_raw"),
    }))

    selected_metadata = {
        "reference": selected.get("reference").normalized_value if selected.get("reference") else None,
        "reference_raw": selected.get("reference").raw_value if selected.get("reference") else None,
        "report_date": selected.get("report_date").normalized_value if selected.get("report_date") else None,
        "report_time": selected.get("report_time").normalized_value if selected.get("report_time") else None,
        "part_name": selected.get("part_name").normalized_value if selected.get("part_name") else normalize_part_name(_filename_parts(filename or context.file_name)[2], from_filename=True),
        "revision": selected.get("revision").normalized_value if selected.get("revision") else None,
        "sample_number": selected.get("sample_number").normalized_value if selected.get("sample_number") else None,
        "sample_number_kind": "explicit_sample_number"
        if selected.get("sample_number") and selected.get("sample_number").source_type == "explicit_sample_number"
        else "stats_count"
        if selected.get("sample_number") and selected.get("sample_number").source_type == "projected_from_stats_count"
        else "filename_tail"
        if selected.get("sample_number") and selected.get("sample_number").source_type == "filename_candidate"
        else "unknown",
        "stats_count_raw": selected.get("stats_count_raw").normalized_value if selected.get("stats_count_raw") else None,
        "stats_count_int": None,
        "operator_name": selected.get("operator_name").normalized_value if selected.get("operator_name") else None,
        "comment": selected.get("comment").normalized_value if selected.get("comment") else None,
    }

    if selected.get("stats_count_raw") and isinstance(selected.get("stats_count_raw").normalized_value, str):
        _, stats_count_int = normalize_stats_count(selected["stats_count_raw"].normalized_value)
        selected_metadata["stats_count_int"] = stats_count_int

    confidence_values = [candidate.confidence for candidate in selected.values() if candidate is not None and candidate.normalized_value is not None]
    metadata_confidence = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0

    candidates_with_selection = []
    for candidate in all_candidates:
        chosen = selected.get(candidate.field_name)
        candidates_with_selection.append(
            replace(candidate, selected=chosen == candidate)
        )
    if sample_candidate is not None and sample_candidate.field_name == "sample_number" and sample_candidate not in candidates_with_selection:
        candidates_with_selection.append(replace(sample_candidate, selected=True))

    page_count = context.page_count
    metadata = CanonicalReportMetadata(
        parser_id=profile.parser_id,
        template_family=profile.template_family,
        template_variant=variant,
        metadata_confidence=metadata_confidence,
        reference=selected_metadata["reference"],
        reference_raw=selected_metadata["reference_raw"],
        report_date=selected_metadata["report_date"],
        report_time=selected_metadata["report_time"],
        part_name=selected_metadata["part_name"],
        revision=selected_metadata["revision"],
        sample_number=selected_metadata["sample_number"],
        sample_number_kind=selected_metadata["sample_number_kind"],
        stats_count_raw=selected_metadata["stats_count_raw"],
        stats_count_int=selected_metadata["stats_count_int"],
        operator_name=selected_metadata["operator_name"],
        comment=selected_metadata["comment"],
        page_count=page_count,
        metadata_json={
            "filename": filename or context.file_name,
            "header_text": header_text,
            "field_sources": {
                field_name: candidate.source_type if candidate is not None else None
                for field_name, candidate in selected.items()
            },
        },
        warnings=warnings,
    )

    return MetadataSelectionResult(metadata=metadata, candidates=tuple(candidates_with_selection))
