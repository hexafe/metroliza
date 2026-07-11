from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUFF_C901_FINDING_BUDGET = 147


def test_production_complexity_does_not_exceed_reviewed_ratchet() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src/metroliza",
            "scripts",
            "packaging",
            "--select",
            "C901",
            "--output-format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode in {0, 1}, completed.stderr
    findings = json.loads(completed.stdout or "[]")
    assert len(findings) <= RUFF_C901_FINDING_BUDGET, (
        f"Production C901 findings increased to {len(findings)}; split new complex functions "
        "or lower the reviewed ratchet after refactoring."
    )
