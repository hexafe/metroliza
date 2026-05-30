import re


INVALID_SHEET_CHARS_PATTERN = re.compile(r"[\[\]:\*\?/\\]")
MAX_SHEET_NAME_LENGTH = 31


def sanitize_sheet_name(name: str) -> str:
    """Sanitize a candidate worksheet name to be Excel-compatible."""
    text = "" if name is None else str(name)
    sanitized = INVALID_SHEET_CHARS_PATTERN.sub("", text).strip("'")
    sanitized = sanitized.strip()
    if not sanitized:
        sanitized = "Sheet"
    return sanitized[:MAX_SHEET_NAME_LENGTH]


def unique_sheet_name(name: str, used_names: set[str]) -> str:
    """Return a deterministic, unique Excel-safe sheet name."""
    base = sanitize_sheet_name(name)
    lowered = {item.lower() for item in used_names}
    if base.lower() not in lowered:
        used_names.add(base)
        return base

    index = 1
    while True:
        suffix = f"_{index}"
        trimmed_base = base[: MAX_SHEET_NAME_LENGTH - len(suffix)]
        candidate = f"{trimmed_base}{suffix}"
        if candidate.lower() not in lowered:
            used_names.add(candidate)
            return candidate
        index += 1
