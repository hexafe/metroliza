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

    cp = (usl - lsl) / (6 * sigma)
    if nom == 0 and lsl == 0:
        cpk = (usl - average) / (3 * sigma)
    else:
        cpk = min((usl - average) / (3 * sigma), (average - lsl) / (3 * sigma))

    if math.isnan(cp) or math.isnan(cpk):
        return "N/A", "N/A"

    return round(cp, 2), round(cpk, 2)
