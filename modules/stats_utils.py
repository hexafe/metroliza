import math

from scipy.stats import chi2, norm


def _is_valid_number(value):
    return value is not None and isinstance(value, (int, float)) and not math.isnan(value)


def _is_zeroish(value, tolerance=1e-12):
    return abs(value) <= tolerance


def is_one_sided_geometric_tolerance(nom, lsl):
    """Return whether limits represent one-sided GD&T-style tolerance."""
    return _is_zeroish(nom) and _is_zeroish(lsl)


def safe_process_capability(nom, usl, lsl, sigma, average):
    """Compute Cp/Cpk safely; returns strings for invalid states."""
    values = (nom, usl, lsl, sigma, average)
    if not all(_is_valid_number(v) for v in values):
        return "N/A", "N/A"

    if sigma == 0:
        return "N/A", "N/A"

    is_one_sided_gdt = is_one_sided_geometric_tolerance(nom, lsl)

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


def compute_capability_confidence_intervals(*, sample_size, cp=None, cpk=None, alpha=0.05):
    """Compute approximate two-sided confidence intervals for capability indexes.

    Returned structure intentionally keeps nullable values so rendering and export
    callers can opt-in without special-case exception handling.
    """

    n = int(sample_size or 0)
    if n < 2:
        return {'cp': None, 'cpk': None}

    dof = n - 1
    alpha = float(alpha)
    z_value = float(norm.ppf(1.0 - alpha / 2.0))

    cp_interval = None
    if isinstance(cp, (int, float)) and math.isfinite(cp) and cp >= 0:
        chi2_low = float(chi2.ppf(alpha / 2.0, dof))
        chi2_high = float(chi2.ppf(1.0 - alpha / 2.0, dof))
        if chi2_low > 0 and chi2_high > 0:
            cp_interval = {
                'lower': float(cp * math.sqrt(chi2_low / dof)),
                'upper': float(cp * math.sqrt(chi2_high / dof)),
            }

    cpk_interval = None
    if isinstance(cpk, (int, float)) and math.isfinite(cpk):
        standard_error = math.sqrt((1.0 / (9.0 * n)) + ((cpk**2) / (2.0 * dof)))
        margin = z_value * standard_error
        cpk_interval = {
            'lower': float(cpk - margin),
            'upper': float(cpk + margin),
        }

    return {
        'cp': cp_interval,
        'cpk': cpk_interval,
    }
