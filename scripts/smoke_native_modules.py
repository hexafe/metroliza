"""CI smoke checks for optional native extension bridges."""

from __future__ import annotations

import argparse
import importlib
import os

import numpy as np


def _reload(name: str):
    return importlib.reload(importlib.import_module(name))


def _assert_present_mode() -> None:
    cmm = _reload("modules.cmm_native_parser")
    group = _reload("modules.group_stats_native")
    comp = _reload("modules.comparison_stats_native")
    dist = _reload("modules.distribution_fit_native")

    assert cmm.native_backend_available(), "_metroliza_cmm_native must be available in present-mode smoke"
    assert group.native_backend_available(), "_metroliza_group_stats_native must be available in present-mode smoke"
    assert comp.native_backend_available(), "_metroliza_comparison_stats_native must be available in present-mode smoke"
    assert dist.native_backend_available(), "_metroliza_distribution_fit_native must be available in present-mode smoke"

    os.environ["METROLIZA_CMM_PARSER_BACKEND"] = "native"
    cmm = _reload("modules.cmm_native_parser")
    parsed = cmm.parse_blocks_with_backend([""], use_native=False)
    assert isinstance(parsed, list)

    coerced = group.coerce_sequence_to_float64([1, "2.5", "bad", None])
    assert isinstance(coerced, np.ndarray)
    assert coerced.shape == (4,)

    os.environ["METROLIZA_COMPARISON_STATS_CI_BACKEND"] = "native"
    os.environ["METROLIZA_COMPARISON_STATS_BACKEND"] = "native"
    comp = _reload("modules.comparison_stats_native")
    ci = comp.bootstrap_percentile_ci_native(
        effect_kernel="cohen_d",
        groups=[[1.0, 1.2, 0.8], [0.5, 0.4, 0.6]],
        level=0.95,
        iterations=64,
        seed=7,
    )
    assert ci is not None and len(ci) == 2
    rows = comp.pairwise_stats_native(
        labels=["A", "B"],
        groups=[[1.0, 1.2, 0.8], [0.5, 0.4, 0.6]],
        alpha=0.05,
        correction_method="holm",
        non_parametric=False,
        equal_var=True,
    )
    assert rows is not None and len(rows) == 1

    ad_ks = dist.compute_ad_ks_statistics_native(
        distribution="norm",
        fitted_params=[0.0, 1.0],
        sample_values=[-1.0, 0.0, 1.0],
    )
    assert ad_ks is not None and len(ad_ks) == 2
    p_est = dist.estimate_ad_pvalue_monte_carlo_native(
        distribution="norm",
        fitted_params=[0.0, 1.0],
        sample_size=8,
        observed_stat=0.3,
        iterations=8,
        seed=11,
    )
    assert p_est is not None and len(p_est) == 2


def _assert_absent_mode() -> None:
    cmm = _reload("modules.cmm_native_parser")
    group = _reload("modules.group_stats_native")
    comp = _reload("modules.comparison_stats_native")
    dist = _reload("modules.distribution_fit_native")

    assert not cmm.native_backend_available()
    assert not group.native_backend_available()
    assert not comp.native_backend_available()
    assert not dist.native_backend_available()

    os.environ["METROLIZA_CMM_PARSER_BACKEND"] = "auto"
    cmm = _reload("modules.cmm_native_parser")
    assert cmm.parse_blocks_with_backend([]) == []

    coerced = group.coerce_sequence_to_float64([1, "2.5", "bad", None])
    assert isinstance(coerced, np.ndarray)
    assert np.isnan(coerced[2]) and np.isnan(coerced[3])

    os.environ["METROLIZA_COMPARISON_STATS_CI_BACKEND"] = "auto"
    os.environ["METROLIZA_COMPARISON_STATS_BACKEND"] = "auto"
    comp = _reload("modules.comparison_stats_native")
    assert comp.bootstrap_percentile_ci_native(
        effect_kernel="cohen_d",
        groups=[[1.0, 1.2], [0.5, 0.6]],
        level=0.95,
        iterations=8,
        seed=3,
    ) is None
    assert comp.pairwise_stats_native(
        labels=["A", "B"],
        groups=[[1.0, 1.2], [0.5, 0.6]],
        alpha=0.05,
        correction_method="holm",
        non_parametric=False,
        equal_var=True,
    ) is None

    assert dist.compute_ad_ks_statistics_native(
        distribution="norm",
        fitted_params=[0.0, 1.0],
        sample_values=[-1.0, 0.0, 1.0],
    ) is None
    assert dist.estimate_ad_pvalue_monte_carlo_native(
        distribution="norm",
        fitted_params=[0.0, 1.0],
        sample_size=8,
        observed_stat=0.3,
        iterations=8,
        seed=11,
    ) is None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("present", "absent"), required=True)
    args = parser.parse_args()
    if args.mode == "present":
        _assert_present_mode()
        return
    _assert_absent_mode()


if __name__ == "__main__":
    main()
