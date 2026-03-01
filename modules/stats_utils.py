import math


def _is_valid_number(value):
    return value is not None and isinstance(value, (int, float)) and not math.isnan(value)


def safe_process_capability(nom, usl, lsl, sigma, average):
    """Compute Cp/Cpk safely; returns strings for invalid states."""
    values = (nom, usl, lsl, sigma, average)
    if not all(_is_valid_number(v) for v in values):
        return "N/A", "N/A"

    if sigma == 0:
        return "N/A", "N/A"

    is_one_sided_gdt = nom == 0 and lsl == 0

    cp = "N/A" if is_one_sided_gdt else (usl - lsl) / (6 * sigma)
    if is_one_sided_gdt:
        cpk = (usl - average) / (3 * sigma)
    else:
        cpk = min((usl - average) / (3 * sigma), (average - lsl) / (3 * sigma))

    if isinstance(cp, (int, float)) and math.isnan(cp):
        cp = "N/A"
    if math.isnan(cpk):
        return "N/A", "N/A"

    cp_value = cp if isinstance(cp, str) else round(cp, 2)
    return cp_value, round(cpk, 2)
