"""Pure payload builders for group-analysis annotation rendering."""

import numpy as np


def build_violin_group_annotation_payload(values, positions, *, show_sigma, one_sided_sigma_mode):
    """Build deterministic per-group annotation payload rows for violin overlays."""

    payload = []
    for idx, group_values in enumerate(values):
        arr = np.asarray(group_values, dtype=float)
        if arr.size == 0:
            continue

        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
        sigma_low = mean_val - (3 * std_val)
        sigma_high = mean_val + (3 * std_val)

        payload.append(
            {
                'position': positions[idx],
                'minimum': float(np.min(arr)),
                'maximum': float(np.max(arr)),
                'mean': mean_val,
                'std': std_val,
                'sigma_low': sigma_low,
                'sigma_high': sigma_high,
                'sigma_start': mean_val if one_sided_sigma_mode else sigma_low,
                'show_sigma_segment': bool(show_sigma and std_val > 0),
            }
        )

    return payload
