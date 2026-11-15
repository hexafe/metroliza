"""Private v2 context file; caller owns the activity worker and its store lock."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

from metroliza.shared import diagnostic_store
from metroliza.shared.safe_bugreport_context import (
    MAX_CONTEXT_BYTES, SafeBugReportContextSnapshot, context_payload,
    parse_context_payload, reject_duplicate_keys,
)

CONTEXT_FILE_NAME = "context.json"


def load_context_locked(root: Path) -> SafeBugReportContextSnapshot:
    path = root / CONTEXT_FILE_NAME
    if not path.exists():
        return SafeBugReportContextSnapshot(snapshot_state="missing")
    data = diagnostic_store._safe_file_bytes(path, MAX_CONTEXT_BYTES)
    payload = json.loads(data.decode("ascii"), object_pairs_hook=reject_duplicate_keys)
    if type(payload) is not dict or set(payload) != {"schema", "context"}:
        raise ValueError("invalid_context_history")
    if type(payload["schema"]) is not int or payload["schema"] != 2:
        raise ValueError("invalid_context_history")
    return parse_context_payload(payload["context"])


def save_context_locked(root: Path, snapshot: SafeBugReportContextSnapshot) -> bool:
    stage = None
    try:
        # Loading is a live worker state, never a durable claim about next launch.
        durable = replace(snapshot, snapshot_state="available")
        data = json.dumps({"schema": 2, "context": context_payload(durable)},
                          ensure_ascii=True, separators=(",", ":")).encode("ascii")
        if len(data) > MAX_CONTEXT_BYTES:
            return False
        path = root / CONTEXT_FILE_NAME
        if path.exists():
            diagnostic_store._safe_file_bytes(path, MAX_CONTEXT_BYTES)
        stage = diagnostic_store._write_stage(root, data)
        os.replace(stage, path)
        stage = None
        if os.name != "nt":
            descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return True
    except Exception:
        return False
    finally:
        if stage is not None:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass
