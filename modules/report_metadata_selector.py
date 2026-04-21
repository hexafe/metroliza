"""Metadata candidate scoring and selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Mapping, Sequence

from modules.header_ocr_corrections import (
    canonicalize_header_label,
    is_logo_noise_text,
    repair_field_value,
)
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
_TIME_IN_TEXT_RE = re.compile(r"\b(?P<time>\d{1,2}[.:/\-\s]\d{2}(?:[.:/\-\s]\d{2})?)\b")


def _collapse_spaces(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def _normalize_label_text(value: str) -> str:
    text = _collapse_spaces(canonicalize_header_label(value) or value).upper()
    return text.rstrip(":.")


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


def _find_filename_date(tokens: Sequence[str]) -> tuple[int | None, int, str | None]:
    for index in range(len(tokens)):
        for token_count in (1, 2, 3):
            raw_tokens = tokens[index : index + token_count]
            if len(raw_tokens) != token_count:
                continue
            raw_date = ".".join(raw_tokens)
            if re.search(r"[A-Za-z]", raw_date):
                continue
            normalized_date = normalize_report_date(raw_date)
            if normalized_date:
                return index, token_count, normalized_date
    return None, 0, None


def _filename_parts(file_name: str) -> tuple[str | None, str | None, str | None, str | None]:
    stem = Path(file_name).stem
    tokens = [token for token in stem.split("_") if token]

    date_index, date_token_count, date_value = _find_filename_date(tokens)
    sample_value = None

    prefix_tokens = tokens[:date_index] if date_index is not None else tokens
    prefix_text = "_".join(prefix_tokens)
    reference_match = _REFERENCE_RE.match(prefix_text)
    reference = reference_match.group("reference") if reference_match else None

    remainder = prefix_text[len(reference):].lstrip("_") if reference else prefix_text
    part_tokens = [token for token in remainder.split("_") if token]

    if date_index is not None:
        tail_tokens = tokens[date_index + date_token_count :]
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


def _label_words(label_text: str) -> tuple[str, ...]:
    return tuple(part for part in _normalize_label_text(label_text).split() if part)


def _is_label_separator(value: str) -> bool:
    return _normalize_label_text(value) in {"", ":", "-", ":-"}


def _match_label_at(
    row: Sequence[HeaderTextItem],
    index: int,
    profile: MetadataProfile,
) -> tuple[str, str, str, int] | None:
    if index >= len(row):
        return None

    token_label = _normalize_label_text(row[index].text)
    best_match: tuple[str, str, str, int] | None = None
    for field_name in profile.label_aliases:
        label_lookup = _label_lookup(profile, field_name)
        if token_label in label_lookup:
            consumed = index + 1
            while consumed < len(row) and _is_label_separator(row[consumed].text):
                consumed += 1
            return field_name, label_lookup[token_label], row[index].text, consumed - index

        for label_text, source_type in label_lookup.items():
            words = _label_words(label_text)
            if len(words) <= 1:
                continue
            position = index
            matched_items: list[HeaderTextItem] = []
            for word in words:
                if position >= len(row):
                    matched_items = []
                    break
                if _normalize_label_text(row[position].text) != word:
                    matched_items = []
                    break
                matched_items.append(row[position])
                position += 1
            if not matched_items:
                continue
            while position < len(row) and _is_label_separator(row[position].text):
                matched_items.append(row[position])
                position += 1
            label_value = _collapse_spaces(" ".join(item.text for item in matched_items))
            consumed_count = position - index
            if best_match is None or consumed_count > best_match[3]:
                best_match = (field_name, source_type, label_value, consumed_count)

    return best_match


def _source_type_for_header_candidate(field_name: str, source_type: str) -> str:
    if field_name == "sample_number":
        return "explicit_sample_number"
    return source_type


def _normalize_candidate_value(profile: MetadataProfile, field_name: str, raw_value: str | None):
    normalizer = profile.field_normalizers.get(field_name)
    if normalizer is None:
        return raw_value, None
    corrected = repair_field_value(field_name, raw_value)
    normalized = normalizer(corrected.value)
    stats_count_int = None
    if field_name == "stats_count_raw" and isinstance(normalized, tuple):
        normalized_value, stats_count_int = normalized
    elif isinstance(normalized, tuple):
        normalized_value = normalized[0]
    else:
        normalized_value = normalized
    return normalized_value, stats_count_int


def _candidate_correction_details(candidate: MetadataCandidate | None) -> dict | None:
    if candidate is None or candidate.raw_value is None:
        return None
    if candidate.source_type == "filename_candidate":
        return None

    corrected = repair_field_value(candidate.field_name, candidate.raw_value)
    was_corrected = corrected.was_corrected or corrected.value != candidate.raw_value
    return {
        "raw_ocr_value": candidate.raw_value,
        "corrected_input_value": corrected.value,
        "normalized_value": candidate.normalized_value,
        "correction_rule": corrected.rule_id,
        "correction_confidence": corrected.confidence,
        "was_corrected": was_corrected,
        "source_type": candidate.source_type,
        "source_cell": candidate.source_detail,
        "rule_id": candidate.rule_id,
    }


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
            label_match = _match_label_at(normalized_row, index, profile)
            if label_match is None:
                index += 1
                continue
            matched_field, source_type, label_text, consumed_count = label_match

            value_tokens: list[str] = []
            value_items: list[HeaderTextItem] = []
            lookahead = index + consumed_count
            while lookahead < len(normalized_row):
                if _match_label_at(normalized_row, lookahead, profile) is not None:
                    break
                next_item = normalized_row[lookahead]
                value_tokens.append(next_item.text)
                value_items.append(next_item)
                lookahead += 1

            raw_value = _collapse_spaces(" ".join(value_tokens)) if value_tokens else None
            normalized_value, _stats_count_int = _normalize_candidate_value(profile, matched_field, raw_value)
            candidate_source_type = _source_type_for_header_candidate(matched_field, source_type)

            candidates.append(
                MetadataCandidate(
                    field_name=matched_field,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    source_type=candidate_source_type or "header_alias",
                    source_detail=label_text,
                    page_number=token.page_number,
                    region_name=token.region_name or header_region,
                    label_text=label_text,
                    rule_id=f"header:{_normalize_label_text(label_text)}",
                    confidence=0.99 if source_type == "header_exact" else 0.94,
                    evidence_text=row_raw_text,
                )
            )

            index = lookahead

    return candidates


def _strip_field_label(raw_text: str | None, profile: MetadataProfile, field_name: str) -> str | None:
    if raw_text is None:
        return None
    value = _collapse_spaces(raw_text)
    labels = [field_name.replace("_", " "), *profile.label_aliases.get(field_name, ())]
    for label in sorted(labels, key=len, reverse=True):
        label_words = r"\s+".join(re.escape(part) for part in _label_words(label))
        if not label_words:
            continue
        pattern = re.compile(rf"^\s*{label_words}\s*[:.\-]?\s*", re.IGNORECASE)
        stripped = pattern.sub("", value, count=1).strip()
        if stripped != value:
            return stripped or None
    value = value.strip(" :-\t")
    return value or None


def _positional_candidates_from_rows(
    rows: Sequence[Sequence[HeaderTextItem]],
    profile: MetadataProfile,
    variant: str | None,
    page_width: float | None,
) -> list[MetadataCandidate]:
    if variant is None or page_width is None:
        return []
    cells = profile.positional_cells.get(variant, ())
    if not cells:
        return []

    min_x_ratio = min(cell.x0_ratio for cell in cells)
    max_x_ratio = max(cell.x1_ratio for cell in cells)
    min_x = float(page_width) * min_x_ratio
    max_x = float(page_width) * max_x_ratio
    table_rows: list[list[HeaderTextItem]] = []
    for row in rows:
        row_items = [
            item
            for item in row
            if item.x0 is not None
            and item.x1 is not None
            and min_x <= ((float(item.x0) + float(item.x1)) / 2.0) <= max_x
        ]
        if len(row_items) >= 2:
            table_rows.append(row_items)

    candidates: list[MetadataCandidate] = []
    for cell in cells:
        if cell.row_index >= len(table_rows):
            continue
        row = table_rows[cell.row_index]
        cell_x0 = float(page_width) * cell.x0_ratio
        cell_x1 = float(page_width) * cell.x1_ratio
        cell_items = [
            item
            for item in row
            if item.x0 is not None
            and item.x1 is not None
            and cell_x0 <= ((float(item.x0) + float(item.x1)) / 2.0) < cell_x1
        ]
        if not cell_items:
            continue
        cell_items.sort(key=lambda item: (item.x0 if item.x0 is not None else 0.0))
        raw_cell_text = _collapse_spaces(" ".join(item.text for item in cell_items if item.text))
        raw_value = _strip_field_label(raw_cell_text, profile, cell.field_name)
        normalized_value, _stats_count_int = _normalize_candidate_value(profile, cell.field_name, raw_value)
        label_text = raw_cell_text if raw_cell_text != (raw_value or "") else None
        candidates.append(
            MetadataCandidate(
                field_name=cell.field_name,
                raw_value=raw_value,
                normalized_value=normalized_value,
                source_type="position_cell",
                source_detail=cell.source_detail,
                page_number=cell_items[0].page_number,
                region_name=cell_items[0].region_name or "page1_header_band",
                label_text=label_text,
                rule_id=f"position:{variant}:{cell.source_detail}",
                confidence=0.98 if normalized_value is not None else 0.70,
                evidence_text=raw_cell_text,
            )
        )
        if cell.field_name == "report_date" and raw_cell_text:
            time_match = _TIME_IN_TEXT_RE.search(raw_cell_text)
            if time_match:
                raw_time = time_match.group("time")
                normalized_time, _ = _normalize_candidate_value(profile, "report_time", raw_time)
                if normalized_time is not None:
                    candidates.append(
                        MetadataCandidate(
                            field_name="report_time",
                            raw_value=raw_time,
                            normalized_value=normalized_time,
                            source_type="position_cell",
                            source_detail=f"{cell.source_detail}:embedded_time",
                            page_number=cell_items[0].page_number,
                            region_name=cell_items[0].region_name or "page1_header_band",
                            label_text=label_text,
                            rule_id=f"position:{variant}:{cell.source_detail}:embedded_time",
                            confidence=0.96,
                            evidence_text=raw_cell_text,
                        )
                    )

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
        candidates.append(
            MetadataCandidate(
                field_name="sample_number",
                raw_value=sample_tail,
                normalized_value=normalize_sample_number(sample_tail),
                source_type="filename_candidate",
                source_detail="filename_tail",
                page_number=1,
                region_name="filename",
                label_text=None,
                rule_id="filename:sample_number_tail",
                confidence=0.63 if tail_int is not None else 0.42,
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


def _field_selected_source(
    candidates: Sequence[MetadataCandidate],
    field_name: str,
    profile: MetadataProfile,
) -> MetadataCandidate | None:
    field_candidates = [candidate for candidate in candidates if candidate.field_name == field_name]
    if not field_candidates:
        return None

    priority = profile.field_priority_rules.get(field_name, ("unknown",))
    ranking = {source_type: index for index, source_type in enumerate(priority)}
    return sorted(
        field_candidates,
        key=lambda candidate: (
            ranking.get(candidate.source_type, len(ranking) + 1),
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


def _derive_sample_number_from_comment(
    comment_candidate: MetadataCandidate | None,
) -> tuple[MetadataCandidate | None, MetadataWarning | None]:
    if comment_candidate is None or not comment_candidate.normalized_value:
        return None, None

    text = str(comment_candidate.normalized_value).strip()
    explicit_match = re.search(
        r"\b(?:SAMPLE|SAMPLE\s+NUMBER|PROBKA|PRÓBKA|NR)\s*[:=#-]?\s*(?P<value>\d+[A-Za-z]?)\b",
        text,
        re.IGNORECASE,
    )
    if explicit_match:
        value = explicit_match.group("value")
        return (
            MetadataCandidate(
                field_name="sample_number",
                raw_value=text,
                normalized_value=normalize_sample_number(value),
                source_type="comment_derived",
                source_detail="comment_pattern",
                page_number=comment_candidate.page_number,
                region_name=comment_candidate.region_name,
                label_text=comment_candidate.label_text,
                rule_id="projection:comment_to_sample_number",
                confidence=min(comment_candidate.confidence, 0.90),
                evidence_text=comment_candidate.evidence_text,
            ),
            None,
        )

    if re.fullmatch(r"\d+[A-Za-z]?", text):
        return (
            MetadataCandidate(
                field_name="sample_number",
                raw_value=text,
                normalized_value=normalize_sample_number(text),
                source_type="comment_derived",
                source_detail="comment_numeric_value",
                page_number=comment_candidate.page_number,
                region_name=comment_candidate.region_name,
                label_text=comment_candidate.label_text,
                rule_id="projection:comment_numeric_to_sample_number",
                confidence=min(comment_candidate.confidence, 0.86),
                evidence_text=comment_candidate.evidence_text,
            ),
            None,
        )

    numeric_tokens = re.findall(r"\d+", text)
    if len(numeric_tokens) > 1:
        return None, _build_warning(
            "sample_number_comment_ambiguous",
            "sample_number",
            "Comment contains multiple numeric tokens and was not used as sample number.",
            severity="info",
            comment=text,
        )

    return None, None


def _sample_number_kind(candidate: MetadataCandidate | None) -> str:
    if candidate is None:
        return "unknown"
    if candidate.source_type == "explicit_sample_number":
        return "explicit_sample_number"
    if candidate.source_type == "comment_derived":
        return "derived_counter"
    if candidate.source_type == "projected_from_stats_count":
        return "stats_count"
    if candidate.source_type == "filename_candidate":
        return "filename_tail"
    return "unknown"


def select_report_metadata(
    *,
    context,
    profile: MetadataProfile,
    header_items: Sequence[object] | None = None,
    filename: str | None = None,
    ocr_fallback=None,
) -> MetadataSelectionResult:
    items = []
    for raw_item in header_items or ():
        item = _as_text_item(raw_item)
        if is_logo_noise_text(item.text, y0=item.y0):
            continue
        items.append(item)
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
    positional_candidates = _positional_candidates_from_rows(
        header_rows,
        profile,
        variant,
        context.first_page_width,
    )
    filename_candidates = _filename_candidates(profile, filename or context.file_name)
    all_candidates = header_candidates + positional_candidates + filename_candidates

    selected: dict[str, MetadataCandidate | None] = {}
    field_names = tuple(profile.field_priority_rules)
    for field_name in field_names:
        if field_name == "sample_number":
            continue
        candidate = _field_selected_source(all_candidates, field_name, profile)
        selected[field_name] = candidate

    sample_candidates = [candidate for candidate in all_candidates if candidate.field_name == "sample_number"]
    comment_sample_candidate, comment_warning = _derive_sample_number_from_comment(selected.get("comment"))
    if comment_warning is not None:
        warnings.append(comment_warning)
    if comment_sample_candidate is not None:
        sample_candidates.append(comment_sample_candidate)

    stats_source_candidate = selected.get("stats_count_raw")
    stats_sample_candidate = None
    if stats_source_candidate is not None and stats_source_candidate.source_type != "filename_candidate":
        stats_sample_candidate = _project_sample_number(stats_source_candidate)
    if stats_sample_candidate is not None:
        sample_candidates.append(stats_sample_candidate)

    sample_candidate = _field_selected_source(sample_candidates, "sample_number", profile)
    selected["sample_number"] = sample_candidate
    if sample_candidate is not None and sample_candidate.source_type == "projected_from_stats_count":
        warnings.append(
            _build_warning(
                "sample_number_projected_from_stats_count",
                "sample_number",
                "Sample number was projected from stats count.",
            )
        )
    elif sample_candidate is not None and sample_candidate.source_type == "comment_derived":
        warnings.append(
            _build_warning(
                "sample_number_derived_from_comment",
                "sample_number",
                "Sample number was derived from comment.",
                severity="info",
            )
        )

    header_or_position_candidates = header_candidates + positional_candidates
    if not any(
        candidate.source_type in {"header_exact", "header_alias", "position_cell", "explicit_sample_number"}
        for candidate in header_or_position_candidates
    ):
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
        "reference": _field_selected_source(filename_candidates, "reference", profile),
        "report_date": _field_selected_source(filename_candidates, "report_date", profile),
        "stats_count_raw": _field_selected_source(filename_candidates, "stats_count_raw", profile),
    }))

    selected_metadata = {
        "reference": selected.get("reference").normalized_value if selected.get("reference") else None,
        "reference_raw": selected.get("reference").raw_value if selected.get("reference") else None,
        "report_date": selected.get("report_date").normalized_value if selected.get("report_date") else None,
        "report_time": selected.get("report_time").normalized_value if selected.get("report_time") else None,
        "part_name": selected.get("part_name").normalized_value if selected.get("part_name") else normalize_part_name(_filename_parts(filename or context.file_name)[2], from_filename=True),
        "revision": selected.get("revision").normalized_value if selected.get("revision") else None,
        "sample_number": selected.get("sample_number").normalized_value if selected.get("sample_number") else None,
        "sample_number_kind": _sample_number_kind(selected.get("sample_number")),
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
    all_candidates_with_derived = all_candidates + [
        candidate for candidate in (comment_sample_candidate, stats_sample_candidate) if candidate is not None
    ]
    for candidate in all_candidates_with_derived:
        chosen = selected.get(candidate.field_name)
        candidates_with_selection.append(
            replace(candidate, selected=chosen == candidate)
        )

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
            "field_corrections": {
                field_name: details
                for field_name, candidate in selected.items()
                if (details := _candidate_correction_details(candidate)) is not None
            },
            "sample_number_provenance": selected.get("sample_number").source_type
            if selected.get("sample_number")
            else None,
        },
        warnings=warnings,
    )

    return MetadataSelectionResult(metadata=metadata, candidates=tuple(candidates_with_selection))
