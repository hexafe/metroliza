"""Strict allowlisted projection; central diagnostics owns transport and emission."""
from __future__ import annotations

from uuid import UUID

from .contracts import StepKind
from .ports import ResultCode, StepStatus
from .run_state import RunRecord, RunState


def _runtime_id(value: str) -> str:
    if type(value) is not str:
        raise ValueError("invalid_runtime_id")
    identity = UUID(value)
    if identity.version != 4 or str(identity) != value:
        raise ValueError("invalid_runtime_id")
    return value


def _integer(value: int, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid_runtime_count")
    return value


def _enum(value, kind):
    if not isinstance(value, kind):
        raise ValueError("invalid_runtime_code")
    return value.value


def safe_run_projection(record: RunRecord) -> dict:
    """No recipe identities, names, values, paths, or configuration fingerprints."""
    if type(record.steps) is not tuple or len(record.steps) > 32:
        raise ValueError("invalid_runtime_steps")
    if type(record.partial_import) is not bool:
        raise ValueError("invalid_runtime_flag")
    steps = []
    for step in record.steps:
        if type(step.result.warnings) is not tuple or len(step.result.warnings) > 32:
            raise ValueError("invalid_runtime_warnings")
        steps.append({"step_id": _runtime_id(step.step_id),
            "kind": _enum(step.kind, StepKind), "status": _enum(step.result.status, StepStatus),
            "code": _enum(step.result.code, ResultCode),
            "duration_ms": _integer(step.duration_ms, 86_400_000),
            "imported_count": _integer(step.result.imported_count, 10_000),
            "rejected_count": _integer(step.result.rejected_count, 10_000),
            "warnings": [_enum(w, ResultCode) for w in step.result.warnings]})
    return {"flow_id": _runtime_id(record.flow_id), "run_id": _runtime_id(record.run_id),
        "state": _enum(record.state, RunState), "code": _enum(record.code, ResultCode),
        "duration_ms": _integer(record.elapsed_ms, 86_400_000),
        "partial_import": record.partial_import, "steps": steps}


def safe_definition_projection(_definition: object, _binding: object = None) -> dict:
    """Constant: custom IDs and private configuration hashes are forbidden."""
    return {"format": "recipe", "projection_version": 1}
