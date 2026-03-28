"""Native bridge for distribution candidate metric kernels with fallback modes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

try:
    from _metroliza_distribution_fit_native import compute_candidate_metrics as _native_compute_candidate_metrics  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_compute_candidate_metrics = None

try:
    from _metroliza_distribution_fit_native import compute_candidate_metrics_batch as _native_compute_candidate_metrics_batch  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_compute_candidate_metrics_batch = None

try:
    from _metroliza_distribution_fit_native import compute_candidate_fit_params_batch as _native_compute_candidate_fit_params_batch  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_compute_candidate_fit_params_batch = None


KERNEL_MODE_PYTHON = 'python'
KERNEL_MODE_NATIVE = 'native'
KERNEL_MODE_AUTO = 'auto'


@dataclass(frozen=True)
class CandidateKernelInput:
    sample_values: np.ndarray
    distribution: str
    fitted_params: np.ndarray


@dataclass(frozen=True)
class CandidateKernelOutput:
    nll: float | None
    aic: float | None
    bic: float | None
    ad_statistic: float | None
    ks_statistic: float | None
    error_flags: int


@dataclass(frozen=True)
class CandidateBatchKernelInput:
    distributions: tuple[str, ...]
    fitted_params_batch: tuple[np.ndarray, ...]
    sample_values_batch: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class CandidateBatchKernelOutput:
    nll: tuple[float | None, ...]
    aic: tuple[float | None, ...]
    bic: tuple[float | None, ...]
    ad_statistic: tuple[float | None, ...]
    ks_statistic: tuple[float | None, ...]
    error_flags: tuple[int, ...]


@dataclass(frozen=True)
class CandidateBatchFitInput:
    distributions: tuple[str, ...]
    sample_values_batch: tuple[np.ndarray, ...]
    force_loc_zero_batch: tuple[bool, ...]


@dataclass(frozen=True)
class CandidateBatchFitOutput:
    fitted_params_batch: tuple[np.ndarray | None, ...]
    error_flags: tuple[int, ...]


ERROR_NONE = 0
ERROR_EMPTY_SAMPLE = 1 << 0
ERROR_NONFINITE_SAMPLE = 1 << 1
ERROR_UNSUPPORTED_DISTRIBUTION = 1 << 2
ERROR_INVALID_PARAMS = 1 << 3
ERROR_LOGPDF_FAILURE = 1 << 4
ERROR_AD_FAILURE = 1 << 5
ERROR_KS_FAILURE = 1 << 6
ERROR_FIT_FAILURE = 1 << 7


def native_backend_available() -> bool:
    return native_metrics_backend_available()


def native_metrics_backend_available() -> bool:
    return (
        _native_compute_candidate_metrics is not None
        and _native_compute_candidate_metrics_batch is not None
    )


def native_fit_backend_available() -> bool:
    return _native_compute_candidate_fit_params_batch is not None


def resolve_kernel_mode(explicit_mode: str | None = None) -> str:
    mode = (explicit_mode or os.getenv('METROLIZA_DISTRIBUTION_FIT_KERNEL') or KERNEL_MODE_AUTO).strip().lower()
    if mode not in {KERNEL_MODE_PYTHON, KERNEL_MODE_NATIVE, KERNEL_MODE_AUTO}:
        return KERNEL_MODE_PYTHON
    return mode


def _as_float64_1d_contiguous(values: Sequence[float] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError('Expected 1D numeric input')
    return np.ascontiguousarray(array)


def build_kernel_input(*, sample_values: Sequence[float] | np.ndarray, distribution: str, fitted_params: Sequence[float] | np.ndarray) -> CandidateKernelInput:
    return CandidateKernelInput(
        sample_values=_as_float64_1d_contiguous(sample_values),
        distribution=str(distribution),
        fitted_params=_as_float64_1d_contiguous(fitted_params),
    )


def build_batch_kernel_input(
    *,
    sample_values_batch: Sequence[Sequence[float] | np.ndarray],
    distributions: Sequence[str],
    fitted_params_batch: Sequence[Sequence[float] | np.ndarray],
) -> CandidateBatchKernelInput:
    if len(sample_values_batch) != len(distributions) or len(sample_values_batch) != len(fitted_params_batch):
        raise ValueError('Batch kernel inputs must have matching lengths')
    return CandidateBatchKernelInput(
        sample_values_batch=tuple(_as_float64_1d_contiguous(values) for values in sample_values_batch),
        distributions=tuple(str(distribution) for distribution in distributions),
        fitted_params_batch=tuple(_as_float64_1d_contiguous(values) for values in fitted_params_batch),
    )


def build_batch_fit_input(
    *,
    sample_values_batch: Sequence[Sequence[float] | np.ndarray],
    distributions: Sequence[str],
    force_loc_zero_batch: Sequence[bool],
) -> CandidateBatchFitInput:
    if len(sample_values_batch) != len(distributions) or len(sample_values_batch) != len(force_loc_zero_batch):
        raise ValueError('Batch fit inputs must have matching lengths')
    return CandidateBatchFitInput(
        sample_values_batch=tuple(_as_float64_1d_contiguous(values) for values in sample_values_batch),
        distributions=tuple(str(distribution) for distribution in distributions),
        force_loc_zero_batch=tuple(bool(flag) for flag in force_loc_zero_batch),
    )


def compute_candidate_metrics_native(kernel_input: CandidateKernelInput) -> CandidateKernelOutput | None:
    if _native_compute_candidate_metrics is None:
        return None

    nll, aic, bic, ad_stat, ks_stat, flags = _native_compute_candidate_metrics(
        kernel_input.distribution,
        kernel_input.fitted_params,
        kernel_input.sample_values,
    )
    return CandidateKernelOutput(
        nll=None if nll is None else float(nll),
        aic=None if aic is None else float(aic),
        bic=None if bic is None else float(bic),
        ad_statistic=None if ad_stat is None else float(ad_stat),
        ks_statistic=None if ks_stat is None else float(ks_stat),
        error_flags=int(flags),
    )


def compute_candidate_metrics(kernel_input: CandidateKernelInput, *, mode: str | None = None) -> CandidateKernelOutput | None:
    resolved_mode = resolve_kernel_mode(mode)
    if resolved_mode == KERNEL_MODE_PYTHON:
        return None

    native_result = compute_candidate_metrics_native(kernel_input)
    if native_result is None and resolved_mode == KERNEL_MODE_NATIVE:
        return CandidateKernelOutput(
            nll=None,
            aic=None,
            bic=None,
            ad_statistic=None,
            ks_statistic=None,
            error_flags=ERROR_UNSUPPORTED_DISTRIBUTION,
        )
    return native_result


def compute_candidate_metrics_batch_native(kernel_input: CandidateBatchKernelInput) -> CandidateBatchKernelOutput | None:
    if _native_compute_candidate_metrics_batch is None:
        return None
    nll, aic, bic, ad_stat, ks_stat, flags = _native_compute_candidate_metrics_batch(
        list(kernel_input.distributions),
        list(kernel_input.fitted_params_batch),
        list(kernel_input.sample_values_batch),
    )
    return CandidateBatchKernelOutput(
        nll=tuple(None if v is None else float(v) for v in nll),
        aic=tuple(None if v is None else float(v) for v in aic),
        bic=tuple(None if v is None else float(v) for v in bic),
        ad_statistic=tuple(None if v is None else float(v) for v in ad_stat),
        ks_statistic=tuple(None if v is None else float(v) for v in ks_stat),
        error_flags=tuple(int(v) for v in flags),
    )


def compute_candidate_fit_batch_native(kernel_input: CandidateBatchFitInput) -> CandidateBatchFitOutput | None:
    if _native_compute_candidate_fit_params_batch is None:
        return None
    fitted_params_batch, flags = _native_compute_candidate_fit_params_batch(
        list(kernel_input.distributions),
        list(kernel_input.sample_values_batch),
        list(kernel_input.force_loc_zero_batch),
    )
    return CandidateBatchFitOutput(
        fitted_params_batch=tuple(None if params is None else _as_float64_1d_contiguous(params) for params in fitted_params_batch),
        error_flags=tuple(int(v) for v in flags),
    )


def compute_candidate_fit_batch_fallback(
    kernel_input: CandidateBatchFitInput,
    *,
    fitters_by_distribution: dict[str, Callable],
) -> CandidateBatchFitOutput:
    fitted: list[np.ndarray | None] = []
    flags: list[int] = []
    for distribution, sample_values, force_loc_zero in zip(
        kernel_input.distributions,
        kernel_input.sample_values_batch,
        kernel_input.force_loc_zero_batch,
        strict=False,
    ):
        fitter = fitters_by_distribution.get(distribution)
        if fitter is None:
            fitted.append(None)
            flags.append(ERROR_UNSUPPORTED_DISTRIBUTION)
            continue
        try:
            fit_kwargs = {'floc': 0.0} if force_loc_zero else {}
            params = fitter(sample_values, **fit_kwargs)
            fitted.append(_as_float64_1d_contiguous(params))
            flags.append(ERROR_NONE)
        except Exception:
            fitted.append(None)
            flags.append(ERROR_FIT_FAILURE)
    return CandidateBatchFitOutput(
        fitted_params_batch=tuple(fitted),
        error_flags=tuple(flags),
    )


def compute_candidate_fit_batch(
    kernel_input: CandidateBatchFitInput,
    *,
    mode: str | None = None,
    fitters_by_distribution: dict[str, Callable] | None = None,
) -> CandidateBatchFitOutput | None:
    resolved_mode = resolve_kernel_mode(mode)
    if resolved_mode != KERNEL_MODE_PYTHON:
        native_output = compute_candidate_fit_batch_native(kernel_input)
        if native_output is not None:
            return native_output
        if resolved_mode == KERNEL_MODE_NATIVE:
            return CandidateBatchFitOutput(
                fitted_params_batch=tuple(None for _ in kernel_input.distributions),
                error_flags=tuple(ERROR_UNSUPPORTED_DISTRIBUTION for _ in kernel_input.distributions),
            )

    if fitters_by_distribution is None:
        return None
    return compute_candidate_fit_batch_fallback(
        kernel_input,
        fitters_by_distribution=fitters_by_distribution,
    )
