"""Deterministic post-processing rules for CMM header OCR text."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import re
import unicodedata
from typing import Iterable, Sequence


@dataclass(frozen=True)
class CorrectedText:
    value: str | None
    rule_id: str | None = None
    confidence: float = 1.0

    @property
    def was_corrected(self) -> bool:
        return self.rule_id is not None


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_REFERENCE_LIKE_RE = re.compile(r"^(?:V[A-Z0-9]*\d(?:_\d{3})?|VSPC\d+|AM[-_]\d+[-_]\d+)$", re.IGNORECASE)
_TIME_SEPARATOR_RE = re.compile(r"^\s*(\d{1,2})[;.,/\-\s:]+(\d{1,2})(?:[;.,/\-\s:]+(\d{1,2}))?\s*$")

_LABEL_ALIASES = {
    "PARTNAME": "PART NAME",
    "PARTNANE": "PART NAME",
    "NANE": "NAME",
    "DRAWINGREV": "DRAWING REV",
    "DRAWINGNO": "DRAWING No",
    "DRAWINGN0": "DRAWING No",
    "REVNUMBER": "REV NUMBER",
    "REVNUMBERE": "REV NUMBER",
    "REVNUNBER": "REV NUMBER",
    "NUMBERE": "NUMBER",
    "NUNBER": "NUMBER",
    "SERNUMBER": "SER NUMBER",
    "SERNUNBER": "SER NUMBER",
    "SERIALNUMBER": "SER NUMBER",
    "STATSCOUNT": "STATS COUNT",
    "STATSC0UNT": "STATS COUNT",
    "C0UNT": "COUNT",
    "MEASUREMENTMADEBY": "MEASUREMENT MADE BY",
    "MEASUREMENTNADEBY": "MEASUREMENT MADE BY",
    "MEASUREMENTONREXCMM": "MEASUREMENT MADE BY",
    "NADE": "MADE",
}
_LABEL_FIELDS = {
    "PARTNAME": "part_name",
    "DRAWINGREV": "revision",
    "DRAWINGNO": "reference",
    "DRAWINGN0": "reference",
    "REVNUMBER": "revision",
    "SERNUMBER": "reference",
    "SERIALNUMBER": "reference",
    "STATSCOUNT": "stats_count_raw",
    "MEASUREMENTMADEBY": "operator_name",
    "MEASUREMENTONREXCMM": "operator_name",
    "COMMENT": "comment",
    "DATE": "report_date",
    "TIME": "report_time",
}
_LOGO_NOISE = {"VAL", "VALC", "VALE", "VALEO", "EO", "LEO", "LOGO"}
_TOP_BAND_NOISE = {"PAM"}

_POLISH_MONTHS = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "wrzesnia",
    "pazdziernika",
    "listopada",
    "grudnia",
)
_POLISH_MONTH_DISPLAY = {
    "stycznia": "stycznia",
    "lutego": "lutego",
    "marca": "marca",
    "kwietnia": "kwietnia",
    "maja": "maja",
    "czerwca": "czerwca",
    "lipca": "lipca",
    "sierpnia": "sierpnia",
    "wrzesnia": "września",
    "pazdziernika": "października",
    "listopada": "listopada",
    "grudnia": "grudnia",
}
_MONTH_ALIASES = {
    "września": "wrzesnia",
    "wrzesnla": "wrzesnia",
    "października": "pazdziernika",
    "pazdziernika": "pazdziernika",
    "paZdziernika": "pazdziernika",
    "stycznla": "stycznia",
}
_OPERATOR_ALIASES = {
    "PAM JAKBIEC S": "PAM_Jakubiec S.",
    "PAM JAKUBIEC S": "PAM_Jakubiec S.",
    "PAM MW": "PAM_MW",
    "PAM GAZDA": "PAM_GAZDA",
    "REX GAZDA": "REX_GAZDA",
    "REX STACHURA": "REX_Stachura",
}


def collapse_spaces(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _SPACE_RE.sub(" ", text)


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def compact_token(value: str | None) -> str:
    text = strip_accents(str(value or "")).upper()
    return _NON_ALNUM_RE.sub("", text)


def is_logo_noise_text(value: str | None, *, y0: float | None = None) -> bool:
    compact = compact_token(value)
    if compact in _LOGO_NOISE:
        return True
    return y0 is not None and y0 < 20.0 and compact in _TOP_BAND_NOISE


def is_logo_noise(value: str | None) -> bool:
    return is_logo_noise_text(value)


def canonicalize_label(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)
    compact = compact_token(text)
    canonical = _LABEL_ALIASES.get(compact)
    if canonical is None:
        return CorrectedText(text)
    if canonical == text:
        return CorrectedText(text)
    return CorrectedText(canonical, rule_id=f"label_alias:{compact.lower()}", confidence=0.99)


def canonicalize_header_label(value: str | None) -> str | None:
    return canonicalize_label(value).value


def canonicalize_header_field_name(value: str | None) -> str | None:
    canonical = canonicalize_label(value).value
    return _LABEL_FIELDS.get(compact_token(canonical))


def canonicalize_header_text_for_variant(value: str) -> str:
    tokens = []
    for raw_token in re.split(r"(\s+|\|)", value):
        if not raw_token or raw_token.isspace() or raw_token == "|":
            tokens.append(raw_token)
            continue
        corrected = canonicalize_label(raw_token)
        tokens.append(corrected.value or raw_token)
    return "".join(tokens)


def filter_noise_items(items: Sequence[object]) -> list[object]:
    filtered = []
    for item in items:
        text = item.text if hasattr(item, "text") else item.get("text", "") if isinstance(item, dict) else str(item)
        y0 = item.y0 if hasattr(item, "y0") else item.get("y0") if isinstance(item, dict) else None
        try:
            y0_value = float(y0) if y0 is not None else None
        except (TypeError, ValueError):
            y0_value = None
        if is_logo_noise_text(text, y0=y0_value):
            continue
        filtered.append(item)
    return filtered


def repair_reference_text(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)
    candidate = text.replace(" ", "").replace("-", "_") if text.upper().startswith(("V", "VSPC")) else text.strip()
    candidate = re.sub(r"(?<=\d)O(?=\d|_|\b)", "0", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"(?<=V)O(?=\d)", "0", candidate, flags=re.IGNORECASE)
    if _REFERENCE_LIKE_RE.match(candidate):
        return CorrectedText(candidate, rule_id="reference:ocr_confusions" if candidate != text else None, confidence=0.96)
    return CorrectedText(text)


def repair_date_text(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)

    repaired = correct_polish_month_ocr_text(text)
    repaired = re.sub(r"(?i)([a-ząćęłńóśźż]+)(\d{1,2})", r"\1 \2", repaired)
    repaired = re.sub(r"(\d{1,2}),(\d{4})", r"\1, \2", repaired)

    return CorrectedText(
        repaired,
        rule_id="date:polish_month_ocr" if repaired != text else None,
        confidence=0.94,
    )


def _canonical_month_word(word: str) -> str | None:
    lower_word = strip_accents(word).lower()
    canonical = _MONTH_ALIASES.get(lower_word, lower_word)
    if canonical in _POLISH_MONTHS:
        return canonical
    match = get_close_matches(canonical, _POLISH_MONTHS, n=1, cutoff=0.82)
    return match[0] if match else None


def correct_polish_month_ocr_text(value: str | None) -> str | None:
    text = collapse_spaces(value)
    if text is None:
        return None

    repaired = text
    for word in re.findall(r"[A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", text):
        canonical = _canonical_month_word(word)
        if canonical is None:
            continue
        repaired = re.sub(
            re.escape(word),
            _POLISH_MONTH_DISPLAY[canonical],
            repaired,
            count=1,
            flags=re.IGNORECASE,
        )
    return repaired


def repair_time_text(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)
    match = _TIME_SEPARATOR_RE.match(text)
    if not match:
        return CorrectedText(text)
    hour, minute, second = match.groups()
    repaired = f"{int(hour):02d}:{int(minute):02d}" if second is None else f"{int(hour):02d}:{int(minute):02d}:{int(second):02d}"
    return CorrectedText(repaired, rule_id="time:separator_normalized" if repaired != text else None, confidence=0.98)


def _operator_key(value: str) -> str:
    text = strip_accents(value).upper().replace("_", " ")
    text = re.sub(r"[^A-Z0-9 ]+", "", text)
    return _SPACE_RE.sub(" ", text).strip()


def repair_operator_name(value: str | None, *, known_operators: Iterable[str] | None = None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)
    stripped_label = re.sub(
        r"^(?:MEASUREMENT\s*)?(?:MADE\s*BY|MADEBY)\s*[:.\-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if stripped_label:
        text = stripped_label
    key = _operator_key(text)
    if key in _OPERATOR_ALIASES:
        return CorrectedText(_OPERATOR_ALIASES[key], rule_id=f"operator_alias:{key.lower().replace(' ', '_')}", confidence=0.97)

    if known_operators:
        lookup = {_operator_key(operator): operator for operator in known_operators}
        match = get_close_matches(key, tuple(lookup), n=1, cutoff=0.92)
        if match:
            return CorrectedText(lookup[match[0]], rule_id="operator_known_list:fuzzy", confidence=0.94)

    normalized = text
    if key.startswith("PAM ") or key.startswith("REX "):
        prefix, _, suffix = normalized.partition(" ")
        normalized = f"{prefix}_{suffix}" if suffix else prefix
    return CorrectedText(normalized, rule_id="operator:separator" if normalized != text else None, confidence=0.90)


def repair_part_name(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    if text is None:
        return CorrectedText(None)
    repaired = text.replace("_", " ")
    repaired = re.sub(r"(?<=[a-z])(?=EA\d{3}\b)", " ", repaired)
    repaired = re.sub(r"\b(EGR valve EA)\s+(897)\b", r"\1\2", repaired, flags=re.IGNORECASE)
    repaired = collapse_spaces(repaired) or repaired
    return CorrectedText(repaired, rule_id="part_name:separator" if repaired != text else None, confidence=0.85)


def repair_comment(value: str | None) -> CorrectedText:
    text = collapse_spaces(value)
    return CorrectedText(text)


def correct_reference_ocr_text(value: str | None) -> str | None:
    return repair_reference_text(value).value


def correct_operator_name_ocr_text(value: str | None) -> str | None:
    return repair_operator_name(value).value


def correct_part_name_ocr_text(value: str | None) -> str | None:
    return repair_part_name(value).value


def preserve_comment_text(value: str | None) -> str | None:
    text = _stringify_preserve_inner_spaces(value)
    return text


def _stringify_preserve_inner_spaces(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def repair_field_value(field_name: str, value: str | None) -> CorrectedText:
    if field_name == "reference":
        return repair_reference_text(value)
    if field_name == "report_date":
        return repair_date_text(value)
    if field_name == "report_time":
        return repair_time_text(value)
    if field_name == "operator_name":
        return repair_operator_name(value)
    if field_name == "part_name":
        return repair_part_name(value)
    if field_name == "comment":
        return repair_comment(value)
    return CorrectedText(collapse_spaces(value))


def correct_header_ocr_value(field_name: str, value: str | None) -> str | None:
    return repair_field_value(field_name, value).value


def postprocess_header_ocr_item(item: object) -> dict:
    if isinstance(item, dict):
        result = dict(item)
    else:
        result = {"text": item.text if hasattr(item, "text") else str(item)}

    text = str(result.get("text", "")).strip()
    label_field = canonicalize_header_field_name(text)
    if label_field is not None:
        result["text"] = canonicalize_header_label(text)
        result.setdefault("canonical_field_name", label_field)
        return result

    field_name = result.get("field_name")
    if field_name:
        result["text"] = correct_header_ocr_value(str(field_name), text)
    else:
        result["text"] = canonicalize_header_label(text)
    return result


def postprocess_header_ocr_items(items: Sequence[object]) -> list[dict]:
    processed: list[dict] = []
    for item in items:
        text = item.text if hasattr(item, "text") else item.get("text", "") if isinstance(item, dict) else str(item)
        y0 = item.y0 if hasattr(item, "y0") else item.get("y0") if isinstance(item, dict) else None
        try:
            y0_value = float(y0) if y0 is not None else None
        except (TypeError, ValueError):
            y0_value = None
        if is_logo_noise_text(text, y0=y0_value):
            continue
        result = postprocess_header_ocr_item(item)
        if result.get("text"):
            processed.append(result)
    return processed
