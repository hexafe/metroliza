#!/usr/bin/env python3
"""Generate and verify deterministic Issue #976 Phase-A build-delivery evidence."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import ExitStack, contextmanager
import ctypes
from datetime import date
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only by the explicit non-POSIX gate
    fcntl = None  # type: ignore[assignment]


BASELINE_SHA = "bba2b9051822b43af951001e943d7c21141cc2a8"
BASELINE_TREE = "3430377cded559c1c2410ffcc571665403683014"
PR972_SHA = "678241e48bab6ae89c94cb559dfc9aeaf9280031"
PR972_TREE = "f916bd0cc70affd22894d9b944af52463f1f6408"
PR973_SHA = "b599c54c624490d1aa53457727975f33d6a47716"
PR973_TREE = "7cf4ae5653b9bd5d7802bb23e14ae1ae0a0488a3"
PR_INPUT_PARENT_SHA = "fcb462942e90aeeb64bba84bfe080d556da0efdb"
PR_INPUT_PARENT_TREE = "cbec0f82de989ef2bfaab36ce43f9ef84082bdf2"
BRANCH = "research/976-build-packaging-audit"
OWNER = 976
EXPECTED_RULE_COUNT = 12
EXPECTED_PATH_COUNT = 58
ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "docs/quality/bug_sweep/coverage.json"
EVIDENCE_PATH = ROOT / "docs/quality/bug_sweep/evidence/976-build-delivery.json"
REPORT_PATH = ROOT / "docs/quality/bug_sweep/waves/976-build-ci-packaging-windows.md"
AUTHORIZED_PHASE_A_PATHS = frozenset(
    {
        "docs/quality/bug_sweep/waves/976-build-ci-packaging-windows.md",
        "docs/quality/bug_sweep/evidence/976-build-delivery.json",
        "scripts/quality/audit_build_delivery.py",
        "tests/test_build_delivery_audit.py",
    }
)

RUNTIME_IDENTITY = {
    "requested_model": "GPT-5.6 Sol",
    "requested_reasoning": "Ultra",
    "runtime_model": "not visible",
    "runtime_reasoning": "not visible",
}
CLEAN_REVIEW_STATUS = (
    "clean independent Sol/Ultra-requested static review; actual runtime not visible"
)

CAPTURE_DATE = "2026-08-28"
# Exact local calendar date for execution of the current receipt-bound validation
# packet.  Historical repository/GitHub observations retain CAPTURE_DATE.
VALIDATION_GATE_DATE = "2026-08-29"
# Exact latest local calendar date authorized for this Phase-A review gate.  Keeping
# it distinct from CAPTURE_DATE prevents a later clean-slate review from being
# misrepresented as part of the historical evidence capture.
REVIEW_GATE_DATE = "2026-08-29"
# These are historical command/cwd strings captured on the original Linux host.
# Keep that evidence namespace stable across the current runtime's OS and TMPDIR.
CAPTURE_TEMP_ROOT = PurePosixPath("/", "tmp")
CAPTURE_PR973_PYTHON = CAPTURE_TEMP_ROOT / "metroliza-976-pr973-venv/bin/python"
CAPTURE_BASELINE_PYTHON = CAPTURE_TEMP_ROOT / "metroliza-976-baseline-venv/bin/python"
CAPTURE_PR973_CWD = CAPTURE_TEMP_ROOT / "metroliza-976-deps-pr973.b599c54"
CAPTURE_BASELINE_CWD = CAPTURE_TEMP_ROOT / "metroliza-976-deps-baseline.303568b"
CAPTURE_UV_CACHE = CAPTURE_TEMP_ROOT / "metroliza-976-uv-cache"
CAPTURE_MPL_CACHE = CAPTURE_TEMP_ROOT / "metroliza-976-mpl-cache"
CAPTURE_XDG_CACHE = CAPTURE_TEMP_ROOT / "metroliza-976-xdg-cache"
CAPTURE_CARGO_HOME = CAPTURE_TEMP_ROOT / "metroliza-976-cargo-home"
CAPTURE_CARGO_TARGET = CAPTURE_TEMP_ROOT / "metroliza-976-cargo-target"
CAPTURE_EXECUTOR_CWD = CAPTURE_TEMP_ROOT / "metroliza-976-audit.75hBI4/repo"
CAPTURE_AUDIT_CWD = CAPTURE_TEMP_ROOT / "metroliza-976-validation-checkout-v5"
CAPTURE_SECURITY_SIBLINGS = CAPTURE_TEMP_ROOT / "metroliza-975-security-siblings.14Hdba"
CAPTURE_SECURITY_MATERIALIZED = CAPTURE_TEMP_ROOT / "metroliza-976-security-materialized-v5"
CAPTURE_PARSER_SMOKE_ROOT = CAPTURE_TEMP_ROOT / "metroliza-976-parser-receipt-v5"
PARSER_EXPECTED_RESULTS_CONTENT = (
    "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
    "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
    "sample_report_01.csv,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,"
    "-0.1,,10.02,0.02,0\n"
).encode("utf-8")
PARSER_SAMPLE_REPORT_CONTENT = (
    "SUPPLIER TEMPLATE MARKER\n"
    "Reference: REF123\n"
    "Date: 2026-01-05\n"
    "Sample: 0001\n"
    "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0\n"
).encode("utf-8")
CAPTURE_VALIDATION_PYCACHE = CAPTURE_TEMP_ROOT / "metroliza-976-validation-pycache-v5"
CAPTURE_VALIDATION_RUFF_CACHE = CAPTURE_TEMP_ROOT / "metroliza-976-validation-ruff-cache-v5"
CAPTURE_VALIDATION_TEST_OUTPUT_ROOT = CAPTURE_TEMP_ROOT / "metroliza-976-validation-test-output-v1"
CAPTURE_VALIDATION_TEST_DB = CAPTURE_VALIDATION_TEST_OUTPUT_ROOT / "test.db"
CAPTURE_RUNTIME_SOURCE_BASE = (
    CAPTURE_TEMP_ROOT / "metroliza-976-python/cpython-3.11.16-linux-x86_64-gnu"
)
CAPTURE_RUNTIME_SOURCE_VENV = CAPTURE_TEMP_ROOT / "metroliza-976-baseline-venv"
CAPTURE_VALIDATION_RUNTIME = CAPTURE_TEMP_ROOT / "metroliza-976-validation-runtime-v1"
CAPTURE_VALIDATION_RUNTIME_BASE = CAPTURE_VALIDATION_RUNTIME / "base"
CAPTURE_VALIDATION_RUNTIME_VENV = CAPTURE_VALIDATION_RUNTIME / "venv"
CAPTURE_VALIDATION_PYTHON = CAPTURE_VALIDATION_RUNTIME_VENV / "bin/python"
VALIDATION_HEADLESS_PREFIX = (
    "env -u QT_QPA_PLATFORMTHEME PYTHONPATH=src:. "
    f"QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg {CAPTURE_BASELINE_PYTHON}"
)
VALIDATION_EXECUTION_ENV = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": str(CAPTURE_TEMP_ROOT / "metroliza-976-validation-home-v5"),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "MPLCONFIGDIR": str(CAPTURE_TEMP_ROOT / "metroliza-976-validation-mpl-v5"),
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "PYTHONPYCACHEPREFIX": str(CAPTURE_VALIDATION_PYCACHE),
    "RUFF_CACHE_DIR": str(CAPTURE_VALIDATION_RUFF_CACHE),
    "TMPDIR": str(CAPTURE_TEMP_ROOT),
    "TZ": "UTC",
    "VIRTUAL_ENV": str(CAPTURE_VALIDATION_RUNTIME_VENV),
    "XDG_CACHE_HOME": str(CAPTURE_TEMP_ROOT / "metroliza-976-validation-cache-v5"),
}
RUNTIME_EXECUTABLE_PTH_ALLOWLIST = {
    "venv/lib/python3.11/site-packages/_virtualenv.pth": (
        "69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d"
    ),
    "venv/lib/python3.11/site-packages/a1_coverage.pth": (
        "ef2ed06d19867ec669c09a804060666a9cd5e383af0a9d11aa2de79b77d448e8"
    ),
    "venv/lib/python3.11/site-packages/distutils-precedence.pth": (
        "2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224"
    ),
}
PINNED_VALIDATION_RUNTIME_CLOSURE = {
    "pyvenv_cfg_sha256": "dae512ae92fc30ba0714d0455e213c7daf35ca90189462507d57dbac1c775e64",
    "filesystem_manifest_sha256": "b847dbc203186b6756dcdc160ad1c222b454ce0d38c0edd8c11ad3959fed6285",
    "filesystem_entry_count": 31_755,
}
PINNED_VALIDATION_RUNTIME_INVENTORY_SHA256 = (
    "07dbf9cfa94b8106da683f342e6b7dfc48148bfcaca32fcb7891951960993e37"
)
PINNED_VALIDATION_RUNTIME_DISTRIBUTIONS: tuple[tuple[str, str], ...] = (
    ("altgraph", "0.17.5"),
    ("annotated-doc", "0.0.5"),
    ("annotated-types", "0.8.0"),
    ("antlr4-python3-runtime", "4.9.3"),
    ("anyio", "4.14.2"),
    ("ast_serialize", "0.8.0"),
    ("bandit", "1.9.4"),
    ("bashlex", "0.18"),
    ("boolean.py", "5.0"),
    ("bracex", "3.0.1"),
    ("build", "1.6.0"),
    ("CacheControl", "0.14.4"),
    ("certifi", "2026.7.22"),
    ("cffi", "2.1.1"),
    ("cfgv", "3.5.0"),
    ("charset-normalizer", "3.5.1"),
    ("cibuildwheel", "4.2.0"),
    ("click", "8.5.0"),
    ("colorlog", "6.12.0"),
    ("contourpy", "1.3.3"),
    ("coverage", "7.15.4"),
    ("cryptography", "50.0.1"),
    ("cycler", "0.12.1"),
    ("cyclonedx-python-lib", "11.12.0"),
    ("defusedxml", "0.7.1"),
    ("dependency-groups", "1.3.2"),
    ("distlib", "0.4.3"),
    ("et_xmlfile", "2.0.0"),
    ("fastapi", "0.141.1"),
    ("filelock", "3.32.4"),
    ("flatbuffers", "25.12.19"),
    ("fonttools", "4.63.0"),
    ("google-auth", "2.57.0"),
    ("google-auth-oauthlib", "1.4.1"),
    ("greenlet", "3.5.5"),
    ("h11", "0.16.0"),
    ("hexafe-groupstats", "0.1.0rc3"),
    ("hexafe-plotstats", "0.1.0a1"),
    ("humanize", "4.16.0"),
    ("identify", "2.6.19"),
    ("idna", "3.19"),
    ("iniconfig", "2.3.0"),
    ("joblib", "1.5.3"),
    ("kiwisolver", "1.5.0"),
    ("librt", "0.15.0"),
    ("license-expression", "30.4.4"),
    ("markdown-it-py", "4.2.0"),
    ("matplotlib", "3.11.1"),
    ("maturin", "1.15.0"),
    ("mdurl", "0.1.2"),
    ("msgpack", "1.2.2"),
    ("mypy", "2.2.0"),
    ("mypy_extensions", "1.1.0"),
    ("mysql-connector-python", "26.7.0"),
    ("narwhals", "2.25.0"),
    ("nodeenv", "1.10.0"),
    ("Nuitka", "4.2"),
    ("numpy", "2.4.6"),
    ("oauthlib", "3.3.1"),
    ("omegaconf", "2.3.1"),
    ("onnxruntime", "1.29.0"),
    ("opencv-python", "4.14.0.94"),
    ("openpyxl", "3.1.5"),
    ("openvino", "2026.3.1"),
    ("openvino-telemetry", "2025.2.0"),
    ("oznak", "0.2.0rc2"),
    ("packageurl-python", "0.17.6"),
    ("packaging", "26.3"),
    ("pandas", "3.0.5"),
    ("pathspec", "1.1.1"),
    ("pillow", "12.3.0"),
    ("pip", "26.2.1"),
    ("pip-api", "0.0.34"),
    ("pip-requirements-parser", "32.0.1"),
    ("pip_audit", "2.10.1"),
    ("platformdirs", "4.11.5"),
    ("pluggy", "1.6.0"),
    ("pre_commit", "4.6.2"),
    ("protobuf", "7.36.0"),
    ("py-serializable", "2.1.0"),
    ("pyasn1", "0.6.4"),
    ("pyasn1_modules", "0.4.2"),
    ("pyclipper", "1.4.0"),
    ("pycparser", "3.0"),
    ("pydantic", "2.13.4"),
    ("pydantic_core", "2.46.4"),
    ("Pygments", "2.21.0"),
    ("pyinstaller", "6.22.2"),
    ("pyinstaller-hooks-contrib", "2026.7"),
    ("pymupdf", "1.28.2"),
    ("PyMySQL", "1.2.0"),
    ("pyodbc", "5.3.0"),
    ("pyparsing", "3.3.2"),
    ("pyproject_hooks", "1.2.0"),
    ("PyQt6", "6.6.1"),
    ("PyQt6-Qt6", "6.6.1"),
    ("PyQt6_sip", "13.12.0"),
    ("pytest", "9.1.1"),
    ("pytest-cov", "7.1.0"),
    ("python-dateutil", "2.9.0.post0"),
    ("python-discovery", "1.5.3"),
    ("python-dotenv", "1.2.3"),
    ("PyYAML", "6.0.3"),
    ("rapidocr", "3.8.1"),
    ("requests", "2.34.2"),
    ("requests-oauthlib", "2.0.0"),
    ("rich", "15.0.0"),
    ("river", "0.26.1"),
    ("ruff", "0.15.10"),
    ("scikit-learn", "1.9.0"),
    ("scipy", "1.17.1"),
    ("seaborn", "0.13.2"),
    ("setuptools", "84.0.0"),
    ("shapely", "2.1.2"),
    ("shellingham", "1.5.4"),
    ("six", "1.17.0"),
    ("sortedcontainers", "2.4.0"),
    ("SQLAlchemy", "2.0.52"),
    ("starlette", "1.6.0"),
    ("stevedore", "5.9.1"),
    ("threadpoolctl", "3.6.0"),
    ("tomli", "2.4.1"),
    ("tomli_w", "1.2.0"),
    ("tqdm", "4.70.0"),
    ("typer", "0.27.1"),
    ("typing-inspection", "0.4.4"),
    ("typing_extensions", "4.16.0"),
    ("urllib3", "2.7.0"),
    ("uvicorn", "0.52.4"),
    ("virtualenv", "21.7.5"),
    ("wheel", "0.48.0"),
    ("xlrd", "2.0.2"),
    ("xlsxwriter", "3.2.9"),
    ("zstandard", "0.25.0"),
)
BOUND_EXECUTABLES: tuple[dict[str, Any], ...] = (
    {
        "argv_path": "/usr/bin/git",
        "resolved_path": "/usr/bin/git",
        "content_sha256": "93473c28694fd72bd889364107cd2770514de59780885a6a4aafca4d602e30ad",
        "size_bytes": 4_899_632,
        "file_type": "regular",
        "mode": "0755",
        "execution_binding": "held descriptor supplied as subprocess executable",
    },
    {
        "argv_path": str(CAPTURE_VALIDATION_PYTHON),
        "resolved_path": str(CAPTURE_VALIDATION_RUNTIME_BASE / "bin/python3.11"),
        "content_sha256": "2874a0b9344d06b7767aebb1e6e25a759ffcbdb544e99400ecc74dc6092d1174",
        "size_bytes": 21_740_000,
        "file_type": "regular",
        "mode": "0555",
        "execution_binding": "held descriptor supplied as subprocess executable",
    },
)

BASELINE_SUBJECT_REF = f"hexafe/metroliza develop@{BASELINE_SHA} tree={BASELINE_TREE}"
PR973_SUBJECT_REF = f"hexafe/metroliza PR #973 head@{PR973_SHA} tree={PR973_TREE}"
SECURITY_SIBLING_SUBJECTS: tuple[dict[str, str], ...] = (
    {
        "repository": "hexafe/hexafe-groupstats",
        "directory": "hexafe-groupstats",
        "commit": "14cc60e7412fa2647a8906f3f8833d0d789fc552",
        "tree": "fa1dddfccd39e2d68159612c74f1eeab3bd72566",
        "worktree_status": "clean; empty porcelain including untracked files",
    },
    {
        "repository": "hexafe/hexafe-plotstats",
        "directory": "hexafe-plotstats",
        "commit": "1e2c72107d342f44a37e5fb78d7d76992ea60315",
        "tree": "97c1110ab6e95ec2681cbb70b4eaea01c9a453b5",
        "worktree_status": "clean; empty porcelain including untracked files",
    },
    {
        "repository": "hexafe/oznak",
        "directory": "oznak",
        "commit": "ed51580dfdec9f91f6320c7937af6d65dd5a1290",
        "tree": "60bf39a0d2e31661080dcf0f8c25b6f25dfaf9db",
        "worktree_status": "clean; empty porcelain including untracked files",
    },
)
SECURITY_SIBLING_PREFLIGHT_COMMANDS = tuple(
    command
    for row in SECURITY_SIBLING_SUBJECTS
    for command in (
        f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} rev-parse HEAD",
        f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} rev-parse HEAD^{{tree}}",
        f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} status --porcelain=v1 --untracked-files=all",
    )
)
SECURITY_SIBLING_PREFLIGHT_EXPECTED_STDOUT = {
    command: expected
    for row in SECURITY_SIBLING_SUBJECTS
    for command, expected in (
        (
            f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} rev-parse HEAD",
            f"{row['commit']}\n".encode("ascii"),
        ),
        (
            f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} rev-parse HEAD^{{tree}}",
            f"{row['tree']}\n".encode("ascii"),
        ),
        (
            f"git -C {CAPTURE_SECURITY_MATERIALIZED / row['directory']} status --porcelain=v1 --untracked-files=all",
            b"",
        ),
    )
}

ROUTING: tuple[dict[str, str], ...] = (
    {
        "agent_id": "HD-976-BUILD",
        "role": "coordinator / integration / validation / parking",
        "lane": "Build / CI / Dependencies / Packaging / Windows",
        "mode": "LOCAL-FIRST / ACTIONS-CI-DEFERRED / PARKED",
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    },
    {
        "agent_id": "HD-976-BUILD/W1-CI-MAP",
        "role": "read-only evidence worker",
        "lane": "CI workflow / history / Actions inputs",
        "mode": "READ-ONLY / ACTIONS-CI-DEFERRED",
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    },
    {
        "agent_id": "HD-976-BUILD/W2-PACKAGING",
        "role": "read-only evidence worker",
        "lane": "Packaging / Windows / resources",
        "mode": "READ-ONLY / ACTIONS-CI-DEFERRED",
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    },
    {
        "agent_id": "HD-976-BUILD/W3-DEPS",
        "role": "read-only evidence worker",
        "lane": "Dependencies / toolchains / PR inputs",
        "mode": "READ-ONLY / ACTIONS-CI-DEFERRED",
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    },
    {
        "agent_id": "HD-976-BUILD/R1-INDEPENDENT",
        "role": "independent adversarial reviewer",
        "lane": "four-file Phase-A diff",
        "mode": "READ-ONLY / INDEPENDENT REVIEW",
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    },
)

CAPTURED_ENVIRONMENT = {
    "capture_platform": "Linux x86_64",
    "isolated_resolution_python": "CPython 3.11.16",
    "repository_python_contract": "CPython 3.11 minor; patch version floats",
    "host_python": "CPython 3.14.7",
    "git": "2.55.0",
    "rustc": "1.98.0",
    "cargo": "1.98.0",
    "powershell": "unavailable on Linux host",
    "baseline_ruff": "0.15.10",
    "baseline_mypy": "2.2.0",
    "baseline_pytest": "9.1.1",
    "pip": "26.2.1",
    "uv": "0.12.5",
    "windows_runtime": "not executed",
    "packaged_runtime": "not executed",
}

WORKFLOW_ROWS: tuple[dict[str, Any], ...] = (
    {
        "job": "static-checks",
        "name": "Static checks",
        "trigger": "pull_request, push(any branch), workflow_dispatch",
        "runner": "ubuntu-latest",
        "timeout_minutes": 30,
        "needs": [],
        "if": "success()",
        "blocking": "automatic blocking",
        "commands": [
            "compileall",
            "parser import smoke",
            "Ruff full repository",
            "narrow strict mypy",
            "release metadata sync check",
            "secret scan",
            "release hygiene",
            "pinned sibling repository verification",
            "security audit",
        ],
        "artifacts": [],
        "cache_dependency_paths": [
            "requirements.txt",
            "requirements-ocr.txt",
            "requirements-build.txt",
            "requirements-dev.txt",
        ],
        "continue_on_error": False,
        "evidence_availability": "automated; existing exact-base run inspected read-only",
        "false_boundary": (
            "A failure short-circuits later steps; no static diagnostic bundle is uploaded. "
            "Floating pip and lower-bound requirements make resolution time-dependent."
        ),
    },
    {
        "job": "unit-tests",
        "name": "Unit tests",
        "trigger": "pull_request, push(any branch), workflow_dispatch",
        "runner": "ubuntu-latest",
        "timeout_minutes": 45,
        "needs": [],
        "if": "success()",
        "blocking": "automatic blocking",
        "commands": [
            "full pytest plus nine isolated append shards",
            "combined coverage threshold",
            "canonical-package coverage threshold >=80",
        ],
        "artifacts": ["coverage-report on success only"],
        "cache_dependency_paths": ["requirements.txt", "requirements-dev.txt"],
        "continue_on_error": False,
        "evidence_availability": "automated; exact-base existing run failed with no artifact",
        "false_boundary": (
            "Coverage summary and upload are skipped after an earlier test failure; downstream "
            "needs jobs then skip without workflow evidence for their own compatibility."
        ),
    },
    {
        "job": "native-artifacts",
        "name": "Native wheel build and smoke checks",
        "trigger": "pull_request, push(any branch), workflow_dispatch",
        "runner": "ubuntu-latest",
        "timeout_minutes": 60,
        "needs": [],
        "if": "success()",
        "blocking": "automatic blocking",
        "commands": [
            "Rust 1.95.0 setup",
            "five maturin --locked wheels",
            "wheel install/import",
            "native fallback and parity tests",
        ],
        "artifacts": [],
        "cache_dependency_paths": ["requirements.txt", "requirements-build.txt"],
        "continue_on_error": False,
        "evidence_availability": "automated Linux wheel evidence; Windows/package unavailable",
        "false_boundary": "Linux wheels do not establish Windows wheel or packaged-extension behavior.",
    },
    {
        "job": "cmm-parser-perf-gate",
        "name": "CMM parser perf guardrail",
        "trigger": "automatic after static-checks and unit-tests",
        "runner": "ubuntu-latest",
        "timeout_minutes": 45,
        "needs": ["static-checks", "unit-tests"],
        "if": "success()",
        "blocking": "automatic blocking after successful needs",
        "commands": ["native CMM wheel", "three measured parser runs", "threshold comparison"],
        "artifacts": ["cmm-parser-perf-artifacts; missing files warn"],
        "cache_dependency_paths": ["requirements-build.txt", "requirements-ocr.txt"],
        "continue_on_error": False,
        "evidence_availability": "automated but skipped after failed needs at exact base",
        "false_boundary": (
            "Skipped, not failed, when either upstream job fails. The enforced benchmark also "
            "returns zero when native_backend_available is false; #993 owns that false-green."
        ),
    },
    {
        "job": "perf-benchmarks",
        "name": "Performance benchmark trend check (non-blocking)",
        "trigger": "automatic after static-checks and unit-tests",
        "runner": "ubuntu-latest",
        "timeout_minutes": 45,
        "needs": ["static-checks", "unit-tests"],
        "if": "success()",
        "blocking": "automatic advisory; job-level continue-on-error",
        "commands": ["benchmark suite", "trend comparison (continue-on-error)"],
        "artifacts": ["performance artifacts; upload always; missing files warn"],
        "cache_dependency_paths": ["requirements-dev.txt"],
        "continue_on_error": True,
        "evidence_availability": "automated advisory; skipped after failed needs at exact base",
        "false_boundary": "Job-level continue-on-error makes regressions advisory; upstream failures skip it.",
    },
    {
        "job": "packaging-smoke",
        "name": "Packaging smoke (manual/opt-in)",
        "trigger": "workflow_dispatch with run_packaging_smoke=1 only",
        "runner": "ubuntu-latest",
        "timeout_minutes": 90,
        "needs": ["static-checks", "unit-tests", "native-artifacts"],
        "if": "manual input and upstream success",
        "blocking": "not selected on PR/push; blocking when dispatch input selects it",
        "commands": ["PyInstaller onefile", "artifact and notice checks", "packaged PDF smoke"],
        "artifacts": ["packaged artifact on success", "failure diagnostics on failure"],
        "cache_dependency_paths": ["requirements-build.txt", "requirements-ocr.txt"],
        "continue_on_error": False,
        "evidence_availability": "manual/opt-in; no enabled hosted run found",
        "false_boundary": "Absent from normal PR/push evidence and Linux-only when selected.",
    },
    {
        "job": "windows-core-smoke",
        "name": "Windows core smoke",
        "trigger": "pull_request, push(any branch), workflow_dispatch",
        "runner": "windows-latest",
        "timeout_minutes": 30,
        "needs": [],
        "if": "success()",
        "blocking": "automatic blocking",
        "commands": ["selected Windows core and path tests"],
        "artifacts": [],
        "cache_dependency_paths": ["requirements.txt", "requirements-dev.txt"],
        "continue_on_error": False,
        "evidence_availability": "automated source/helper smoke only",
        "false_boundary": "Source tests are not executable packaging, Qt plugin, OCR model or clean-machine evidence.",
    },
    {
        "job": "windows-startup-benchmark",
        "name": "Windows startup benchmark (manual/opt-in)",
        "trigger": "workflow_dispatch with run_windows_startup_benchmark=1 only",
        "runner": "windows-latest",
        "timeout_minutes": 120,
        "needs": ["static-checks", "unit-tests"],
        "if": "manual input and upstream success",
        "blocking": "not selected on PR/push; blocking when dispatch input selects it",
        "commands": ["build both PyInstaller modes", "measure packaged startup"],
        "artifacts": ["startup benchmark artifacts; upload always; missing files warn"],
        "cache_dependency_paths": ["requirements-build.txt", "requirements-ocr.txt"],
        "continue_on_error": False,
        "evidence_availability": "manual/opt-in; no enabled hosted run found",
        "false_boundary": "Absent from normal PR/push evidence and skipped after upstream failure.",
    },
)

PR972_MATRIX: tuple[dict[str, str], ...] = (
    {
        "action": "actions/checkout",
        "from": "5.0.1",
        "to": "7.0.1",
        "sha": "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "decision": "safe candidate; does not repair fetch-depth=1; retest exact head",
        "notes": "Node 24 and runner >=2.327.1; current workflow uses no elevated event or token persistence.",
    },
    {
        "action": "actions/setup-python",
        "from": "6.3.0",
        "to": "7.0.0",
        "sha": "5fda3b95a4ea91299a34e894583c3862153e4b97",
        "decision": "safe candidate; retest exact head",
        "notes": "Node 24; workflow's python-version and pip-cache inputs remain supported.",
    },
    {
        "action": "actions/upload-artifact",
        "from": "6.0.0",
        "to": "7.0.1",
        "sha": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "decision": "safe candidate; retest success/failure artifact semantics",
        "notes": "Node 24; direct uploads and configured missing-file behavior remain compatible.",
    },
)

PR973_DECLARATION_EDITS: tuple[dict[str, str], ...] = (
    {
        "family": "ML/realtime",
        "path": "requirements-anomaly.txt",
        "name": "scikit-learn",
        "old": "scikit-learn>=1.4,<2",
        "new": "scikit-learn>=1.9.0,<2",
    },
    {
        "family": "ML/realtime",
        "path": "requirements-anomaly.txt",
        "name": "river",
        "old": "river>=0.22,<1",
        "new": "river>=0.26.1,<1",
    },
    {
        "family": "packaging",
        "path": "requirements-build.txt",
        "name": "Nuitka",
        "old": "Nuitka>=1.9",
        "new": "Nuitka>=4.1.3",
    },
    {
        "family": "packaging",
        "path": "requirements-build.txt",
        "name": "pyinstaller",
        "old": "pyinstaller>=6.11",
        "new": "pyinstaller>=6.22.2",
    },
    {
        "family": "packaging",
        "path": "requirements-build.txt",
        "name": "pyinstaller-hooks-contrib",
        "old": "pyinstaller-hooks-contrib>=2025.0",
        "new": "pyinstaller-hooks-contrib>=2026.6",
    },
    {
        "family": "packaging",
        "path": "requirements-build.txt",
        "name": "zstandard",
        "old": "zstandard>=0.22.0",
        "new": "zstandard>=0.25.0",
    },
    {
        "family": "Rust/native wheel",
        "path": "requirements-build.txt",
        "name": "maturin",
        "old": "maturin>=1.13.3",
        "new": "maturin>=1.14.1",
    },
    {
        "family": "Rust/native wheel",
        "path": "requirements-build.txt",
        "name": "cibuildwheel",
        "old": "cibuildwheel>=2.19",
        "new": "cibuildwheel>=4.2.0",
    },
    {
        "family": "Rust/native wheel",
        "path": "requirements-build.txt",
        "name": "build",
        "old": "build>=1.2",
        "new": "build>=1.5.0",
    },
    {
        "family": "Rust/native wheel",
        "path": "requirements-build.txt",
        "name": "packaging",
        "old": "packaging>=24.0",
        "new": "packaging>=26.3",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-build.txt",
        "name": "pytest",
        "old": "pytest>=8.0",
        "new": "pytest>=9.1.1",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "pytest",
        "old": "pytest>=8.0.0",
        "new": "pytest>=9.1.1",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "pytest-cov",
        "old": "pytest-cov>=5.0.0",
        "new": "pytest-cov>=7.1.0",
    },
    {
        "family": "scientific/data",
        "path": "requirements-dev.txt",
        "name": "pandas",
        "old": "pandas>=2.0.1",
        "new": "pandas>=3.0.5",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "ruff",
        "old": "ruff==0.15.10",
        "new": "ruff==0.16.4",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "mypy",
        "old": "mypy==2.2.0",
        "new": "mypy==2.3.1",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "pip-audit",
        "old": "pip-audit>=2.10.0",
        "new": "pip-audit>=2.10.1",
    },
    {
        "family": "test/lint/type/security",
        "path": "requirements-dev.txt",
        "name": "pre-commit",
        "old": "pre-commit>=3.7.0",
        "new": "pre-commit>=4.6.2",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements-ocr.txt",
        "name": "rapidocr",
        "old": "rapidocr==3.8.1",
        "new": "rapidocr==3.9.2",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements-ocr.txt",
        "name": "onnxruntime",
        "old": "onnxruntime>=1.21,<2",
        "new": "onnxruntime>=1.29.0,<2",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements-ocr.txt",
        "name": "openvino",
        "old": "openvino>=2026.1,<2027",
        "new": "openvino>=2026.3.0,<2027",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements-ocr.txt",
        "name": "opencv-python",
        "old": "opencv-python>=4.12,<5",
        "new": "opencv-python>=5.0.0.93,<6",
    },
    {
        "family": "security/auth",
        "path": "requirements.txt",
        "name": "cryptography",
        "old": "cryptography>=46.0.7",
        "new": "cryptography>=50.0.0",
    },
    {
        "family": "security/auth",
        "path": "requirements.txt",
        "name": "google-auth-oauthlib",
        "old": "google-auth-oauthlib>=1.2.0",
        "new": "google-auth-oauthlib>=1.4.0",
    },
    {
        "family": "scientific/data",
        "path": "requirements.txt",
        "name": "matplotlib",
        "old": "matplotlib>=3.8.1",
        "new": "matplotlib>=3.11.1",
    },
    {
        "family": "scientific/data",
        "path": "requirements.txt",
        "name": "numpy",
        "old": "numpy>=1.24.3",
        "new": "numpy>=2.4.6",
    },
    {
        "family": "workbook/report",
        "path": "requirements.txt",
        "name": "openpyxl",
        "old": "openpyxl>=3.1.2",
        "new": "openpyxl>=3.1.5",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements.txt",
        "name": "Pillow",
        "old": "Pillow>=12.2.0",
        "new": "Pillow>=12.3.0",
    },
    {
        "family": "PDF/OCR/image",
        "path": "requirements.txt",
        "name": "PyMuPDF",
        "old": "PyMuPDF>=1.27.2.3",
        "new": "PyMuPDF>=1.28.2",
    },
    {
        "family": "Qt",
        "path": "requirements.txt",
        "name": "PyQt6",
        "old": "PyQt6==6.6.1",
        "new": "PyQt6==6.11.0",
    },
    {
        "family": "Qt",
        "path": "requirements.txt",
        "name": "PyQt6-Qt6",
        "old": "PyQt6-Qt6==6.6.1",
        "new": "PyQt6-Qt6==6.11.1",
    },
    {
        "family": "security/auth",
        "path": "requirements.txt",
        "name": "PyYAML",
        "old": "PyYAML>=6.0.1",
        "new": "PyYAML>=6.0.3",
    },
    {
        "family": "scientific/data",
        "path": "requirements.txt",
        "name": "scipy",
        "old": "scipy>=1.10.1",
        "new": "scipy>=1.17.1",
    },
    {
        "family": "scientific/data",
        "path": "requirements.txt",
        "name": "seaborn",
        "old": "seaborn>=0.13.0",
        "new": "seaborn>=0.13.2",
    },
    {
        "family": "workbook/report",
        "path": "requirements.txt",
        "name": "XlsxWriter",
        "old": "XlsxWriter>=3.1.0",
        "new": "XlsxWriter>=3.2.9",
    },
    {
        "family": "workbook/report",
        "path": "requirements.txt",
        "name": "xlrd",
        "old": "xlrd>=2.0.1",
        "new": "xlrd>=2.0.2",
    },
)

PR973_TEST_PREFIX = (
    "env -u QT_QPA_PLATFORMTHEME PYTHONDONTWRITEBYTECODE=1 "
    "QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg "
    f"MPLCONFIGDIR={CAPTURE_MPL_CACHE} "
    f"XDG_CACHE_HOME={CAPTURE_XDG_CACHE} "
    f"{CAPTURE_PR973_PYTHON}"
)
PR973_PROPOSAL_CWD = str(CAPTURE_PR973_CWD)


def _pr973_pytest(*paths: str) -> str:
    return f"{PR973_TEST_PREFIX} -m pytest -q -p no:cacheprovider " + " ".join(paths)


def _pr973_command(argv: str, *, exit_code: int, result: str) -> dict[str, Any]:
    return {
        "argv": argv,
        "cwd": PR973_PROPOSAL_CWD,
        "exit_code": exit_code,
        "result": result,
    }


PR973_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "family": "security/auth",
        "names": ["cryptography", "google-auth-oauthlib", "PyYAML"],
        "python_311": "supported; resolved Requires-Python floors are >=3.9, >=3.10 and >=3.8",
        "linux_artifacts": "cryptography cp311-abi3 manylinux; google auth pure py3; PyYAML cp311 manylinux",
        "windows_evidence": "opaque solver capture observed inclusion in a 66-row CPython 3.11 wheel-only result; raw rows/digest are not independently auditable and execution is unavailable",
        "api_risks": "cryptography declared-floor major change; auth/token and OpenSSL/backend behavior",
        "conflicts": "no family conflict; broad security-policy test fails only on Pillow from another family",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_google_drive_credentials_hygiene.py",
                    "tests/test_google_drive_export.py",
                ),
                exit_code=0,
                result="51 passed, 3 subtests",
            )
        ],
        "downstream_waves": "credential hygiene, OAuth/Drive export, security-audit input generation",
        "decision": "split/retest",
        "owner": "#913 and #983",
    },
    {
        "family": "scientific/data",
        "names": ["matplotlib", "numpy", "scipy", "seaborn", "pandas"],
        "python_311": "supported; exact floor for matplotlib, NumPy, SciPy and pandas; seaborn >=3.8",
        "linux_artifacts": "compiled cp311 manylinux wheels except pure-Python seaborn",
        "windows_evidence": "opaque solver capture observed inclusion in a 66-row CPython 3.11 wheel-only result; raw rows/digest are not independently auditable and execution is unavailable",
        "api_risks": "NumPy 2/pandas 3 ABI, dtype and serialization; SciPy/matplotlib plotting and numeric behavior",
        "conflicts": "none detected; fresh highest-version baseline already resolves all proposed floors",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_matplotlib_runtime.py",
                    "tests/test_matplotlib_distribution_geometry.py",
                    "tests/test_matplotlib_iqr_trend_geometry.py",
                    "tests/test_distribution_shape_analysis.py",
                ),
                exit_code=0,
                result="19 passed",
            )
        ],
        "downstream_waves": "chart rendering, statistics/distributions, industrial analytics, workbook/dashboard exports",
        "decision": "split/retest",
        "owner": "#913, #980 and #982",
    },
    {
        "family": "Qt",
        "names": ["PyQt6", "PyQt6-Qt6"],
        "python_311": "supported; proposal PyQt6 requires >=3.10; Qt payload publishes no Requires-Python",
        "linux_artifacts": "wrapper cp310-abi3 manylinux_2_34 and payload manylinux_2_34 raise the baseline glibc floor",
        "windows_evidence": "opaque solver capture observed compatible artifacts; raw rows/digest and DLL/plugin/startup/package execution are unavailable",
        "api_risks": "enums/signals, wrapper/payload alignment, plugin discovery and packaged Qt DLL paths",
        "conflicts": "requirements-hygiene still requires both 6.6.1 exact pins",
        "commands": [
            _pr973_command(
                "env -u QT_QPA_PLATFORMTHEME PYTHONDONTWRITEBYTECODE=1 "
                f"QT_QPA_PLATFORM=offscreen {CAPTURE_PR973_PYTHON} "
                "scripts/validate_qt_runtime.py",
                exit_code=0,
                result="PyQt6 6.11.0 / Qt payload 6.11.1; alignment/import pass",
            ),
            _pr973_command(
                _pr973_pytest(
                    "tests/test_qt_runtime_validation.py",
                    "tests/test_pyqt_ui_geometry_audit.py",
                ),
                exit_code=0,
                result="8 passed",
            ),
        ],
        "downstream_waves": "GUI/dialog/startup, Qt plugins, both packagers and Windows startup",
        "decision": "split/retest; blocked from release acceptance",
        "owner": "#901, #913 and #920",
    },
    {
        "family": "PDF/OCR/image",
        "names": ["Pillow", "PyMuPDF", "rapidocr", "onnxruntime", "openvino", "opencv-python"],
        "python_311": "supported; ONNX Runtime requires >=3.11 and the remaining resolved distributions accept 3.11",
        "linux_artifacts": "Pillow/PyMuPDF/ONNX/OpenVINO/OpenCV platform wheels; RapidOCR pure Python",
        "windows_evidence": "opaque 78-row runtime+OCR solver capture selected omegaconf 2.0.6 rather than 2.3.1; raw rows/digest are not independently auditable and execution is unavailable",
        "api_risks": "OpenCV major, RapidOCR result model, NumPy ABI, provider/model and packaged DLL discovery",
        "conflicts": "security policy still expects Pillow>=12.2.0",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_packaged_pdf_parser_validation.py",
                    "tests/test_pdf_parser_smoke.py",
                    "tests/test_header_ocr_backend.py",
                    "tests/test_pymupdf_backend_resolution.py",
                ),
                exit_code=0,
                result="37 passed",
            ),
            _pr973_command(
                "env -u QT_QPA_PLATFORMTHEME PYTHONDONTWRITEBYTECODE=1 "
                f"QT_QPA_PLATFORM=offscreen {CAPTURE_PR973_PYTHON} "
                "scripts/validate_packaged_pdf_parser.py --require-header-ocr",
                exit_code=0,
                result="header OCR dependencies and three vendored models validated",
            ),
        ],
        "downstream_waves": "PDF parser/header OCR, model loading, image preprocessing and packaged providers/DLLs",
        "decision": "split/retest; OpenCV major and packaged Windows runtime blocked",
        "owner": "#901, #913 and #978",
    },
    {
        "family": "workbook/report",
        "names": ["openpyxl", "XlsxWriter", "xlrd"],
        "python_311": "supported; all three captured distributions accept Python 3.11",
        "linux_artifacts": "pure Python wheels",
        "windows_evidence": "opaque solver capture observed inclusion in the runtime wheel-only result; raw rows/digest and execution are unavailable",
        "api_risks": "formula/type serialization, charts, formatting and legacy XLS reading",
        "conflicts": "none detected; no resolved-version delta",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_export_workbook_output.py",
                    "tests/test_export_sheet_writer.py",
                    "tests/test_xlsx_chart_utils.py",
                ),
                exit_code=0,
                result="12 passed",
            )
        ],
        "downstream_waves": "XLSX generation, charts/summaries and legacy XLS intake",
        "decision": "split/retest",
        "owner": "#913 and #981",
    },
    {
        "family": "ML/realtime",
        "names": ["scikit-learn", "river"],
        "python_311": "supported and exact minimum for both resolved distributions",
        "linux_artifacts": "compiled cp311 manylinux wheels",
        "windows_evidence": "opaque 7-row wheel-only anomaly solver capture was observed; raw rows/digest and execution are unavailable",
        "api_risks": "estimator/serialization compatibility, numeric ABI, drift-detector and online-learning behavior",
        "conflicts": "none detected; no resolved-version delta",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_anomaly_isolation_forest.py",
                    "tests/test_anomaly_online_drift.py",
                    "tests/test_realtime_detector_consumer.py",
                    "tests/test_realtime_end_to_end_replay.py",
                ),
                exit_code=0,
                result="30 passed",
            )
        ],
        "downstream_waves": "anomaly registry, isolation forest, online drift and realtime replay/consumer",
        "decision": "split/retest",
        "owner": "#913 and #982",
    },
    {
        "family": "Rust/native wheel",
        "names": ["maturin", "cibuildwheel", "build", "packaging"],
        "python_311": "supported; captured floors >=3.7, >=3.11, >=3.10 and >=3.9",
        "linux_artifacts": "maturin manylinux/musllinux; remaining tools pure Python",
        "windows_evidence": "opaque build-family solver capture was observed for CPython 3.11; raw rows/digest and MSVC build/install execution are unavailable",
        "api_risks": "floating local Rust, PyO3 0.21 Python ceiling, wheel tags and MSVC linkage",
        "conflicts": "host Python 3.14 failed PyO3; explicit Python 3.11 passed",
        "commands": [
            {
                "argv": (
                    f"PYO3_PYTHON={CAPTURE_PR973_PYTHON} "
                    f"CARGO_HOME={CAPTURE_CARGO_HOME} "
                    f"CARGO_TARGET_DIR={CAPTURE_CARGO_TARGET / crate} "
                    f"cargo {subcommand} --locked --offline "
                    + ("--format-version 1 " if subcommand == "metadata" else "")
                    + f"--manifest-path src/metroliza/native/{crate}/Cargo.toml"
                ),
                "cwd": PR973_PROPOSAL_CWD,
                "crate": crate,
                "exit_code": 0,
                "result": (
                    "metadata passed"
                    if subcommand == "metadata"
                    else (
                        "passed; two Rust unit tests"
                        if crate == "comparison_stats_bootstrap"
                        else "passed; zero Rust unit tests"
                    )
                ),
            }
            for crate in (
                "chart_renderer",
                "cmm_parser",
                "comparison_stats_bootstrap",
                "distribution_fit_ad",
                "group_stats_coercion",
            )
            for subcommand in ("metadata", "test")
        ],
        "downstream_waves": "five native wheels, native parsers/statistics/charts, fallback/parity and packaging",
        "decision": "split/retest",
        "owner": "#913 and #980",
    },
    {
        "family": "packaging",
        "names": ["Nuitka", "pyinstaller", "pyinstaller-hooks-contrib", "zstandard"],
        "python_311": "supported in capture; Nuitka metadata omits Requires-Python, others accept 3.11",
        "linux_artifacts": "Nuitka locally built cp311-linux; PyInstaller manylinux; hooks pure; zstandard cp311 manylinux",
        "windows_evidence": "opaque build solver capture required --no-binary nuitka; raw rows/digest, compiler execution and packaged execution are unavailable",
        "api_risks": "hook/data discovery, onefile/standalone layout, Qt/OCR/native DLL collection and compiler selection",
        "conflicts": "no resolved-version delta; exact Windows artifact execution unavailable",
        "commands": [
            _pr973_command(
                _pr973_pytest(
                    "tests/test_build_native_and_package_helper.py",
                    "tests/test_packaging_spec_hiddenimports.py",
                    "tests/test_build_provenance.py",
                    "tests/test_stage_release_notices.py",
                ),
                exit_code=0,
                result="23 passed",
            )
        ],
        "downstream_waves": "both packagers, notices/provenance, artifact freshness/naming and Windows toolchains",
        "decision": "split/retest; blocked from release acceptance",
        "owner": "#901, #913, #920 and #992",
    },
    {
        "family": "test/lint/type/security",
        "names": ["pytest", "pytest-cov", "ruff", "mypy", "pip-audit", "pre-commit"],
        "python_311": "supported by all captured tool distributions",
        "linux_artifacts": "Ruff/mypy platform wheels; remaining tools pure Python",
        "windows_evidence": "opaque 103-row dev wheel-only solver capture was observed; raw rows/digest and execution are unavailable",
        "api_risks": "lint defaults, type diagnostics/plugins, pytest/plugins, pre-commit sync and audit output",
        "conflicts": "Ruff/pre-commit pin, mypy policy pin, Qt hygiene and Pillow policy drift",
        "commands": [
            _pr973_command(
                f"{CAPTURE_PR973_PYTHON} -m ruff check . --statistics",
                exit_code=1,
                result="1,671 findings; 916 fixable",
            ),
            _pr973_command(
                f"{CAPTURE_PR973_PYTHON} -m mypy "
                "src/metroliza/integrations/google_credentials_hygiene.py "
                "src/metroliza/industrial/anomaly/contracts.py "
                "src/metroliza/industrial/realtime/stream_contracts.py",
                exit_code=0,
                result="no issues in three files",
            ),
            _pr973_command(
                f"{CAPTURE_PR973_PYTHON} -m pytest -q "
                "-p no:cacheprovider tests/test_ci_policy_sync.py "
                "tests/test_requirements_hygiene.py tests/test_security_audit.py",
                exit_code=1,
                result="4 failed, 46 passed",
            ),
        ],
        "downstream_waves": "static/pre-commit/type/unit/coverage gates and downstream skip propagation",
        "decision": "blocked; isolate Ruff remediation",
        "owner": "#913, #914 and #996",
    },
)

PR973_RESOLUTION_ROWS: tuple[dict[str, Any], ...] = tuple(
    json.loads(
        r"""[
  {
    "family": "security/auth",
    "name": "cryptography",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "cryptography",
      "requires_python": ">=3.9, !=3.9.0, !=3.9.1",
      "resolved_version": "50.0.1",
      "wheel_tags": [
        "cp311-abi3-manylinux_2_34_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "cryptography",
      "requires_python": ">=3.9, !=3.9.0, !=3.9.1",
      "resolved_version": "50.0.1",
      "wheel_tags": [
        "cp311-abi3-manylinux_2_34_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "security/auth",
    "name": "google-auth-oauthlib",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "google-auth-oauthlib",
      "requires_python": ">=3.10",
      "resolved_version": "1.4.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "google-auth-oauthlib",
      "requires_python": ">=3.10",
      "resolved_version": "1.4.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "security/auth",
    "name": "PyYAML",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyYAML",
      "requires_python": ">=3.8",
      "resolved_version": "6.0.3",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyYAML",
      "requires_python": ">=3.8",
      "resolved_version": "6.0.3",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "scientific/data",
    "name": "matplotlib",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "matplotlib",
      "requires_python": ">=3.11",
      "resolved_version": "3.11.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "matplotlib",
      "requires_python": ">=3.11",
      "resolved_version": "3.11.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "scientific/data",
    "name": "numpy",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "numpy",
      "requires_python": ">=3.11",
      "resolved_version": "2.4.6",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "numpy",
      "requires_python": ">=3.11",
      "resolved_version": "2.4.6",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "scientific/data",
    "name": "scipy",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "scipy",
      "requires_python": ">=3.11",
      "resolved_version": "1.17.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "scipy",
      "requires_python": ">=3.11",
      "resolved_version": "1.17.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "scientific/data",
    "name": "seaborn",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "seaborn",
      "requires_python": ">=3.8",
      "resolved_version": "0.13.2",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "seaborn",
      "requires_python": ">=3.8",
      "resolved_version": "0.13.2",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "scientific/data",
    "name": "pandas",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pandas",
      "requires_python": ">=3.11",
      "resolved_version": "3.0.5",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_24_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pandas",
      "requires_python": ">=3.11",
      "resolved_version": "3.0.5",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_24_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Qt",
    "name": "PyQt6",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyQt6",
      "requires_python": ">=3.6.1",
      "resolved_version": "6.6.1",
      "wheel_tags": [
        "cp38-abi3-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyQt6",
      "requires_python": ">=3.10",
      "resolved_version": "6.11.0",
      "wheel_tags": [
        "cp310-abi3-manylinux_2_34_x86_64"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Qt",
    "name": "PyQt6-Qt6",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyQt6-Qt6",
      "requires_python": null,
      "resolved_version": "6.6.1",
      "wheel_tags": [
        "py3-none-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyQt6-Qt6",
      "requires_python": null,
      "resolved_version": "6.11.1",
      "wheel_tags": [
        "py3-none-manylinux_2_34_x86_64"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "Pillow",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "Pillow",
      "requires_python": ">=3.10",
      "resolved_version": "12.3.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "Pillow",
      "requires_python": ">=3.10",
      "resolved_version": "12.3.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "PyMuPDF",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyMuPDF",
      "requires_python": ">=3.10",
      "resolved_version": "1.28.2",
      "wheel_tags": [
        "cp310-abi3-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "PyMuPDF",
      "requires_python": ">=3.10",
      "resolved_version": "1.28.2",
      "wheel_tags": [
        "cp310-abi3-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "rapidocr",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "rapidocr",
      "requires_python": ">=3.6,<4",
      "resolved_version": "3.8.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "rapidocr",
      "requires_python": "<4,>=3.8",
      "resolved_version": "3.9.2",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "onnxruntime",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "onnxruntime",
      "requires_python": ">=3.11",
      "resolved_version": "1.29.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "onnxruntime",
      "requires_python": ">=3.11",
      "resolved_version": "1.29.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "openvino",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "openvino",
      "requires_python": ">=3.10",
      "resolved_version": "2026.3.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "openvino",
      "requires_python": ">=3.10",
      "resolved_version": "2026.3.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "PDF/OCR/image",
    "name": "opencv-python",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "opencv-python",
      "requires_python": ">=3.6",
      "resolved_version": "4.14.0.94",
      "wheel_tags": [
        "cp37-abi3-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "opencv-python",
      "requires_python": ">=3.6",
      "resolved_version": "5.0.0.93",
      "wheel_tags": [
        "cp37-abi3-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "workbook/report",
    "name": "openpyxl",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "openpyxl",
      "requires_python": ">=3.8",
      "resolved_version": "3.1.5",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "openpyxl",
      "requires_python": ">=3.8",
      "resolved_version": "3.1.5",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "workbook/report",
    "name": "XlsxWriter",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "XlsxWriter",
      "requires_python": ">=3.8",
      "resolved_version": "3.2.9",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "XlsxWriter",
      "requires_python": ">=3.8",
      "resolved_version": "3.2.9",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "workbook/report",
    "name": "xlrd",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "xlrd",
      "requires_python": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*",
      "resolved_version": "2.0.2",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "xlrd",
      "requires_python": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*",
      "resolved_version": "2.0.2",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "ML/realtime",
    "name": "scikit-learn",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "scikit-learn",
      "requires_python": ">=3.11",
      "resolved_version": "1.9.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "scikit-learn",
      "requires_python": ">=3.11",
      "resolved_version": "1.9.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_27_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "ML/realtime",
    "name": "river",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "river",
      "requires_python": ">=3.11",
      "resolved_version": "0.26.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "river",
      "requires_python": ">=3.11",
      "resolved_version": "0.26.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Rust/native wheel",
    "name": "maturin",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "maturin",
      "requires_python": ">=3.7",
      "resolved_version": "1.15.0",
      "wheel_tags": [
        "py3-none-manylinux_2_12_x86_64",
        "py3-none-manylinux2010_x86_64",
        "py3-none-musllinux_1_1_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "maturin",
      "requires_python": ">=3.7",
      "resolved_version": "1.15.0",
      "wheel_tags": [
        "py3-none-manylinux_2_12_x86_64",
        "py3-none-manylinux2010_x86_64",
        "py3-none-musllinux_1_1_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Rust/native wheel",
    "name": "cibuildwheel",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "cibuildwheel",
      "requires_python": ">=3.11",
      "resolved_version": "4.2.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "cibuildwheel",
      "requires_python": ">=3.11",
      "resolved_version": "4.2.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Rust/native wheel",
    "name": "build",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "build",
      "requires_python": ">= 3.10",
      "resolved_version": "1.6.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "build",
      "requires_python": ">= 3.10",
      "resolved_version": "1.6.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "Rust/native wheel",
    "name": "packaging",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "packaging",
      "requires_python": ">=3.9",
      "resolved_version": "26.3",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "packaging",
      "requires_python": ">=3.9",
      "resolved_version": "26.3",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "packaging",
    "name": "Nuitka",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "Nuitka",
      "requires_python": null,
      "resolved_version": "4.2",
      "wheel_tags": [
        "cp311-cp311-linux_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "Nuitka",
      "requires_python": null,
      "resolved_version": "4.2",
      "wheel_tags": [
        "cp311-cp311-linux_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "packaging",
    "name": "pyinstaller",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pyinstaller",
      "requires_python": "<3.16,>=3.8",
      "resolved_version": "6.22.2",
      "wheel_tags": [
        "py3-none-manylinux2014_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pyinstaller",
      "requires_python": "<3.16,>=3.8",
      "resolved_version": "6.22.2",
      "wheel_tags": [
        "py3-none-manylinux2014_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "packaging",
    "name": "pyinstaller-hooks-contrib",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pyinstaller-hooks-contrib",
      "requires_python": ">=3.8",
      "resolved_version": "2026.7",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pyinstaller-hooks-contrib",
      "requires_python": ">=3.8",
      "resolved_version": "2026.7",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "packaging",
    "name": "zstandard",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "zstandard",
      "requires_python": ">=3.9",
      "resolved_version": "0.25.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "zstandard",
      "requires_python": ">=3.9",
      "resolved_version": "0.25.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "pytest",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pytest",
      "requires_python": ">=3.10",
      "resolved_version": "9.1.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pytest",
      "requires_python": ">=3.10",
      "resolved_version": "9.1.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "pytest-cov",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pytest-cov",
      "requires_python": ">=3.9",
      "resolved_version": "7.1.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pytest-cov",
      "requires_python": ">=3.9",
      "resolved_version": "7.1.0",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "ruff",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "ruff",
      "requires_python": ">=3.7",
      "resolved_version": "0.15.10",
      "wheel_tags": [
        "py3-none-manylinux_2_17_x86_64",
        "py3-none-manylinux2014_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "ruff",
      "requires_python": ">=3.7",
      "resolved_version": "0.16.4",
      "wheel_tags": [
        "py3-none-manylinux_2_17_x86_64",
        "py3-none-manylinux2014_x86_64"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "mypy",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "mypy",
      "requires_python": ">=3.10",
      "resolved_version": "2.2.0",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "mypy",
      "requires_python": ">=3.10",
      "resolved_version": "2.3.1",
      "wheel_tags": [
        "cp311-cp311-manylinux_2_17_x86_64",
        "cp311-cp311-manylinux2014_x86_64",
        "cp311-cp311-manylinux_2_28_x86_64"
      ]
    },
    "resolved_changed": true,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "pip-audit",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pip-audit",
      "requires_python": ">=3.10",
      "resolved_version": "2.10.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pip-audit",
      "requires_python": ">=3.10",
      "resolved_version": "2.10.1",
      "wheel_tags": [
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  },
  {
    "family": "test/lint/type/security",
    "name": "pre-commit",
    "baseline": {
      "direct_url": null,
      "installer": "uv",
      "name": "pre-commit",
      "requires_python": ">=3.10",
      "resolved_version": "4.6.2",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "proposal": {
      "direct_url": null,
      "installer": "uv",
      "name": "pre-commit",
      "requires_python": ">=3.10",
      "resolved_version": "4.6.2",
      "wheel_tags": [
        "py2-none-any",
        "py3-none-any"
      ]
    },
    "resolved_changed": false,
    "capture_platform": "Linux x86_64 / CPython 3.11.16",
    "source_provenance": "INSTALLER=uv; no direct_url.json; exact package index unavailable",
    "artifact_sha256": null,
    "artifact_provenance_boundary": "installed WHEEL tags retained; wheel filename, URL, size, signature and artifact hash not retained"
  }
]"""
    )
)

PR973_RESOLUTION_CAPTURE = {
    "opaque_baseline_capture_sha256": "8da6d680270840d30ac2144fecf327b68d8772de3cb62bd08d6984acb9bcc7c4",
    "opaque_proposal_capture_sha256": "30808ba950948e3f00b52e1cd1f4ab5a78fdbb1c6843509b10daa33fe1f7feea",
    "opaque_capture_raw_stream_retained": False,
    "opaque_capture_digest_verified": False,
    "row_count": 35,
    "schema": "requested_name, resolved_version, INSTALLER, direct_url, Requires-Python, WHEEL tags",
    "pip_check": "observational pass in both isolated environments; exact argv and raw output were not retained",
    "pip_check_observations": [
        {
            "subject_ref": BASELINE_SUBJECT_REF,
            "argv": "not retained; isolated baseline CPython 3.11 environment invoked pip check",
            "cwd": "temporary exact-baseline checkout; exact path not retained",
            "exit_code": 0,
            "result": "observational pass",
            "exact_argv_retained": False,
            "raw_output_retained": False,
        },
        {
            "subject_ref": PR973_SUBJECT_REF,
            "argv": f"not retained; {CAPTURE_PR973_PYTHON} invoked pip check",
            "cwd": PR973_PROPOSAL_CWD,
            "exit_code": 0,
            "result": "observational pass",
            "exact_argv_retained": False,
            "raw_output_retained": False,
        },
    ],
    "capture_date": CAPTURE_DATE,
}


def _direct_resolution_capture() -> dict[str, Any]:
    algorithm = (
        "UTF-8 JSON array plus LF; rows retain declaration order; keys sorted; compact "
        "separators; fields=requested_name,resolved_version,installer,direct_url,"
        "requires_python,wheel_tags"
    )

    def normalized(side: str) -> list[dict[str, Any]]:
        return [
            {
                "requested_name": row["name"],
                "resolved_version": row[side]["resolved_version"],
                "installer": row[side]["installer"],
                "direct_url": row[side]["direct_url"],
                "requires_python": row[side]["requires_python"],
                "wheel_tags": row[side]["wheel_tags"],
            }
            for row in PR973_RESOLUTION_ROWS
        ]

    result = dict(PR973_RESOLUTION_CAPTURE)
    result["retained_row_normalization"] = algorithm
    for side in ("baseline", "proposal"):
        rows = normalized(side)
        if len(rows) != result["row_count"]:
            raise AuditError(f"PR #973 retained {side} resolution row count drifted")
        payload = (
            json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        result[f"{side}_retained_rows_sha256"] = hashlib.sha256(payload).hexdigest()
        result[f"{side}_retained_rows"] = rows
    return result


PR973_WINDOWS_RESOLUTIONS: tuple[dict[str, Any], ...] = (
    {
        "input": "proposal requirements.txt",
        "input_paths": ["requirements.txt"],
        "observed_rows": 66,
        "opaque_capture_sha256": "eb4cf091ece0a5a7055295afb5b0de3c323052c53e1518b214a6b52ba34c21a1",
        "binary_policy": "--only-binary :all:",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-header --no-annotate requirements.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
    {
        "input": "proposal runtime + OCR",
        "input_paths": ["requirements.txt", "requirements-ocr.txt"],
        "observed_rows": 78,
        "opaque_capture_sha256": "0511d4ce0854fd5aa61cfa764f7ccbbc2a71de7cbfdae75ac4ddca8af9bcc7d8",
        "binary_policy": "--only-binary :all:",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-header --no-annotate requirements.txt requirements-ocr.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
    {
        "input": "proposal anomaly",
        "input_paths": ["requirements-anomaly.txt"],
        "observed_rows": 7,
        "opaque_capture_sha256": "5cb688e7746968a21318fb3cd98a5f9887a23017a53776b80ab0d5fd6465f885",
        "binary_policy": "--only-binary :all:",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-header --no-annotate requirements-anomaly.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
    {
        "input": "proposal dev",
        "input_paths": ["requirements-dev.txt"],
        "observed_rows": 103,
        "opaque_capture_sha256": "52bed4236dd7590c5055e8a4ecd6db8a61286580bf202e16a787be036b3066d8",
        "binary_policy": "--only-binary :all:",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-header --no-annotate requirements-dev.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
    {
        "input": "proposal build",
        "input_paths": ["requirements-build.txt"],
        "observed_rows": 88,
        "opaque_capture_sha256": None,
        "malformed_opaque_capture_commitment": "2366e33fc3a0fa802c8754b8f3ed54adb1e85ea3f4b62397ed723eb7515d8d1",
        "binary_policy": "--only-binary :all: --no-binary nuitka",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-binary nuitka --no-header --no-annotate requirements-build.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
    {
        "input": "full baseline five inputs",
        "input_paths": [
            "requirements.txt",
            "requirements-anomaly.txt",
            "requirements-build.txt",
            "requirements-dev.txt",
            "requirements-ocr.txt",
        ],
        "observed_rows": 137,
        "opaque_capture_sha256": "16fb7a1161cccc9f617d7526e3c0cfcea28022d619ca31f227e6b1a941b7218f",
        "binary_policy": "ordinary compile policy; not wheel-only evidence",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --no-header --no-annotate requirements.txt requirements-anomaly.txt requirements-build.txt requirements-dev.txt requirements-ocr.txt",
        "cwd": f"{CAPTURE_BASELINE_CWD} (five manifests byte-identical to authorized bba2b905 baseline)",
    },
    {
        "input": "full proposal five inputs",
        "input_paths": [
            "requirements.txt",
            "requirements-anomaly.txt",
            "requirements-build.txt",
            "requirements-dev.txt",
            "requirements-ocr.txt",
        ],
        "observed_rows": 137,
        "opaque_capture_sha256": "14fb1a887ee8e43e40d1a9b1bde7bff6e320a17f5c9f5d0566773a00e9598cb5",
        "binary_policy": "ordinary compile policy; not wheel-only evidence",
        "argv": f"UV_CACHE_DIR={CAPTURE_UV_CACHE} uv pip compile --offline --python-version 3.11 --python-platform x86_64-pc-windows-msvc --no-header --no-annotate requirements.txt requirements-anomaly.txt requirements-build.txt requirements-dev.txt requirements-ocr.txt",
        "cwd": str(CAPTURE_PR973_CWD),
    },
)


def _windows_resolution_inventory() -> list[dict[str, Any]]:
    return [
        {
            **row,
            "opaque_capture_digest_well_formed": bool(
                re.fullmatch(r"[0-9a-f]{64}", row.get("opaque_capture_sha256") or "")
            ),
            "normalized_stream_retained": False,
            "row_count_recomputed": False,
            "digest_recomputed": False,
            "evidence_boundary": (
                (
                    "observed count only; the retained opaque digest commitment is malformed "
                    "and therefore unavailable as SHA-256 evidence; "
                    if row.get("opaque_capture_sha256") is None
                    else "observed count and opaque digest commitment only; "
                )
                + "normalized resolver text/package rows and cache artifacts were not retained"
            ),
        }
        for row in PR973_WINDOWS_RESOLUTIONS
    ]


FINDINGS: tuple[dict[str, str], ...] = (
    {
        "id": "HD-976-F001",
        "severity": "P1",
        "taxonomy": "CI / release-evidence / audit-control",
        "disposition": "confirmed defect; open",
        "summary": "Depth-1 CI checkout lacks historical commits required by schema-v4 terminal snapshots.",
        "issue": "https://github.com/hexafe/metroliza/issues/991",
    },
    {
        "id": "HD-976-F002",
        "severity": "P1",
        "taxonomy": "packaging / output-atomicity / release-evidence",
        "disposition": "confirmed defect; open",
        "summary": "Nuitka standalone validates a onefile-style root path and can accept stale output.",
        "issue": "https://github.com/hexafe/metroliza/issues/992",
    },
    {
        "id": "HD-976-F003",
        "severity": "P1",
        "taxonomy": "dependency-platform / reproducibility",
        "disposition": "confirmed gap; authoritative existing owner",
        "summary": "Lower-bound Python manifests have no lock; 29 of 35 unique #973 proposals are current resolution no-ops.",
        "issue": "https://github.com/hexafe/metroliza/issues/913",
    },
    {
        "id": "HD-976-F004",
        "severity": "P2",
        "taxonomy": "windows-packaging / toolchain",
        "disposition": "confirmed configuration conflict; authoritative existing owner",
        "summary": "Windows setup defaults to 3.12, ignores that selector when py is absent, and the build path accepts generic py -3/python while repository/CI policy selects 3.11.",
        "issue": "https://github.com/hexafe/metroliza/issues/913",
    },
    {
        "id": "HD-976-F005",
        "severity": "P2",
        "taxonomy": "CI / observability / skip propagation",
        "disposition": "confirmed evidence gap; authoritative existing owner",
        "summary": "Unit failure skips coverage upload and required downstream compatibility evidence.",
        "issue": "https://github.com/hexafe/metroliza/issues/914",
    },
    {
        "id": "HD-976-F006",
        "severity": "P2",
        "taxonomy": "CI / native-parity / release-evidence",
        "disposition": "confirmed false-green; open",
        "summary": "Enforced CMM performance guardrail exits zero when the native backend is unavailable.",
        "issue": "https://github.com/hexafe/metroliza/issues/993",
    },
    {
        "id": "HD-976-F007",
        "severity": "P2",
        "taxonomy": "CI / Rust test coverage",
        "disposition": "confirmed test gap; authoritative existing owner",
        "summary": "CI builds five locked native wheels but runs no Cargo fmt, clippy or Rust unit tests.",
        "issue": "https://github.com/hexafe/metroliza/issues/914",
    },
    {
        "id": "HD-976-F008",
        "severity": "P1",
        "taxonomy": "packaging / licensing / release-evidence",
        "disposition": "confirmed missing notice input; open",
        "summary": "Vendored Plotly JavaScript names a companion license file that is absent from both packagers.",
        "issue": "https://github.com/hexafe/metroliza/issues/994",
    },
    {
        "id": "HD-976-F009",
        "severity": "P1",
        "taxonomy": "CI / dependency-platform / static-analysis",
        "disposition": "confirmed required-gate failure; open",
        "summary": "Ruff 0.16.4 enables new defaults and produces 1,671 findings on exact PR #973 head.",
        "issue": "https://github.com/hexafe/metroliza/issues/996",
    },
    {
        "id": "HD-976-F010",
        "severity": "P1",
        "taxonomy": "windows-packaging / supply-chain / toolchain",
        "disposition": "confirmed preventative control gap; open",
        "summary": "Opt-in VC redistributable installer executes mutable redirected content without signer/digest verification.",
        "issue": "https://github.com/hexafe/metroliza/issues/997",
    },
    {
        "id": "HD-976-F011",
        "severity": "P1",
        "taxonomy": "packaging / licensing / release-identity",
        "disposition": "confirmed freshness-control defect; open",
        "summary": "Packagers accept a fixed build-numbered third-party inventory without binding it to current release, source or dependency inputs.",
        "issue": "https://github.com/hexafe/metroliza/issues/999",
    },
    {
        "id": "HD-976-F012",
        "severity": "P3",
        "taxonomy": "CI / cache invalidation / reproducibility",
        "disposition": "confirmed cache-efficiency risk; authoritative existing owner",
        "summary": "Several cache keys omit transitively included runtime manifests and can restore stale download caches.",
        "issue": "https://github.com/hexafe/metroliza/issues/914",
    },
    {
        "id": "HD-976-F013",
        "severity": "P1",
        "taxonomy": "CI / process-crash / industrial-analytics / observability",
        "disposition": "confirmed hosted-run crash; root-cause hypothesis open",
        "summary": "Exact-base combined coverage received SIGSEGV in the industrial analytics dialog shard.",
        "issue": "https://github.com/hexafe/metroliza/issues/998",
    },
    {
        "id": "HD-976-F014",
        "severity": "P1",
        "taxonomy": "windows-runtime / diagnostics / false-green",
        "disposition": "confirmed control-flow defect; open",
        "summary": "Windows OCR diagnostics serialize required smoke failures but return zero, so checked runtime setup can report completion.",
        "issue": "https://github.com/hexafe/metroliza/issues/1000",
    },
    {
        "id": "HD-976-F015",
        "severity": "P1",
        "taxonomy": "packaging / provenance / release-identity",
        "disposition": "confirmed freshness-control defect; open",
        "summary": "PyInstaller accepts a structurally valid same-release provenance manifest without binding Git identity or build-attempt freshness.",
        "issue": "https://github.com/hexafe/metroliza/issues/1001",
    },
    {
        "id": "HD-976-F016",
        "severity": "P1",
        "taxonomy": "windows-runtime / diagnostics / confidentiality",
        "disposition": "confirmed disclosure-control defect; open",
        "summary": "Windows OCR diagnostics can emit local paths, environment/process details, raw subprocess output, document metadata/text and database rows without a sanitized-default boundary.",
        "issue": "https://github.com/hexafe/metroliza/issues/1002",
    },
    {
        "id": "HD-976-F017",
        "severity": "P2",
        "taxonomy": "packaging / resource-fetch / cleanup",
        "disposition": "confirmed interruption-cleanup defect; open",
        "summary": "RapidOCR model fetch exceptions can leave partial temporary files outside the completed hash-mismatch cleanup path.",
        "issue": "https://github.com/hexafe/metroliza/issues/1003",
    },
    {
        "id": "HD-976-F018",
        "severity": "P2",
        "taxonomy": "build-validation / parser-cli / control-flow",
        "disposition": "confirmed argument-contract defect; open",
        "summary": "Parser self-service validate/install/repair --sample crashes because argparse append uses a tuple default.",
        "issue": "https://github.com/hexafe/metroliza/issues/1004",
    },
)

DURABLE_ISSUE_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "issue": 901,
        "role": "clean Windows artifact acceptance residual owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/901#issuecomment-5451933231",
        "status": "public comment URL reference posted; mutable remote body is not content-addressed",
    },
    {
        "issue": 913,
        "role": "dependency/toolchain reproducibility and Windows Python owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/913#issuecomment-5451933357",
        "status": "public comment URL reference posted; mutable remote body is not content-addressed",
    },
    {
        "issue": 914,
        "role": "CI observability/Rust/cache owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/914#issuecomment-5451933268",
        "status": "public comment URL reference posted; mutable remote body is not content-addressed",
    },
    {
        "issue": 920,
        "role": "release/artifact policy residual owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/920",
        "status": "authoritative Issue link only; a new comment was not authorized by the remote-mutation gate",
    },
    {
        "issue": 955,
        "role": "packaged offline-help residual owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/955",
        "status": "authoritative Issue link only; a new comment was not authorized by the remote-mutation gate",
    },
    {
        "issue": 984,
        "role": "installed/frozen parser-profile discovery residual owner",
        "evidence_url": "https://github.com/hexafe/metroliza/issues/984#issuecomment-5451933616",
        "status": "public comment URL reference posted; mutable remote body is not content-addressed",
    },
    *(
        {
            "issue": issue,
            "role": role,
            "evidence_url": f"https://github.com/hexafe/metroliza/issues/{issue}",
            "status": "focused Phase-A Issue created; mutable public URL reference, not immutable body evidence",
        }
        for issue, role in (
            (991, "history object availability"),
            (992, "Nuitka artifact freshness"),
            (993, "native CMM guardrail false-green"),
            (994, "Plotly companion notice"),
            (996, "Ruff 0.16 migration gate"),
            (997, "VC redistributable provenance"),
            (998, "exact-base coverage shard SIGSEGV"),
            (999, "third-party inventory freshness"),
            (1000, "Windows OCR diagnostic false-green"),
            (1001, "PyInstaller provenance freshness"),
            (1002, "Windows OCR diagnostic confidentiality"),
            (1003, "RapidOCR model fetch interruption cleanup"),
            (1004, "parser self-service explicit-sample CLI crash"),
        )
    ),
)

RESIDUAL_RISKS: tuple[dict[str, str], ...] = (
    {
        "id": "HD-976-R001",
        "severity": "P1",
        "taxonomy": "windows-packaging / compatibility / release-evidence",
        "classification": "deferred residual risk",
        "reason": "No clean-machine Windows packaged executable, Qt plugin, OCR model or native DLL run was available in Phase A.",
        "accountable_owner": "Windows release owner",
        "target_issue_or_phase": "#901 / release acceptance",
        "next_gate": "Exact-SHA clean Windows artifact build/start/core-flow evidence.",
        "preserved_seam": "Windows build scripts and package configuration remain unchanged.",
    },
    {
        "id": "HD-976-R002",
        "severity": "P2",
        "taxonomy": "release-policy / platform / reproducibility",
        "classification": "deferred residual risk",
        "reason": "Supported platform/toolchain and immutable artifact policy remain undecided.",
        "accountable_owner": "Release policy owner",
        "target_issue_or_phase": "#920 / release-policy gate",
        "next_gate": "Release ADR and reproducible artifact validation.",
        "preserved_seam": "No release metadata or artifact was changed or published.",
    },
    {
        "id": "HD-976-R003",
        "severity": "P2",
        "taxonomy": "packaging / documentation / offline-availability",
        "classification": "deferred residual risk",
        "reason": "Packaged manuals remain online-path oriented rather than proven offline resources.",
        "accountable_owner": "Documentation and release owner",
        "target_issue_or_phase": "#955 / packaged-help acceptance",
        "next_gate": "Packaged offline help/manual acceptance evidence.",
        "preserved_seam": "Existing help behavior and documentation remain unchanged.",
    },
    {
        "id": "HD-976-R004",
        "severity": "P2",
        "taxonomy": "packaging / provenance / artifact-identity",
        "classification": "deferred residual risk",
        "reason": "Nuitka lacks PyInstaller's embedded manifest and sidecar binding; the manual Linux PyInstaller CI path embeds the manifest but does not stage an artifact-hash sidecar. Missing/malformed embedded provenance also degrades a frozen runtime to source/unknown identity.",
        "accountable_owner": "Packaging and release owner",
        "target_issue_or_phase": "#920 / reproducible-artifact gate",
        "next_gate": "Define and verify onefile/standalone provenance binding against the current build attempt, including fail-closed or explicit invalid-frozen behavior for missing/corrupt manifests.",
        "preserved_seam": "Nuitka configuration and artifact metadata remain unchanged in this audit.",
    },
    {
        "id": "HD-976-R005",
        "severity": "P2",
        "taxonomy": "packaging / resource-discovery / parser-profile",
        "classification": "deferred residual risk",
        "reason": "Source-path checks do not establish installed-wheel or frozen parser-profile/resource discovery.",
        "accountable_owner": "Packaging and parser maintainers",
        "target_issue_or_phase": "#901 and #984 / packaged-discovery gates",
        "next_gate": "Run installed-wheel and clean frozen-artifact discovery from an isolated working directory.",
        "preserved_seam": "Resource locators, parser profiles and packaging manifests remain unchanged.",
    },
    {
        "id": "HD-976-R006",
        "severity": "P2",
        "taxonomy": "CI / hosted-evidence / observability",
        "classification": "deferred residual risk",
        "reason": "Phase A did not dispatch Actions, and manual lanes plus failure-artifact behavior remain hosted-only evidence.",
        "accountable_owner": "CI maintainer",
        "target_issue_or_phase": "#914 and Phase B / exact-head CI gate",
        "next_gate": "Run authorized exact-head automatic/manual lanes and verify success/failure artifacts after Phase-B reconciliation.",
        "preserved_seam": "Workflow configuration and existing runs were inspected read-only and remain unchanged.",
    },
    {
        "id": "HD-976-R007",
        "severity": "P1",
        "taxonomy": "dependency-platform / toolchain / reproducibility",
        "classification": "deferred residual risk",
        "reason": "Python and local Rust tool resolution remains time/host dependent without a complete repository lock/toolchain contract.",
        "accountable_owner": "Build and dependency maintainer",
        "target_issue_or_phase": "#913 / reproducible-environment gate",
        "next_gate": "Adopt and verify the chosen Python/Rust lock and clean-environment installation policy.",
        "preserved_seam": "Dependency manifests, lockfiles and toolchain configuration remain unchanged in Phase A.",
    },
    {
        "id": "HD-976-R008",
        "severity": "P2",
        "taxonomy": "packaging / archive-permissions / release-policy",
        "classification": "deferred residual risk",
        "reason": "GitHub artifact archives normalize executable mode, but the repository has no settled contract that these uploads are directly runnable release artifacts.",
        "accountable_owner": "Release policy owner",
        "target_issue_or_phase": "#920 / artifact-delivery policy gate",
        "next_gate": "Decide artifact usability semantics and, if direct execution is required, verify mode restoration or a permission-preserving format.",
        "preserved_seam": "Upload configuration and artifact consumers remain unchanged pending the policy decision.",
    },
)


def _build_path_audit_map() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}

    def add(
        paths: Sequence[str],
        *,
        disposition: str,
        evidence_refs: Sequence[str],
        finding_ids: Sequence[str] = (),
        residual_risk_id: str | None = None,
    ) -> None:
        for path in paths:
            if path in records:
                raise AuditError(f"duplicate explicit path-audit record: {path}")
            records[path] = {
                "phase_a_status": "audited",
                "disposition": disposition,
                "evidence_refs": [f"EV-PATH:{path}", *evidence_refs],
                "finding_ids": list(finding_ids),
                "residual_risk_id": residual_risk_id,
                "snapshot_status": "deferred_to_phase_b",
                "terminal_snapshot": None,
            }

    add(
        [".github/workflows/ci.yml"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-CI",
            "EV-ACTIONS",
            "DP-HISTORY-FULL",
            "DP-HISTORY-SHALLOW",
            "DP-PR973-POLICY",
            "DP-CMM-NATIVE-MISSING",
            "NC-upstream-required-job-skip",
            "NC-warm-cache-only",
        ],
        finding_ids=[
            "HD-976-F001",
            "HD-976-F005",
            "HD-976-F006",
            "HD-976-F007",
            "HD-976-F009",
            "HD-976-F012",
            "HD-976-F013",
        ],
    )
    add(
        [".github/dependabot.yml"],
        disposition="confirmed_finding_surface",
        evidence_refs=["EV-DEPENDABOT-GROUPING", "EV-PR973", "DP-PR973-FAMILY", "DP-PR973-POLICY"],
        finding_ids=["HD-976-F003", "HD-976-F009"],
    )
    add(
        [".pre-commit-config.yaml"],
        disposition="confirmed_finding_surface",
        evidence_refs=["EV-PRECOMMIT-EXTERNAL", "EV-PR973", "DP-PR973-POLICY"],
        finding_ids=["HD-976-F003", "HD-976-F009"],
    )
    add(
        [".python-version"],
        disposition="confirmed_finding_surface",
        evidence_refs=["EV-ENVIRONMENT", "EV-WINDOWS-SETUP-COMMAND", "DP-WINDOWS-WHEEL-RESOLUTION"],
        finding_ids=["HD-976-F004"],
    )
    add(
        ["pyproject.toml", "requirements-dev.txt"],
        disposition="confirmed_finding_surface",
        evidence_refs=["EV-PYTHON-MANIFEST", "EV-PR973", "DP-PR973-FAMILY", "DP-PR973-POLICY"],
        finding_ids=["HD-976-F003", "HD-976-F009"],
    )
    add(
        [
            "requirements-anomaly.txt",
            "requirements-build.txt",
            "requirements-ocr.txt",
            "requirements.txt",
        ],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-PYTHON-MANIFEST",
            "EV-PR973",
            "DP-PR973-FAMILY",
            "DP-WINDOWS-WHEEL-RESOLUTION",
            "NC-import-green-workflow-broken",
        ],
        finding_ids=["HD-976-F003"],
    )
    add(
        ["packaging/build_nuitka.ps1", "packaging/build_native_and_package.ps1"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-BUILD-COMMANDS",
            "EV-PACKAGING",
            "DP-NUITKA-STALE",
            "NC-zero-exit-no-artifact",
            "NC-stale-partial-artifact",
            "NC-missing-packaged-asset",
        ],
        finding_ids=["HD-976-F002", "HD-976-F008"],
    )
    add(
        [
            "THIRD_PARTY_NOTICES.md",
            "build_windows_exe.bat",
            "build_windows_exe.ps1",
            "docs/release_checks/third_party_inventory_260711.json",
            "scripts/generate_third_party_inventory.py",
            "scripts/stage_release_notices.py",
        ],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-PACKAGING-EXPLICIT-ASSETS",
            "EV-PACKAGING-NOTICES",
            "NC-missing-packaged-asset",
        ],
        finding_ids=["HD-976-F008", "HD-976-F011"],
    )
    add(
        [
            "packaging/metroliza_onedir.spec",
            "packaging/metroliza_onefile.spec",
            "packaging/pyinstaller_common.py",
        ],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-PACKAGING-EXPLICIT-ASSETS",
            "EV-PACKAGING-NOTICES",
            "EV-PACKAGING-PROVENANCE",
            "NC-missing-packaged-asset",
            "NC-stale-same-release-provenance",
        ],
        finding_ids=["HD-976-F008", "HD-976-F011", "HD-976-F015"],
    )
    add(
        [
            "docs/perf_baseline_snapshot.json",
            "scripts/benchmark_paths.py",
            "scripts/benchmark_trend_compare.py",
        ],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-CI-CMM-GATE",
            "DP-CMM-NATIVE-MISSING",
            "NC-misleading-native-fallback",
            "NC-import-green-workflow-broken",
        ],
        finding_ids=["HD-976-F006"],
    )
    add(
        ["setup_windows_runtime.bat", "setup_windows_runtime.ps1"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-WINDOWS-SETUP-COMMAND",
            "EV-PACKAGING-WINDOWS-PREREQUISITE",
            "EV-ENVIRONMENT",
            "DP-WINDOWS-WHEEL-RESOLUTION",
        ],
        finding_ids=["HD-976-F004", "HD-976-F010", "HD-976-F014"],
    )
    add(
        ["scripts/windows_ocr_runtime_diagnostics.py"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-CI-WINDOWS-LANES",
            "EV-BUILD-COMMANDS",
            "EV-PLATFORM",
            "NC-sensitive-diagnostic-output",
        ],
        finding_ids=["HD-976-F014", "HD-976-F016"],
    )
    for crate in (
        "chart_renderer",
        "cmm_parser",
        "comparison_stats_bootstrap",
        "distribution_fit_ad",
        "group_stats_coercion",
    ):
        add(
            [
                f"src/metroliza/native/{crate}/Cargo.toml",
                f"src/metroliza/native/{crate}/Cargo.lock",
            ],
            disposition="confirmed_finding_surface",
            evidence_refs=["EV-RUST-MANIFEST-LOCK", "DP-CARGO-TESTS"],
            finding_ids=["HD-976-F007"],
        )

    add(
        ["docs/user_manual/group_analysis/user_manual.pdf"],
        disposition="deferred_residual_risk",
        evidence_refs=["EV-PACKAGING-MANUALS"],
        residual_risk_id="HD-976-R003",
    )
    add(
        [
            "packaging/metroliza_bootloader_splash.png",
            "packaging/metroliza_icon2.ico",
            "packaging/metroliza_package_entry.py",
        ],
        disposition="deferred_residual_risk",
        evidence_refs=[
            "EV-PACKAGING",
            "NC-missing-packaged-asset",
            "NC-repository-root-only-import",
            "NC-path-permission-boundary",
        ],
        residual_risk_id="HD-976-R001",
    )
    add(
        [
            "src/metroliza/resources/app_assets.py",
            "src/metroliza/resources/base64_encoded_files.py",
        ],
        disposition="deferred_residual_risk",
        evidence_refs=[
            "EV-PACKAGING",
            "NC-missing-packaged-asset",
            "NC-repository-root-only-import",
            "NC-path-permission-boundary",
        ],
        residual_risk_id="HD-976-R005",
    )
    add(
        [
            "scripts/measure_windows_startup.ps1",
            "scripts/summarize_startup_profile.py",
            "scripts/validate_packaged_pdf_parser.py",
            "scripts/validate_qt_runtime.py",
        ],
        disposition="deferred_residual_risk",
        evidence_refs=[
            "EV-CI-WINDOWS-LANES",
            "EV-BUILD-COMMANDS",
            "EV-PLATFORM",
            "DP-OCR-INFERENCE",
        ],
        residual_risk_id="HD-976-R001",
    )
    add(
        ["scripts/release_only_google_conversion_smoke.py"],
        disposition="deferred_residual_risk",
        evidence_refs=["EV-CI", "EV-PLATFORM-MANUAL-RELEASE"],
        residual_risk_id="HD-976-R002",
    )
    add(
        ["src/metroliza/app/build_provenance.py"],
        disposition="deferred_residual_risk",
        evidence_refs=[
            "EV-PACKAGING-PROVENANCE",
            "EV-BUILD-COMMANDS",
            "NC-zero-exit-no-artifact",
            "NC-stale-partial-artifact",
        ],
        residual_risk_id="HD-976-R004",
    )

    add(
        [".gitignore"],
        disposition="audited_no_confirmed_finding",
        evidence_refs=["EV-CONFIDENTIALITY", "EV-BUILD-COMMANDS"],
    )
    add(
        ["CHANGELOG.md", "scripts/sync_release_metadata.py", "src/metroliza/app/version.py"],
        disposition="audited_no_confirmed_finding",
        evidence_refs=["EV-CI-STATIC-COMMANDS", "EV-BUILD-COMMANDS"],
    )
    add(
        ["scripts/__init__.py", "src/metroliza/resources/__init__.py"],
        disposition="audited_no_confirmed_finding",
        evidence_refs=["EV-PACKAGING-HIDDEN-IMPORTS"],
    )
    add(
        ["scripts/build_provenance.py"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-PACKAGING-PROVENANCE",
            "NC-zero-exit-no-artifact",
            "NC-stale-partial-artifact",
            "NC-stale-same-release-provenance",
        ],
        finding_ids=["HD-976-F015"],
    )
    add(
        ["scripts/check_release_hygiene.py"],
        disposition="audited_no_confirmed_finding",
        evidence_refs=["EV-CI-STATIC-COMMANDS", "EV-CLASSIFICATIONS-ACCEPTED"],
    )
    add(
        ["scripts/fetch_rapidocr_models.py"],
        disposition="confirmed_finding_surface",
        evidence_refs=[
            "EV-PACKAGING-OCR-MODELS",
            "NC-interrupted-model-fetch-cleanup",
        ],
        finding_ids=["HD-976-F017"],
    )
    return records


PATH_AUDIT = _build_path_audit_map()

FALSIFIERS: tuple[dict[str, Any], ...] = (
    {
        "id": "missing-packaged-asset",
        "result": "detected",
        "production_gate": "tests/test_packaged_pdf_parser_validation.py::test_validate_vendored_header_ocr_models_rejects_missing_assets",
        "negative_control": "tests/test_build_delivery_audit.py::test_missing_required_packaged_asset_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_packaged_pdf_parser_validation.py::test_validate_vendored_header_ocr_models_rejects_missing_assets tests/test_build_delivery_audit.py::test_missing_required_packaged_asset_is_detected -q",
        "cwd": ".",
        "fixture": "pytest-generated temporary model directory; one required model omitted",
        "expected_diagnostic": "missing required packaged asset/model",
        "source_paths": ["tests/test_packaged_pdf_parser_validation.py"],
    },
    {
        "id": "repository-root-only-import",
        "result": "detected",
        "production_gate": "tests/test_directory_reorganization_architecture.py::test_canonical_imports_work_from_outside_repository_root",
        "negative_control": "tests/test_build_delivery_audit.py::test_repository_root_only_import_or_resource_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_directory_reorganization_architecture.py::test_canonical_imports_work_from_outside_repository_root tests/test_build_delivery_audit.py::test_repository_root_only_import_or_resource_is_detected -q",
        "cwd": ".",
        "fixture": "pytest temporary directory outside the repository plus synthetic failed outcome",
        "expected_diagnostic": "repository-root state",
        "source_paths": ["tests/test_directory_reorganization_architecture.py"],
    },
    {
        "id": "misleading-native-fallback",
        "result": "detected",
        "production_gate": "structural only: tests/test_build_native_and_package_helper.py::test_build_native_and_package_helper_covers_native_build_and_packaging_paths verifies RequireNative command wiring; no production mutation run",
        "negative_control": "tests/test_build_delivery_audit.py::test_required_native_backend_cannot_hide_behind_importable_fallback",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_native_and_package_helper.py::test_build_native_and_package_helper_covers_native_build_and_packaging_paths tests/test_build_delivery_audit.py::test_required_native_backend_cannot_hide_behind_importable_fallback -q",
        "cwd": ".",
        "fixture": "baseline helper source plus synthetic import-ok/native-unavailable state",
        "expected_diagnostic": "required native backend is unavailable",
        "source_paths": ["tests/test_build_native_and_package_helper.py"],
    },
    {
        "id": "new-static-finding",
        "result": "detected",
        "production_gate": f"{CAPTURE_PR973_PYTHON} -m ruff check . --statistics (observed exit 1, 1,671 findings) plus exact policy pytest command",
        "negative_control": "tests/test_build_delivery_audit.py::test_new_static_finding_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_ci_policy_sync.py::test_ci_workflow_keeps_static_typing_narrow_and_blocking tests/test_build_delivery_audit.py::test_new_static_finding_is_detected -q",
        "cwd": ".",
        "fixture": "baseline CI policy plus synthetic nonzero Ruff/mypy/security exit",
        "expected_diagnostic": "static gate finding",
        "source_paths": ["tests/test_ci_policy_sync.py"],
    },
    {
        "id": "zero-exit-no-artifact",
        "result": "detected",
        "production_gate": "tests/test_build_provenance.py::test_artifact_sidecar_requires_an_explicit_artifact",
        "negative_control": "tests/test_build_delivery_audit.py::test_zero_exit_without_required_artifact_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_provenance.py::test_artifact_sidecar_requires_an_explicit_artifact tests/test_build_delivery_audit.py::test_zero_exit_without_required_artifact_is_detected -q",
        "cwd": ".",
        "fixture": "pytest temporary dist directory with no current artifact",
        "expected_diagnostic": "zero-exit build produced no required artifact",
        "source_paths": ["tests/test_build_provenance.py"],
    },
    {
        "id": "stale-partial-artifact",
        "result": "detected",
        "production_gate": "tests/test_build_provenance.py::test_build_manifest_validation_rejects_stale_build_identity and tests/test_stage_release_notices.py::test_explicit_release_artifact_does_not_pick_up_stale_dist_outputs",
        "negative_control": "tests/test_build_delivery_audit.py::test_stale_artifact_is_detected_even_after_zero_exit, ::test_future_dated_unchanged_artifact_is_detected_after_zero_exit, ::test_touched_but_byte_identical_artifact_is_not_current_build_evidence and ::test_partial_artifact_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_provenance.py::test_build_manifest_validation_rejects_stale_build_identity tests/test_stage_release_notices.py::test_explicit_release_artifact_does_not_pick_up_stale_dist_outputs tests/test_build_delivery_audit.py::test_stale_artifact_is_detected_even_after_zero_exit tests/test_build_delivery_audit.py::test_future_dated_unchanged_artifact_is_detected_after_zero_exit tests/test_build_delivery_audit.py::test_touched_but_byte_identical_artifact_is_not_current_build_evidence tests/test_build_delivery_audit.py::test_partial_artifact_is_detected -q",
        "cwd": ".",
        "fixture": "pytest-generated stale manifest/artifact, future-dated unchanged pre-build artifact and undersized artifact",
        "expected_diagnostic": "stale identity, unchanged pre-build state, pre-attempt timestamp, or undersized artifact",
        "source_paths": ["tests/test_build_provenance.py", "tests/test_stage_release_notices.py"],
    },
    {
        "id": "import-green-workflow-broken",
        "result": "detected",
        "production_gate": f"{CAPTURE_PR973_PYTHON} -m pytest -q -p no:cacheprovider tests/test_ci_policy_sync.py tests/test_requirements_hygiene.py tests/test_security_audit.py (observed 4 failed, 46 passed)",
        "negative_control": "tests/test_build_delivery_audit.py::test_import_green_workflow_broken_family_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_requirements_hygiene.py tests/test_security_audit.py tests/test_build_delivery_audit.py::test_import_green_workflow_broken_family_is_detected -q",
        "cwd": ".",
        "fixture": "exact dependency-policy tests plus synthetic import-green/workflow-failed state",
        "expected_diagnostic": "passed imports but failed representative workflow",
        "source_paths": ["tests/test_requirements_hygiene.py", "tests/test_security_audit.py"],
    },
    {
        "id": "upstream-required-job-skip",
        "result": "detected",
        "production_gate": "existing exact-base run 33151703847: unit-tests failed and cmm-parser-perf-gate/perf-benchmarks skipped through needs; inspected read-only",
        "negative_control": "tests/test_build_delivery_audit.py::test_upstream_skip_or_failure_is_not_required_job_success",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_ci_policy_sync.py::test_ci_policy_keeps_manual_smoke_lane_semantics_explicit tests/test_build_delivery_audit.py::test_upstream_skip_or_failure_is_not_required_job_success -q",
        "cwd": ".",
        "fixture": "baseline workflow policy plus skipped/cancelled/failure conclusions",
        "expected_diagnostic": "required CI job did not conclude success",
        "source_paths": ["tests/test_ci_policy_sync.py"],
    },
    {
        "id": "warm-cache-only",
        "result": "detected",
        "production_gate": "unavailable: no isolated cold-versus-warm production workflow mutation was executed; exact setup-python cache declarations were inspected only",
        "negative_control": "tests/test_build_delivery_audit.py::test_wrong_or_warm_only_cache_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_ci_policy_sync.py::test_ci_workflow_keeps_coverage_visibility_contract tests/test_build_delivery_audit.py::test_wrong_or_warm_only_cache_is_detected -q",
        "cwd": ".",
        "fixture": "baseline cache declarations plus cold-fail/key-mismatch states",
        "expected_diagnostic": "workflow succeeds only with warm cache or key mismatch",
        "source_paths": ["tests/test_ci_policy_sync.py"],
    },
    {
        "id": "shallow-history",
        "result": "detected",
        "production_gate": "tests/test_bug_sweep_coverage.py::test_shallow_clone_missing_historical_commit_fails_closed",
        "negative_control": "tests/test_build_delivery_audit.py::test_missing_historical_commit_fails_closed",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_bug_sweep_coverage.py::test_shallow_clone_missing_historical_commit_fails_closed tests/test_build_delivery_audit.py::test_missing_historical_commit_fails_closed -q",
        "cwd": ".",
        "fixture": "local sanitized Git history and missing 40-hex commit",
        "expected_diagnostic": "historical audited commit unavailable",
        "source_paths": ["tests/test_bug_sweep_coverage.py"],
    },
    {
        "id": "path-permission-boundary",
        "result": "detected",
        "production_gate": "tests/test_stage_release_notices.py::test_stage_release_notices_adds_visible_bundle_for_each_artifact",
        "negative_control": "tests/test_build_delivery_audit.py::test_spaces_non_ascii_and_long_path_round_trip and ::test_read_only_output_is_detected_from_mode_bits",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_stage_release_notices.py::test_stage_release_notices_adds_visible_bundle_for_each_artifact tests/test_build_delivery_audit.py::test_spaces_non_ascii_and_long_path_round_trip tests/test_build_delivery_audit.py::test_read_only_output_is_detected_from_mode_bits -q",
        "cwd": ".",
        "fixture": "sanitized spaces/non-ASCII/long path and mode-0555 directory",
        "expected_diagnostic": "read-only output target",
        "source_paths": ["tests/test_stage_release_notices.py"],
    },
    {
        "id": "missing-tool-optional-dependency",
        "result": "detected",
        "production_gate": "tests/test_packaged_pdf_parser_validation.py::test_pyinstaller_required_collection_fails_when_dependency_is_missing",
        "negative_control": "tests/test_build_delivery_audit.py::test_missing_required_tool_has_truthful_diagnostic and ::test_missing_optional_dependency_is_not_misreported_as_available",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_packaged_pdf_parser_validation.py::test_pyinstaller_required_collection_fails_when_dependency_is_missing tests/test_build_delivery_audit.py::test_missing_required_tool_has_truthful_diagnostic tests/test_build_delivery_audit.py::test_missing_optional_dependency_is_not_misreported_as_available -q",
        "cwd": ".",
        "fixture": "monkeypatched missing required package and explicit optional capability",
        "expected_diagnostic": "required dependency unavailable; optional capability remains unavailable",
        "source_paths": ["tests/test_packaged_pdf_parser_validation.py"],
    },
    {
        "id": "stale-same-release-provenance",
        "result": "detected",
        "production_gate": "exact-baseline packaging/pyinstaller_common.py accepts METROLIZA_BUILD_PROVENANCE_PATH after schema/packager/release checks only; scripts/build_provenance.py stage performs schema-only validation",
        "negative_control": "tests/test_build_delivery_audit.py::test_same_release_stale_git_or_timestamp_provenance_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_provenance.py tests/test_build_delivery_audit.py::test_same_release_stale_git_or_timestamp_provenance_is_detected -q",
        "cwd": ".",
        "fixture": "synthetic structurally valid same-release manifest identity with stale Git SHA or pre-attempt timestamp",
        "expected_diagnostic": "build provenance Git identity or build-attempt freshness mismatch",
        "source_paths": [
            "packaging/pyinstaller_common.py",
            "scripts/build_provenance.py",
            "tests/test_build_provenance.py",
        ],
    },
    {
        "id": "sensitive-diagnostic-output",
        "result": "detected",
        "production_gate": "exact-baseline Windows OCR diagnostic payload statically includes local/environment paths, raw subprocess output and optional document/database fields",
        "negative_control": "tests/test_build_delivery_audit.py::test_sensitive_diagnostic_values_require_redaction",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_delivery_audit.py::test_sensitive_diagnostic_values_require_redaction -q",
        "cwd": ".",
        "fixture": "synthetic local path, token, raw header text and database-row values",
        "expected_diagnostic": "diagnostic output retains sensitive value",
        "source_paths": [
            "scripts/windows_ocr_runtime_diagnostics.py",
            "scripts/diagnose_header_ocr_metadata.py",
        ],
    },
    {
        "id": "interrupted-model-fetch-cleanup",
        "result": "detected",
        "production_gate": "exact-baseline fetch helper cleanup is confined to the completed digest-mismatch branch; interrupted URL/read/write exceptions bypass it",
        "negative_control": "tests/test_build_delivery_audit.py::test_interrupted_model_fetch_temp_residue_is_detected",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_delivery_audit.py::test_interrupted_model_fetch_temp_residue_is_detected -q",
        "cwd": ".",
        "fixture": "pytest temporary output directory containing a partial model .tmp residue",
        "expected_diagnostic": "partial model-fetch temporary file remains",
        "source_paths": ["scripts/fetch_rapidocr_models.py"],
    },
)

DISCOVERY_PROBES: tuple[dict[str, Any], ...] = (
    {
        "id": "DP-HISTORY-FULL",
        "probe": "schema-v4 full-history terminal snapshot",
        "command": "original compound temporary-clone argv not retained; production control is tests/test_bug_sweep_coverage.py::test_real_local_git_commits_enumerate_exact_historical_trees",
        "cwd": "sanitized temporary Git repository",
        "subject_refs": ["sanitized temporary Git history fixture; not a metroliza revision"],
        "production_paths": ["tests/test_bug_sweep_coverage.py"],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "accepted 935/935 with older audited commit object present",
    },
    {
        "id": "DP-HISTORY-SHALLOW",
        "probe": "schema-v4 depth-1/no-tags terminal snapshot",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_bug_sweep_coverage.py::test_shallow_clone_missing_historical_commit_fails_closed -q",
        "cwd": ".",
        "subject_refs": ["sanitized depth-1 temporary Git fixture; not a metroliza revision"],
        "production_paths": ["tests/test_bug_sweep_coverage.py"],
        "exact_argv_retained": True,
        "exit_code": 1,
        "result": "failed closed because audited commit object was unavailable",
    },
    {
        "id": "DP-PR973-FAMILY",
        "probe": "PR #973 isolated family workflows",
        "command": "original aggregate argv was not retained; nine narrower exact family command rows are separately preserved under /pr_973/families/*/commands",
        "cwd": str(CAPTURE_PR973_CWD),
        "subject_refs": [BASELINE_SUBJECT_REF, PR973_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "observational aggregate completed; exact aggregate count/argv is not retained; use individual family rows as captured command evidence, not durable replay evidence",
    },
    {
        "id": "DP-PR973-POLICY",
        "probe": "PR #973 focused policy synchronization",
        "command": f"{CAPTURE_PR973_PYTHON} -m pytest -q -p no:cacheprovider tests/test_ci_policy_sync.py tests/test_requirements_hygiene.py tests/test_security_audit.py",
        "cwd": str(CAPTURE_PR973_CWD),
        "subject_refs": [PR973_SUBJECT_REF],
        "exact_argv_retained": True,
        "exit_code": 1,
        "result": "4 failed, 46 passed for Ruff/mypy/Qt/Pillow contract drift",
    },
    {
        "id": "DP-PR973-QT",
        "probe": "PR #973 corrected offscreen Qt comparison",
        "command": "original 30-test baseline/proposal comparison argv was not retained; narrower Qt validator/eight-test commands are separately preserved under /pr_973/families",
        "cwd": str(CAPTURE_PR973_CWD),
        "subject_refs": [BASELINE_SUBJECT_REF, PR973_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "observational baseline/proposal comparison passed; exact 30-test argv was not retained, so only narrower captured command rows are auditable",
    },
    {
        "id": "DP-OCR-INFERENCE",
        "probe": "RapidOCR model load and sanitized fixture inference",
        "command": "original exact inline probe command was not retained; observational only",
        "cwd": f"{CAPTURE_TEMP_ROOT} isolated baseline and proposal environments",
        "subject_refs": [BASELINE_SUBJECT_REF, PR973_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "both environments returned 19 records with identical leading text",
    },
    {
        "id": "DP-CARGO-TESTS",
        "probe": "five Cargo test --locked runs with PYO3_PYTHON=Python 3.11",
        "command": "aggregate shorthand only; five concrete cargo metadata and five concrete cargo test argv are preserved under /pr_973/families for Rust/native wheel",
        "cwd": str(CAPTURE_PR973_CWD),
        "subject_refs": [PR973_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "all five captured child commands passed; aggregate replay additionally depends on ephemeral Cargo/Python state and is not acceptance evidence",
    },
    {
        "id": "DP-WINDOWS-WHEEL-RESOLUTION",
        "probe": "Windows CPython 3.11 mixed-binary-policy resolution observations",
        "command": "aggregate shorthand only; seven captured argv rows are preserved under /pr_973/windows_resolution_rows",
        "cwd": str(CAPTURE_PR973_CWD),
        "subject_refs": [BASELINE_SUBJECT_REF, PR973_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "seven child commands resolved captured inputs: four strict wheel-only, one wheel-only with a Nuitka source exception, and two ordinary-policy rows; the aggregate is not replayable without the ephemeral cache and is not acceptance evidence",
    },
    {
        "id": "DP-CMM-NATIVE-MISSING",
        "probe": "enforced CMM guardrail without native backend",
        "command": "production workflow command preserved under /ci/exact_baseline_inventory; exact standalone reproduction argv was not retained",
        "cwd": "authorized baseline checkout",
        "subject_refs": [BASELINE_SUBJECT_REF],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "misleading successful skip reproduced; finding #993",
    },
    {
        "id": "DP-NUITKA-STALE",
        "probe": "Nuitka stale root artifact notice staging",
        "command": "sanitized PowerShell function probe; exact inline invocation was not retained",
        "cwd": "temporary package directory",
        "subject_refs": [BASELINE_SUBJECT_REF, "sanitized temporary package-directory fixture"],
        "exact_argv_retained": False,
        "exit_code": 0,
        "result": "14-byte stale artifact accepted; finding #992",
    },
    {
        "id": "DP-OCR-HASH-DELETE",
        "probe": "OCR model hashes and deletion control",
        "command": f"{CAPTURE_BASELINE_PYTHON} scripts/validate_packaged_pdf_parser.py --require-header-ocr --header-ocr-model-dir src/metroliza/resources/ocr_models/rapidocr",
        "negative_control_command": "PYTHONPATH=src:. python -m pytest tests/test_packaged_pdf_parser_validation.py::test_validate_vendored_header_ocr_models_rejects_missing_assets -q",
        "cwd": ".",
        "subject_refs": [BASELINE_SUBJECT_REF],
        "exact_argv_retained": True,
        "exit_code": 0,
        "result": "three hashes matched; deleted detector failed closed",
    },
    {
        "id": "DP-PATH-BOUNDARIES",
        "probe": "Unicode/spaces/long/read-only resource boundaries",
        "command": "PYTHONPATH=src:. python -m pytest tests/test_build_delivery_audit.py::test_spaces_non_ascii_and_long_path_round_trip tests/test_build_delivery_audit.py::test_read_only_output_is_detected_from_mode_bits -q",
        "cwd": ".",
        "subject_refs": ["content-addressed Phase-A audit mutation under /audit_implementation"],
        "exact_argv_retained": True,
        "exit_code": 0,
        "result": "POSIX spaces/non-ASCII/long paths passed; read-only destination failed clearly",
    },
)

CLASSIFICATIONS = {
    "accepted_behaviors": [
        "Manual packaging and Windows-startup jobs skip on normal PR/push events by explicit design; a skip is not package evidence.",
        "Advisory performance trend uses continue-on-error by explicit policy; it cannot be cited as a blocking gate.",
        "Optional native fallback is accepted only when the caller does not request native enforcement and diagnostics stay truthful.",
        "GitHub Actions and CI sibling checkouts use full immutable SHAs; checkout credentials are not persisted. Two pre-commit hook repositories still use mutable version tags and are separately classified.",
        "Security audit passes with the finite reviewed Bandit baseline; renewal/removal remains explicitly owned by #906.",
    ],
    "false_positives": [
        "An initial Qt aggregation inherited host QT_QPA_PLATFORMTHEME=gtk3; corrected offscreen runs passed and it is not a dependency regression.",
        "Coverage-summary missing-XML exits zero, but the preceding coverage-generation step is blocking; this is not an independent false-green.",
        "Warm pip cache restoration can be stale for efficiency, but pip still resolves requirements; no wrong installed version was demonstrated.",
    ],
    "hypotheses": [
        "Existing exact-base run 33151703847 received SIGSEGV in the industrial analytics dialog coverage shard; #998 owns the P1 root-cause hypothesis and bounded reproducer.",
        "Nuitka Windows clang selection may conflate clang and clang-cl; exact Windows toolchain reproduction is required under #913.",
    ],
}

BUILD_COMMAND_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "path": "setup_windows_runtime.bat",
        "surface": "Windows runtime setup wrapper",
        "command": "setup_windows_runtime.bat [PowerShell arguments]",
        "callers": ["operator"],
        "platform": "Windows cmd.exe -> powershell.exe",
        "output_contract": "delegates all arguments and exit status to setup_windows_runtime.ps1",
        "failure_contract": "PowerShell launch or delegated setup failure is nonzero",
    },
    {
        "path": "setup_windows_runtime.ps1",
        "surface": "Windows runtime setup",
        "command": ".\\setup_windows_runtime.ps1 [-PythonVersion <version>] [-VenvDir <path>] [-Clean] [-WithDev] [-WithBuild] [-SkipOcr] [-SkipValidation] [-InstallVcRedist]",
        "callers": ["setup_windows_runtime.bat", "README Windows setup guidance", "operator"],
        "platform": "Windows PowerShell",
        "environment": "Windows; default PythonVersion=3.12 conflicts with canonical 3.11",
        "output_contract": ".venv plus optional runtime/OCR/Qt validation; no release artifact",
        "failure_contract": "strict mode and checked subprocesses stop when a child returns nonzero; the OCR diagnostic child currently returns zero for recorded smoke-row failures, so those failures remain false-green under #1000",
    },
    {
        "path": "diagnose_windows_ocr.bat",
        "surface": "Windows OCR diagnostic wrapper",
        "command": "diagnose_windows_ocr.bat [PowerShell arguments]",
        "callers": ["operator"],
        "platform": "Windows cmd.exe -> powershell.exe",
        "output_contract": "delegates all arguments and exit status to diagnose_windows_ocr.ps1",
        "failure_contract": "PowerShell launch or delegated diagnostic failure is nonzero",
    },
    {
        "path": "diagnose_windows_ocr.ps1",
        "surface": "Windows OCR diagnostic orchestrator",
        "command": ".\\diagnose_windows_ocr.ps1 [-PdfPath <path>] [-DbFile <path>] [-OutputPath <path>] [-VenvDir <path>] [-Compact]",
        "callers": ["diagnose_windows_ocr.bat", "README Windows OCR troubleshooting", "operator"],
        "platform": "Windows PowerShell",
        "environment": "prefers <VenvDir>/Scripts/python.exe, then PATH python or py",
        "output_contract": "delegates to scripts/windows_ocr_runtime_diagnostics.py and emits optional JSON",
        "failure_contract": "missing Python or child nonzero fails; diagnostic child records row failures but currently exits zero",
    },
    {
        "path": "build_windows_exe.bat",
        "surface": "Windows PyInstaller wrapper",
        "command": "build_windows_exe.bat [PowerShell arguments]",
        "callers": ["README Windows build guidance", "operator"],
        "platform": "Windows cmd.exe -> powershell.exe",
        "output_contract": "delegates all arguments to build_windows_exe.ps1; success is preserved but every nonzero PowerShell status is normalized to 1",
        "failure_contract": "PowerShell launch or delegated build failure exits 1 rather than preserving the child code",
    },
    {
        "path": "build_windows_exe.ps1",
        "surface": "Windows PyInstaller",
        "command": ".\\build_windows_exe.ps1 [-Clean] [-WithNative] [-SkipInstall] [-Mode onefile|onedir|both]",
        "callers": [
            "build_windows_exe.bat",
            "README Windows build guidance",
            ".github/workflows/ci.yml",
            "operator",
        ],
        "platform": "Windows PowerShell",
        "environment": "Windows .venv-build; clean is optional; floating pip/wheel and lower bounds",
        "output_contract": "exact release-label EXE paths plus notice and provenance sidecars",
        "failure_contract": "checked install/build/validation and exact artifact selection must succeed",
    },
    {
        "path": "packaging/build_native_and_package.ps1",
        "surface": "Native wheel/package helper",
        "command": ".\\packaging\\build_native_and_package.ps1 [-Packager none|nuitka|pyinstaller] [-NativeTargets all|cmm|chart|group-stats|comparison-stats|distribution-fit] [declared switches/paths]",
        "callers": ["build_windows_exe.ps1 when -WithNative is selected", "operator"],
        "platform": "PowerShell on Windows/Linux/macOS",
        "environment": "active Python and cargo; five maturin --locked targets",
        "output_contract": "native availability verification, package-specific artifacts and sidecars",
        "failure_contract": "strict checked native build/import and delegated packager failures stop execution",
    },
    {
        "path": "packaging/build_nuitka.ps1",
        "surface": "Nuitka package",
        "command": ".\\packaging\\build_nuitka.ps1 [-EntryPoint <path>] [-OutputName <name>] [-IconPath <path>] [-BundleCredentials -CredentialsPath <path>] [-Mode onefile|standalone] [declared switches]",
        "callers": ["packaging/build_native_and_package.ps1", "operator"],
        "platform": "PowerShell on Windows/Linux/macOS",
        "environment": "active Python; selected GCC/Clang strategy; repository-root PYTHONPATH",
        "output_contract": "mode-specific executable should be fresh; current defect #992",
        "failure_contract": "strict dependency/resource/compiler checks; stale standalone-root selection remains #992",
    },
    {
        "path": "packaging/metroliza_onefile.spec",
        "surface": "PyInstaller onefile spec",
        "command": "Windows helpers: python -m PyInstaller --noconfirm packaging/metroliza_onefile.spec; Linux manual CI: pyinstaller packaging/metroliza_onefile.spec",
        "callers": [
            "build_windows_exe.ps1",
            "packaging/build_native_and_package.ps1",
            ".github/workflows/ci.yml",
        ],
        "platform": "host PyInstaller; Windows release and Linux manual smoke",
        "environment": "shared packaging/pyinstaller_common.py collection contract",
        "output_contract": "dist/metroliza_P_<release-label>[.exe] plus embedded provenance/resources",
        "failure_contract": "PyInstaller nonzero or caller's exact artifact validation fails",
    },
    {
        "path": "packaging/metroliza_onedir.spec",
        "surface": "PyInstaller onedir spec",
        "command": "python -m PyInstaller --noconfirm packaging/metroliza_onedir.spec",
        "callers": ["build_windows_exe.ps1", "packaging/build_native_and_package.ps1"],
        "platform": "Windows release helper",
        "environment": "shared packaging/pyinstaller_common.py collection contract",
        "output_contract": "dist/metroliza_P_<release-label>_onedir/ with executable and embedded resources",
        "failure_contract": "PyInstaller nonzero or caller's exact directory/artifact validation fails",
    },
    {
        "path": "packaging/metroliza_package_entry.py",
        "surface": "frozen application entrypoint",
        "command": "python packaging/metroliza_package_entry.py",
        "callers": ["both PyInstaller specs", "packaging/build_nuitka.ps1"],
        "platform": "source/package bootstrap on supported desktop hosts",
        "environment": "requires src package/import and packaged resources",
        "output_contract": "imports and delegates to metroliza.app.bootstrap.run_application",
        "failure_contract": (
            "import/bootstrap exceptions propagate; the run_application return value is "
            "passed to SystemExit"
        ),
    },
    {
        "path": "scripts/benchmark_paths.py",
        "surface": "performance benchmark producer",
        "command": "python scripts/benchmark_paths.py [declared benchmark sizes/scenario/guardrail options]",
        "callers": [".github/workflows/ci.yml", "operator"],
        "platform": "Linux CI/source host",
        "environment": "optional native backends; generated/sanitized benchmarks",
        "output_contract": "benchmark JSON/CSV plus guardrail result",
        "failure_contract": "invalid CLI/workload/threshold is nonzero; native-missing false-green is #993",
    },
    {
        "path": "scripts/benchmark_trend_compare.py",
        "surface": "performance trend comparator",
        "command": "python scripts/benchmark_trend_compare.py --baseline <json> --runs <json...> --output-json <json> [threshold options]",
        "callers": [".github/workflows/ci.yml", "operator"],
        "platform": "Linux CI/source host",
        "environment": "checked-in baseline plus current run files",
        "output_contract": "trend comparison JSON and threshold exit",
        "failure_contract": "missing/malformed input or blocking threshold is nonzero; CI trend step is advisory",
    },
    {
        "path": "scripts/build_provenance.py",
        "surface": "build provenance CLI",
        "command": "python scripts/build_provenance.py generate|validate|stage [declared subcommand options]",
        "callers": [
            "packaging/pyinstaller_common.py",
            "build_windows_exe.ps1",
            "packaging/build_native_and_package.ps1",
        ],
        "platform": "source/package build host",
        "environment": "exact Git checkout and current Python/Rust tools",
        "output_contract": "generate records the active checkout; validate checks schema/packager/release; stage copies a schema-valid manifest and binds explicit artifact SHA-256",
        "failure_contract": "malformed/schema/packager/release mismatch or missing explicit artifact is nonzero; same-release stale Git/time identity is accepted (#1001)",
    },
    {
        "path": "scripts/check_release_hygiene.py",
        "surface": "release hygiene scanner",
        "command": "python scripts/check_release_hygiene.py",
        "callers": [".github/workflows/ci.yml", ".pre-commit-config.yaml", "operator"],
        "platform": "source checkout",
        "environment": "tracked repository text",
        "output_contract": "diagnostics only",
        "failure_contract": "forbidden release residue is nonzero",
    },
    {
        "path": "scripts/fetch_rapidocr_models.py",
        "surface": "vendored OCR model fetch",
        "command": "python scripts/fetch_rapidocr_models.py [--output-dir <path>] [--force]",
        "callers": ["operator"],
        "platform": "networked source host",
        "environment": "network download; fixed model digests",
        "output_contract": "three verified RapidOCR model files",
        "failure_contract": "completed hash mismatch deletes the temporary output and fails; URL/read/write interruption can leave a partial .tmp file",
    },
    {
        "path": "scripts/generate_third_party_inventory.py",
        "surface": "third-party inventory generator",
        "command": "python scripts/generate_third_party_inventory.py [--requirements <path>...] [--cargo-manifest <path>...] [--output <path>]",
        "callers": ["operator/release preparation"],
        "platform": "source checkout",
        "environment": "declared Python/Rust manifests plus the active installed Python distributions/metadata and Cargo tool/cache state",
        "output_contract": "environment-dependent dependency/review content plus live generated_at timestamp; reproducibility requires a fully locked, identity-bound capture environment",
        "failure_contract": "missing roots or Cargo warnings are nonzero only after a partial inventory file is written; parse/write failures are nonzero",
    },
    {
        "path": "scripts/measure_windows_startup.ps1",
        "surface": "packaged Windows startup measurement",
        "command": ".\\scripts\\measure_windows_startup.ps1 -ArtifactPath <path...> [-Iterations <n>] [-WarmupRuns <n>] [-Offscreen] [-OutputDirectory <path>]",
        "callers": [".github/workflows/ci.yml", "operator"],
        "platform": "Windows PowerShell",
        "environment": "current packaged executable; generated profile output",
        "output_contract": "per-run startup profiles and summary artifacts",
        "failure_contract": "nonzero executable, missing required event, or invalid profile fails",
    },
    {
        "path": "scripts/release_only_google_conversion_smoke.py",
        "surface": "release-only Google conversion smoke",
        "command": "METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 python scripts/release_only_google_conversion_smoke.py",
        "callers": ["authorized local release operator only"],
        "platform": "networked authenticated source host",
        "environment": "explicit opt-in and credentials; not run in Phase A",
        "output_contract": (
            "validates conversion and cleans the local TemporaryDirectory workbook; a "
            "successful remote Google Sheet persists and requires manual cleanup"
        ),
        "failure_contract": (
            "missing opt-in/credentials or conversion/validation failure is nonzero; the "
            "export layer attempts best-effort remote deletion only for exceptions after a "
            "file ID exists, while post-success smoke assertions can also leave the remote "
            "Sheet and cleanup exceptions are warning-only"
        ),
    },
    {
        "path": "scripts/stage_release_notices.py",
        "surface": "release notice staging",
        "command": "python scripts/stage_release_notices.py [--dist-dir <path>] [--artifact <path>...] [--notice <path>] [--inventory <path>]",
        "callers": [
            "build_windows_exe.ps1",
            "packaging/build_native_and_package.ps1",
            "packaging/build_nuitka.ps1",
            ".github/workflows/ci.yml",
            "operator",
        ],
        "platform": "build host",
        "environment": (
            "distribution directory, notice/inventory inputs, and either explicit artifact "
            "paths or recursively discovered executable/archive candidates"
        ),
        "output_contract": (
            "always creates a root dist/release-notices bundle, plus one visible .licenses "
            "sidecar per explicit artifact or discovered candidate; no candidate still "
            "succeeds with the root bundle"
        ),
        "failure_contract": (
            "missing notice/inventory or an explicitly selected artifact is nonzero; an "
            "empty or initially missing dist with no candidates succeeds"
        ),
    },
    {
        "path": "scripts/summarize_startup_profile.py",
        "surface": "startup profile summarizer",
        "command": "python scripts/summarize_startup_profile.py <profile.jsonl>",
        "callers": ["README/manual documentation", "operator"],
        "platform": "source host",
        "environment": "generated startup profile JSONL",
        "output_contract": "summary JSON on stdout; an empty/incomplete valid JSONL profile produces event_count=0 and nullable metrics",
        "failure_contract": "missing/unreadable input, malformed JSON or incompatible value types are nonzero; missing expected events alone remains zero",
    },
    {
        "path": "scripts/sync_release_metadata.py",
        "surface": "release metadata synchronization check",
        "command": "read-only: python scripts/sync_release_metadata.py --check; mutating: python scripts/sync_release_metadata.py",
        "callers": [".github/workflows/ci.yml", "operator"],
        "platform": "source checkout",
        "environment": "canonical src/metroliza/app/version.py and consumer files",
        "output_contract": "--check reports drift without writing; default mode rewrites the exact README/CHANGELOG metadata occurrences",
        "failure_contract": "--check drift is nonzero; default mode fails unless each target has exactly one expected replacement",
    },
    {
        "path": "scripts/validate_packaged_pdf_parser.py",
        "surface": "packaged PDF/OCR validator",
        "command": "python scripts/validate_packaged_pdf_parser.py [--report <xml>] [--allow-broken-pdf-parser-build] [--require-header-ocr] [--allow-missing-header-ocr-build] [--header-ocr-model-dir <path>]",
        "callers": [
            "setup_windows_runtime.ps1",
            "build_windows_exe.ps1",
            "packaging/build_native_and_package.ps1",
            "packaging/build_nuitka.ps1",
            ".github/workflows/ci.yml",
            "operator",
        ],
        "platform": "source or packaged environment",
        "environment": "PyMuPDF, parser modules, optional OCR models/providers",
        "output_contract": "validated backend/modules/models and optional fixture parse",
        "failure_contract": "missing required runtime component/model/text is nonzero",
    },
    {
        "path": "scripts/validate_qt_runtime.py",
        "surface": "Qt runtime validator",
        "command": "python scripts/validate_qt_runtime.py [--output <json>] [--compact]",
        "callers": ["setup_windows_runtime.ps1", "README/manual diagnostics", "operator"],
        "platform": "installed source/runtime host",
        "environment": "PyQt6 wrapper/payload and platform plugin environment",
        "output_contract": "JSON version/import/plugin diagnostics",
        "failure_contract": "PyQt import failure or wrapper/payload major-minor mismatch is nonzero; plugin/library paths are diagnostic strings and their presence/loadability is not validated",
    },
    {
        "path": "scripts/windows_ocr_runtime_diagnostics.py",
        "surface": "Windows OCR runtime diagnostics",
        "command": "python scripts/windows_ocr_runtime_diagnostics.py [--pdf <path>] [--db-file <path>] [--output <json>] [--compact]",
        "callers": ["diagnose_windows_ocr.ps1", "setup_windows_runtime.ps1", "operator"],
        "platform": "Windows runtime",
        "environment": "installed OCR providers plus optional local PDF/database; payload can contain sensitive paths, environment/process details, document text/metadata and database rows",
        "output_contract": "raw provider/model/parser diagnostics JSON; not sanitized for publication and must remain local or be manually redacted (#1002)",
        "failure_contract": "uncaught argument/path/serialization failures are nonzero; recorded diagnostic smoke-row failures are serialized but main returns zero (false-green finding)",
    },
)


def _captured_validation(
    command: str,
    argv: Sequence[str],
    result: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "command": command,
        "argv": list(argv),
        "cwd": str(CAPTURE_AUDIT_CWD),
        "observed_at": VALIDATION_GATE_DATE,
        "result": result,
        "subject_refs": [BASELINE_SUBJECT_REF],
        "binding": (
            "execution claim is bound by validation_receipt.tested_implementation_refs; "
            "regeneration never substitutes current bytes"
        ),
        **details,
    }


CAPTURED_VALIDATION: tuple[dict[str, Any], ...] = (
    _captured_validation(
        "validate_bug_sweep_coverage.py",
        [f"{CAPTURE_BASELINE_PYTHON} scripts/quality/validate_bug_sweep_coverage.py"],
        "935/935 tracked paths covered; zero uncovered and zero duplicate-primary",
    ),
    _captured_validation(
        "pre-publication application pytest",
        [
            f"{VALIDATION_HEADLESS_PREFIX} -m pytest tests -q "
            "-p no:cacheprovider --ignore=tests/test_build_delivery_audit.py"
        ],
        "all non-self-referential application/control-plane tests exited zero; the complete suite including the packet audit is a required external post-publication parking gate",
        environment_correction=(
            "unset host-only QT_QPA_PLATFORMTHEME so QT_QPA_PLATFORM=offscreen matches "
            "a clean hosted runner"
        ),
    ),
    _captured_validation(
        "Ruff full repository",
        [
            f"{CAPTURE_BASELINE_PYTHON} -m ruff check --no-cache .",
            f"{VALIDATION_HEADLESS_PREFIX} -m pytest tests/test_complexity_ratchet.py -q "
            "-p no:cacheprovider",
        ],
        "pass; complexity ratchet also passed",
    ),
    _captured_validation(
        "compileall",
        [f"{CAPTURE_BASELINE_PYTHON} -m compileall -q -x '^\\./\\.git/' ."],
        "pass",
    ),
    _captured_validation(
        "narrow mypy",
        [
            f"{CAPTURE_BASELINE_PYTHON} -m mypy "
            f"--cache-dir {CAPTURE_TEMP_ROOT / 'metroliza-976-validation-mypy-cache-v5'} "
            "src/metroliza/integrations/google_credentials_hygiene.py "
            "src/metroliza/industrial/anomaly/contracts.py "
            "src/metroliza/industrial/realtime/stream_contracts.py"
        ],
        "no issues in the three workflow-owned source files",
    ),
    _captured_validation(
        "parser smoke",
        [
            f"{CAPTURE_BASELINE_PYTHON} scripts/parser_plugin_self_service.py init "
            "--plugin-id ci_smoke --display-name 'CI Smoke' --source-format csv "
            f"--output {CAPTURE_PARSER_SMOKE_ROOT}/workspace/profile.yaml --force",
            f"{CAPTURE_BASELINE_PYTHON} scripts/parser_plugin_self_service.py validate "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/profile.yaml --expected-results "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/expected_results.csv --workspace "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace",
            f"{CAPTURE_BASELINE_PYTHON} scripts/parser_plugin_self_service.py diagnose "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/profile.yaml "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/samples/sample_report_01.csv",
            f"{CAPTURE_BASELINE_PYTHON} scripts/parser_plugin_self_service.py --home "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/home install "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/profile.yaml --expected-results "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/expected_results.csv --workspace "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace --approved-by ci",
            f"{CAPTURE_BASELINE_PYTHON} scripts/parser_plugin_self_service.py --home "
            f"{CAPTURE_PARSER_SMOKE_ROOT}/home evidence ci_smoke",
        ],
        "init, workspace-derived validate, diagnose, isolated-home install and evidence commands passed",
        fixture="sanitized CSV and expected-results fixture under the held, non-writable recorded temporary workspace",
        explicit_sample_boundary=(
            "not used by the receipt because the exact-base argparse append/tuple defect "
            "crashes before command execution; confirmed finding HD-976-F018/#1004"
        ),
    ),
    _captured_validation(
        "metadata sync check",
        [f"{CAPTURE_BASELINE_PYTHON} scripts/sync_release_metadata.py --check"],
        "pass",
    ),
    _captured_validation(
        "release hygiene",
        [f"{CAPTURE_BASELINE_PYTHON} scripts/check_release_hygiene.py"],
        "pass",
    ),
    _captured_validation(
        "secret scan",
        [
            f"{CAPTURE_BASELINE_PYTHON} scripts/security_audit.py --secret-scan-only "
            f"--base-ref {BASELINE_SHA}"
        ],
        "pass against the authorized base",
    ),
    _captured_validation(
        "pinned-sibling security audit",
        [
            *SECURITY_SIBLING_PREFLIGHT_COMMANDS,
            f"{CAPTURE_BASELINE_PYTHON} scripts/security_audit.py --ci "
            f"--sibling-root {CAPTURE_SECURITY_MATERIALIZED}",
        ],
        "pass against private read-only standalone materializations of the three workflow-pinned sibling commit trees; retained preflights bound those materializations immediately before the audit; live advisory lookup found no known vulnerabilities; only reviewed Bandit baseline findings remained",
        subject_refs=[
            BASELINE_SUBJECT_REF,
            *[
                f"{row['repository']} HEAD@{row['commit']} tree={row['tree']} "
                f"status={row['worktree_status']}"
                for row in SECURITY_SIBLING_SUBJECTS
            ],
        ],
        sibling_checkout_preflight={
            "argv": list(SECURITY_SIBLING_PREFLIGHT_COMMANDS),
            "observed": list(SECURITY_SIBLING_SUBJECTS),
            "result": "all private standalone materializations matched workflow pins and exact trees, and all porcelain outputs were empty",
        },
        network="live read-only package-index advisory lookup allowed after sandbox-only lookup failed",
    ),
)

VERSION_IDENTITY_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "channel": "canonical Python release metadata",
        "value": "RELEASE_VERSION=2026.06rc2; VERSION_DATE=260711; VERSION_LABEL=2026.06rc2(260711); PUBLIC_VERSION_LABEL=2026.06 RC2 (build 260711)",
        "source": "src/metroliza/app/version.py",
        "consumer": "source package, About/release notes, metadata synchronization",
        "verification": "python scripts/sync_release_metadata.py --check",
        "result": "pass at authorized baseline",
        "limitation": "source version does not alone bind a built binary",
        "issue": None,
    },
    {
        "channel": "root compatibility version module",
        "value": "re-exports canonical metroliza.app.version values",
        "source": "VersionDate.py",
        "consumer": "legacy imports and direct Nuitka naming command",
        "verification": "static exact-baseline import bridge inspection",
        "result": "synchronized by indirection",
        "limitation": "Nuitka reads this source label but does not create equivalent artifact provenance",
        "issue": "#920",
    },
    {
        "channel": "runtime/About/startup identity",
        "value": "canonical VERSION_LABEL plus runtime_mode/build provenance log",
        "source": "src/metroliza/app/bootstrap.py",
        "consumer": "GUI title/About and startup diagnostic log",
        "verification": "tests/test_build_provenance.py::test_startup_log_includes_process_build_and_parser_identity",
        "result": "source test passed locally; packaged Windows UI not executed",
        "limitation": "clean frozen GUI display remains unavailable",
        "issue": "#901",
    },
    {
        "channel": "missing/corrupt embedded provenance fallback",
        "value": "load failure returns packager=source, git_sha=unknown, dirty/built_at=None even when runtime_mode reports frozen",
        "source": "src/metroliza/app/build_provenance.py; src/metroliza/app/bootstrap.py",
        "consumer": "frozen startup diagnostics and About/support identity",
        "verification": "exact-baseline control-flow and tests/test_build_provenance.py fallback inspection",
        "result": "normal source absence is accepted; a frozen missing/malformed manifest degrades to source/unknown rather than failing or exposing a distinct invalid-frozen state",
        "limitation": "support/release logs can lose exact artifact identity when frozen provenance is absent or corrupt",
        "issue": "#920/#901",
    },
    {
        "channel": "end-user changelog heading",
        "value": "2026.06 RC2 (build 260711)",
        "source": "CHANGELOG.md",
        "consumer": "release notes",
        "verification": "python scripts/sync_release_metadata.py --check",
        "result": "pass at authorized baseline",
        "limitation": "documentation identity is not artifact identity",
        "issue": None,
    },
    {
        "channel": "Python interpreter selectors",
        "value": "repository .python-version=3.11; all eight CI setup-python selectors=3.11; Windows setup default=3.12; Windows build uses py -3 or PATH python",
        "source": ".python-version; .github/workflows/ci.yml; setup_windows_runtime.ps1; build_windows_exe.ps1",
        "consumer": "developer, hosted CI, Windows runtime and package-build environments",
        "verification": "exact-baseline static selector/caller inventory",
        "result": "major/minor mismatch confirmed; every selector floats the Python patch release",
        "limitation": "Windows fallback paths do not enforce the requested selector and no Windows environment was executed",
        "issue": "#913",
    },
    {
        "channel": "Rust compiler/toolchain selectors",
        "value": "two CI jobs request rustc 1.95.0; no rust-toolchain(.toml); Phase-A host rustc/cargo 1.98.0 (LLVM 22.1.8)",
        "source": ".github/workflows/ci.yml; absent rust-toolchain contract; captured local environment",
        "consumer": "five CI native-wheel builds and local Cargo/package helpers",
        "verification": "exact-baseline tree inventory plus rustc/cargo --version capture",
        "result": "CI selector is exact; local helper toolchain floats with the active host",
        "limitation": "the local 1.98.0 capture is environmental evidence, not repository identity",
        "issue": "#913",
    },
    {
        "channel": "Python project/build metadata",
        "value": "pyproject.toml has tool configuration only; no [project] and no [build-system]",
        "source": "pyproject.toml",
        "consumer": "Python package/build frontend and application distribution metadata",
        "verification": "exact-baseline TOML key inventory",
        "result": "no repository-defined application wheel version or PEP 517 backend",
        "limitation": "requirements and packager scripts do not substitute for installable project metadata",
        "issue": "#920/#913",
    },
    {
        "channel": "packaging-tool and compiler provenance",
        "value": "baseline lower bounds resolved in the capture to Nuitka 4.2, PyInstaller 6.22.2 and maturin 1.15.0; schema 1 records none of those versions",
        "source": "requirements-build.txt; scripts/build_provenance.py; src/metroliza/app/build_provenance.py",
        "consumer": "PyInstaller/Nuitka artifacts and provenance sidecars",
        "verification": "isolated Python 3.11 resolution plus exact schema-field inspection",
        "result": "provenance records packager name and Python patch, not packager/hooks/Rust/Cargo/compiler/OS/runner/dependency-lock identity",
        "limitation": "artifacts with identical current provenance fields can come from materially different toolchains",
        "issue": "#920/#913",
    },
    {
        "channel": "third-party inventory release identity",
        "value": "hard-coded third_party_inventory_260711.json in generator default and PyInstaller data list",
        "source": "scripts/generate_third_party_inventory.py; packaging/pyinstaller_common.py",
        "consumer": "packaged/staged legal inventory and release review",
        "verification": "exact-baseline source inspection; sync_release_metadata.py target inventory",
        "result": "current 260711 token matches VERSION_DATE, but no check couples the filename or inventory release field to canonical metadata",
        "limitation": "a later release can silently generate, embed or stage the prior build-numbered inventory",
        "issue": "#999/#920",
    },
    {
        "channel": "PyInstaller onefile name and provenance",
        "value": "metroliza_P_2026.06rc2(260711)[.exe] with embedded manifest; .provenance.json sidecar only under PowerShell build callers",
        "source": "packaging/metroliza_onefile.spec; packaging/pyinstaller_common.py; scripts/build_provenance.py",
        "consumer": "onefile release artifact",
        "verification": "tests/test_build_provenance.py::test_pyinstaller_build_embeds_manifest_and_selects_exact_artifacts",
        "result": "static/helper tests passed; artifact not built in Phase A; supplied same-release manifests are not bound to current Git/time identity",
        "limitation": "manual Linux packaging-smoke does not invoke build_provenance.py stage; same-release stale manifest #1001; no exact Windows artifact hash or execution",
        "issue": "#1001/#901/#920",
    },
    {
        "channel": "PyInstaller onedir name and provenance",
        "value": "metroliza_P_2026.06rc2(260711)_onedir plus embedded manifest and explicit executable sidecar",
        "source": "packaging/metroliza_onedir.spec; packaging/pyinstaller_common.py; scripts/build_provenance.py",
        "consumer": "onedir release artifact",
        "verification": "tests/test_build_provenance.py::test_pyinstaller_build_embeds_manifest_and_selects_exact_artifacts",
        "result": "static/helper tests passed; artifact not built in Phase A; supplied same-release manifests are not bound to current Git/time identity",
        "limitation": "same-release stale manifest #1001; no exact Windows directory manifest or execution",
        "issue": "#1001/#901/#920",
    },
    {
        "channel": "Nuitka onefile/standalone name",
        "value": "canonical metroliza_N_<release>(<build>).exe when VersionDate.py loads; time-dependent metroliza_N_<yyMMdd>.exe fallback when metadata loading fails",
        "source": "packaging/build_nuitka.ps1",
        "consumer": "Nuitka artifact and notice staging",
        "verification": "static helper inspection and stale-root artifact probe",
        "result": "silent date-based identity fallback and freshness defect #992 confirmed statically",
        "limitation": "metadata failure does not fail closed; no generated/embedded build_provenance.json or artifact provenance sidecar",
        "issue": "#992/#920",
    },
    *(
        {
            "channel": f"Rust crate version: {crate}",
            "value": "0.1.0",
            "source": f"src/metroliza/native/{path}/Cargo.toml",
            "consumer": f"_{module} extension wheel metadata",
            "verification": "cargo metadata --locked --offline and cargo test --locked --offline",
            "result": "pass with explicit Python 3.11",
            "limitation": "crate version is uniform but not the application release label; Windows wheel not built",
            "issue": "#913/#901",
        }
        for crate, path, module in (
            ("chart", "chart_renderer", "metroliza_chart_native"),
            ("CMM parser", "cmm_parser", "metroliza_cmm_native"),
            (
                "comparison statistics",
                "comparison_stats_bootstrap",
                "metroliza_comparison_stats_native",
            ),
            ("distribution fit", "distribution_fit_ad", "metroliza_distribution_fit_native"),
            ("group statistics", "group_stats_coercion", "metroliza_group_stats_native"),
        )
    ),
)

PLATFORM_FAILURE_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "id": "PF-01",
        "platform_path": "Linux source happy path",
        "scenario": "receipt-bound pre-publication non-self tests/static/parser/metadata/security gates",
        "command": "receipt-retained portable logical child argv/environment/cwd are recorded in the per-invocation receipt table; parser operands execute through unretained role-checked held descriptor aliases; full packet pytest and combined coverage remain external post-publication parking gates",
        "exit_code": 0,
        "result": "pass: receipt-bound non-self pytest, static, parser, metadata, hygiene and security gates; external full-packet pytest and combined coverage are not claimed by this self-referential artifact",
        "evidence_class": "actual local Linux source validation",
        "limitation": "not packaged or Windows evidence",
        "owner_or_gate": "Phase-A local gate",
    },
    {
        "id": "PF-02",
        "platform_path": "Linux isolated dependency resolution",
        "scenario": "baseline/proposal Python 3.11 family workflows",
        "command": "exact commands recorded under pr_973.families",
        "exit_code": 1,
        "result": "mixed: many family commands passed, but required Ruff and focused policy commands failed; overall PR #973 remains blocked",
        "evidence_class": "actual per-family rows plus observational aggregate; heterogeneous outcomes are not flattened",
        "limitation": "fresh highest resolution makes 29/35 proposals no-ops; do not sum heterogeneous rows as one suite",
        "owner_or_gate": "#913 and downstream family waves",
    },
    {
        "id": "PF-03",
        "platform_path": "Windows source/core",
        "scenario": "exact-base hosted windows-core-smoke",
        "command": "existing run 33151703847 inspected read-only; workflow exact steps retained",
        "exit_code": 0,
        "result": "success",
        "evidence_class": "existing hosted observation; not dispatched by Phase A",
        "limitation": "does not build or run a packaged executable",
        "owner_or_gate": "#914 / Phase B exact-head CI",
    },
    {
        "id": "PF-04",
        "platform_path": "Windows packaged happy path",
        "scenario": "clean-machine onefile/onedir startup, Qt/OCR/native DLL/resource flows",
        "command": "unavailable: no authorized clean Windows package build/execution in Phase A",
        "exit_code": None,
        "result": "not executed",
        "evidence_class": "unavailable/manual",
        "limitation": "source/helper and resolver evidence cannot substitute",
        "owner_or_gate": "#901 / release acceptance",
    },
    {
        "id": "PF-05",
        "platform_path": "network/cold dependency cache",
        "scenario": "offline fresh install/compile without a complete wheelhouse",
        "command": "uv pip compile --offline with isolated UV cache and exact Python/platform selectors",
        "exit_code": 1,
        "result": "failed because required artifacts were absent from cache",
        "evidence_class": "actual",
        "limitation": "proves no self-contained wheelhouse; not an online resolver failure",
        "owner_or_gate": "#913 reproducible-environment gate",
    },
    {
        "id": "PF-06",
        "platform_path": "warm cache",
        "scenario": "restored download cache with dependency-file key drift",
        "command": "static lossless setup-python cache inventory plus NC-warm-cache-only",
        "exit_code": 0,
        "result": "pip still resolves; stale download cache efficiency risk only",
        "evidence_class": "static plus deterministic control",
        "limitation": "no wrong installed version reproduced",
        "owner_or_gate": "#914",
    },
    {
        "id": "PF-07",
        "platform_path": "compiler/tool absent",
        "scenario": "required Cargo/compiler versus optional dependency",
        "command": "NC-missing-tool-optional-dependency; packaging scripts inspected",
        "exit_code": 0,
        "result": "pytest harness passed while asserting the required-tool exception and optional-capability diagnostic",
        "evidence_class": "synthetic negative control",
        "limitation": "Windows auto-install/UAC path not executed",
        "owner_or_gate": "#913/#901",
    },
    {
        "id": "PF-08",
        "platform_path": "spaces/non-ASCII/long path",
        "scenario": "sanitized nested output round trip",
        "command": "NC-path-permission-boundary",
        "exit_code": 0,
        "result": "passed on POSIX",
        "evidence_class": "actual sanitized control",
        "limitation": "Windows MAX_PATH and shell quoting not executed",
        "owner_or_gate": "#901",
    },
    {
        "id": "PF-09",
        "platform_path": "read-only/ACL output boundary",
        "scenario": "mode-0555 parent rejects output",
        "command": "NC-path-permission-boundary",
        "exit_code": 0,
        "result": "negative control detected read-only target",
        "evidence_class": "actual POSIX control",
        "limitation": "Windows ACL/UAC behavior not executed",
        "owner_or_gate": "#901",
    },
    {
        "id": "PF-10",
        "platform_path": "antivirus/indexer file lock",
        "scenario": "locked executable/model/sidecar during replace or cleanup",
        "command": "unavailable: no Windows lock-injection environment",
        "exit_code": None,
        "result": "not executed",
        "evidence_class": "unsupported in Phase A",
        "limitation": "cleanup/retry behavior unproven",
        "owner_or_gate": "#901 clean-Windows gate",
    },
    {
        "id": "PF-11",
        "platform_path": "interruption/cancellation",
        "scenario": "build interrupted after partial output",
        "command": "NC-stale-partial-artifact",
        "exit_code": 0,
        "result": "consumer-side stale/partial rejection passed",
        "evidence_class": "deterministic synthetic control",
        "limitation": "real PowerShell/Cargo/PyInstaller process interruption cleanup not executed",
        "owner_or_gate": "#901/#920",
    },
    {
        "id": "PF-12",
        "platform_path": "zero-exit/no output and stale output",
        "scenario": "current build attempt produces no fresh artifact",
        "command": "NC-zero-exit-no-artifact and NC-stale-partial-artifact",
        "exit_code": 0,
        "result": "negative controls detected missing/stale/undersized outputs",
        "evidence_class": "production-bound deterministic controls",
        "limitation": "Nuitka helper still has confirmed stale-root defect #992",
        "owner_or_gate": "#992/#920",
    },
    {
        "id": "PF-13",
        "platform_path": "manual CI lanes",
        "scenario": "packaging smoke and Windows startup workflow_dispatch inputs",
        "command": "not run or rerun by Phase A",
        "exit_code": None,
        "result": "not selected on PR/push; blocking only when explicitly selected after successful needs",
        "evidence_class": "static exact workflow semantics",
        "limitation": "no hosted package/startup result",
        "owner_or_gate": "#914 / authorized Phase B CI",
    },
    {
        "id": "PF-14",
        "platform_path": "hosted test process crash",
        "scenario": "exact-base industrial analytics coverage shard SIGSEGV",
        "command": "existing run 33151703847 logs inspected read-only",
        "exit_code": 139,
        "result": "confirmed process crash; bounded root cause not reproduced locally",
        "evidence_class": "existing hosted observation",
        "limitation": "no crash artifact uploaded; hypothesis remains open",
        "owner_or_gate": "#998",
    },
)

EXTERNAL_EXECUTOR_INVENTORY: tuple[dict[str, Any], ...] = (
    {
        "id": "EXEC-PIP",
        "executor": "Python package installer",
        "argv_contracts": [
            {
                "argv": "python -m pip install --upgrade pip",
                "callers": [".github/workflows/ci.yml", "setup/build PowerShell helpers"],
            },
            {
                "argv": "python -m pip install -r requirements.txt",
                "callers": [".github/workflows/ci.yml", "setup/build PowerShell helpers"],
            },
            {
                "argv": "python -m pip install -r requirements-anomaly.txt",
                "callers": [
                    "src/metroliza/industrial/anomaly/optional_dependencies.py user recommendation"
                ],
            },
            {
                "argv": "python -m pip install -r requirements-build.txt",
                "callers": [".github/workflows/ci.yml", "setup/build PowerShell helpers"],
            },
            {
                "argv": "python -m pip install -r requirements-dev.txt",
                "callers": [".github/workflows/ci.yml", "setup_windows_runtime.ps1 -WithDev"],
            },
            {
                "argv": "python -m pip install -r requirements-ocr.txt",
                "callers": [".github/workflows/ci.yml", "setup/build PowerShell helpers"],
            },
        ],
        "contract": "creates source/test/build environments from lower-bound/VCS declarations; resolution is not immutable",
    },
    {
        "id": "EXEC-MATURIN",
        "executor": "locked native wheel build",
        "argv_contracts": [
            {
                "argv": "python -m maturin build --locked --manifest-path <one-of-five-Cargo.toml> --release --out dist/native",
                "callers": [".github/workflows/ci.yml"],
            },
            {
                "argv": "python -m maturin build --locked --release --manifest-path <one-of-five-Cargo.toml>",
                "callers": ["packaging/build_native_and_package.ps1"],
            },
        ],
        "contract": "builds one of five locked native wheels; caller must install/import/verify; CI uploads no wheel artifact",
    },
    {
        "id": "EXEC-PYINSTALLER",
        "executor": "PyInstaller spec execution",
        "argv_contracts": [
            {
                "argv": "pyinstaller packaging/metroliza_onefile.spec",
                "callers": [".github/workflows/ci.yml packaging-smoke"],
            },
            {
                "argv": "python -m PyInstaller --noconfirm packaging/metroliza_onefile.spec",
                "callers": ["build_windows_exe.ps1", "packaging/build_native_and_package.ps1"],
            },
            {
                "argv": "python -m PyInstaller --noconfirm packaging/metroliza_onedir.spec",
                "callers": ["build_windows_exe.ps1", "packaging/build_native_and_package.ps1"],
            },
        ],
        "contract": "executes exact spec; caller is responsible for freshness, notice and provenance acceptance",
    },
    {
        "id": "EXEC-NUITKA",
        "executor": "Nuitka application compilation",
        "argv_contracts": [
            {
                "argv": "python -m nuitka packaging/metroliza_package_entry.py --onefile --output-filename=<resolved name> --report=nuitka-build-report.xml <literal console/plugin/module/data/compiler/jobs args retained under packaging.nuitka>",
                "callers": ["packaging/build_nuitka.ps1"],
            },
            {
                "argv": "python -m nuitka packaging/metroliza_package_entry.py --standalone --output-filename=<resolved name> --report=nuitka-build-report.xml <literal console/plugin/module/data/compiler/jobs args retained under packaging.nuitka>",
                "callers": ["packaging/build_nuitka.ps1"],
            },
        ],
        "contract": "runs from repository root with Nuitka default output placement; PowerShell selects --onefile/--standalone plus GCC/Clang and explicit resources/modules, then validates the report and stages notices; stale-root acceptance defect #992 remains",
    },
)

SECONDARY_PATH_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "role": "control-plane inputs",
        "evidence_refs": ["EV-SCOPE-CONTRACT", "DP-HISTORY-FULL", "DP-HISTORY-SHALLOW"],
        "execution_status": "read at exact baseline; validator/tests executed locally",
        "finding_or_residual": "#991 / Phase-B ledger gate",
        "paths": [
            "docs/quality/bug_sweep/README.md",
            "docs/quality/bug_sweep/coverage.json",
            "scripts/quality/validate_bug_sweep_coverage.py",
            "tests/test_bug_sweep_coverage.py",
        ],
    },
    {
        "role": "release/version/provenance source and consumers",
        "evidence_refs": ["EV-VERSION-COMPAT", "EV-PACKAGING-PROVENANCE", "EV-CI-STATIC-COMMANDS"],
        "execution_status": "static exact-baseline inventory and metadata/provenance tests",
        "finding_or_residual": "#920/#901 where packaged identity remains unavailable",
        "paths": [
            "VersionDate.py",
            "README.md",
            "docs/release_checks/release_status.md",
            "src/metroliza/__init__.py",
            "src/metroliza/app/bootstrap.py",
        ],
    },
    {
        "role": "Windows OCR diagnostic caller context",
        "evidence_refs": ["EV-BUILD-COMMANDS", "EV-CI-WINDOWS-LANES", "EV-PLATFORM"],
        "execution_status": "static exact-baseline caller inventory; Windows execution unavailable",
        "finding_or_residual": "HD-976-F016/#1002; HD-976-R001/#901",
        "paths": [
            "diagnose_windows_ocr.bat",
            "diagnose_windows_ocr.ps1",
            "scripts/diagnose_header_ocr_metadata.py",
        ],
    },
    {
        "role": "Plotly runtime and companion-notice inputs",
        "evidence_refs": ["EV-PACKAGING-EXPLICIT-ASSETS", "EV-PACKAGING-NOTICES"],
        "execution_status": "runtime asset hash-bound; expected companion file absent",
        "finding_or_residual": "HD-976-F008/#994",
        "paths": [
            "src/metroliza/resources/html_dashboard_assets/README.md",
            "src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js",
            "src/metroliza/resources/html_dashboard_assets/plotly.min.js.LICENSE.txt",
        ],
    },
    {
        "role": "RapidOCR vendored model inputs",
        "evidence_refs": ["EV-PACKAGING-OCR-MODELS", "DP-OCR-INFERENCE", "DP-OCR-HASH-DELETE"],
        "execution_status": "tracked hashes and deletion control executed; frozen Windows load unavailable",
        "finding_or_residual": "HD-976-R001/#901",
        "paths": [
            "src/metroliza/resources/ocr_models/rapidocr/README.md",
            "src/metroliza/resources/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx",
            "src/metroliza/resources/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "src/metroliza/resources/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx",
        ],
    },
    {
        "role": "generated PyInstaller provenance contract path",
        "evidence_refs": ["EV-PACKAGING-PROVENANCE"],
        "execution_status": "generated path; no Phase-A release artifact",
        "finding_or_residual": "HD-976-R004/#920",
        "paths": ["build/provenance/build_provenance.json"],
    },
    {
        "role": "online manual inputs outside the primary representative PDF",
        "evidence_refs": ["EV-PACKAGING-MANUALS"],
        "execution_status": "static inventory; offline packaged availability not executed",
        "finding_or_residual": "HD-976-R003/#955",
        "paths": [
            "docs/user_manual/README.md",
            "docs/user_manual/characteristic_name_matching.md",
            "docs/user_manual/csv_summary.md",
            "docs/user_manual/dashboard_visuals.md",
            "docs/user_manual/export_filtering.md",
            "docs/user_manual/export_grouping.md",
            "docs/user_manual/export_overview.md",
            "docs/user_manual/group_analysis/README.md",
            "docs/user_manual/group_analysis/user_manual.md",
            "docs/user_manual/help_startup_and_license.md",
            "docs/user_manual/industrial_data.md",
            "docs/user_manual/main_window.md",
            "docs/user_manual/modify_database.md",
            "docs/user_manual/parser_profiles.md",
            "docs/user_manual/parsing.md",
            "docs/user_manual/realtime_industrial_monitoring.md",
        ],
    },
    {
        "role": "direct runtime resource locators and consumers",
        "evidence_refs": [
            "EV-PACKAGING-EXPLICIT-ASSETS",
            "EV-PACKAGING-OCR-MODELS",
            "EV-PACKAGING-HIDDEN-IMPORTS",
            "NC-repository-root-only-import",
        ],
        "execution_status": "source/helper tests executed; frozen discovery unavailable",
        "finding_or_residual": "HD-976-R001/R003/R005",
        "paths": [
            "src/metroliza/charts/dashboard_visual_options.py",
            "src/metroliza/charts/export_html_dashboard.py",
            "src/metroliza/exporting/export_data_thread.py",
            "src/metroliza/industrial/industrial_analytics_dashboard.py",
            "src/metroliza/parsing/header_ocr_backend.py",
            "src/metroliza/ui/help_menu.py",
            "modules/help_menu.py",
            "src/metroliza/app/license_bootstrap.py",
            "src/metroliza/app/startup_splash.py",
            "src/metroliza/ui/main_window.py",
            "src/metroliza/ui/about_window.py",
            "src/metroliza/ui/worker_progress_dialog.py",
            "modules/base64_encoded_files.py",
        ],
    },
    {
        "role": "parser-profile discovery/self-service consumers",
        "evidence_refs": ["EV-PACKAGING-PARSER-PROFILES", "DP-PATH-BOUNDARIES"],
        "execution_status": "source tests executed; explicit --sample parser CLI crashed before execution; installed/frozen discovery unavailable",
        "finding_or_residual": "HD-976-F018/#1004; HD-976-R005/#901/#984",
        "paths": [
            "src/metroliza/parsing/parser_plugin_paths.py",
            "src/metroliza/parsing/declarative_parser_profiles.py",
            "src/metroliza/parsing/report_parser_factory.py",
            "src/metroliza/parsing/parser_profile_handoff.py",
            "src/metroliza/parsing/parser_plugin_contracts.py",
            "src/metroliza/parsing/parser_plugin_validation.py",
            "src/metroliza/parsing/parser_plugin_repair_loop.py",
            "src/metroliza/ui/parser_plugin_wizard.py",
            "scripts/parser_plugin_self_service.py",
            "scripts/validate_parser_plugins.py",
        ],
    },
    {
        "role": "native implementation and bridge seam",
        "evidence_refs": [
            "EV-RUST-MANIFEST-LOCK",
            "DP-CARGO-TESTS",
            "NC-misleading-native-fallback",
        ],
        "execution_status": "locked Linux Cargo tests and bridge tests; Windows wheel/ABI unavailable",
        "finding_or_residual": "HD-976-F007/R001",
        "paths": [
            "src/metroliza/native/chart_renderer/src/lib.rs",
            "src/metroliza/native/cmm_parser/src/lib.rs",
            "src/metroliza/native/comparison_stats_bootstrap/src/lib.rs",
            "src/metroliza/native/distribution_fit_ad/src/lib.rs",
            "src/metroliza/native/group_stats_coercion/src/lib.rs",
            "src/metroliza/charts/chart_renderer.py",
            "src/metroliza/native_bridges/cmm_native_parser.py",
            "src/metroliza/native_bridges/group_stats_native.py",
            "src/metroliza/native_bridges/comparison_stats_native.py",
            "src/metroliza/native_bridges/distribution_fit_native.py",
            "src/metroliza/native_bridges/distribution_fit_candidate_native.py",
            "modules/chart_renderer.py",
            "modules/cmm_native_parser.py",
            "modules/group_stats_native.py",
            "modules/comparison_stats_native.py",
            "modules/distribution_fit_native.py",
        ],
    },
    {
        "role": "exact narrowed-mypy source inputs",
        "evidence_refs": ["DP-PR973-POLICY"],
        "execution_status": "exact proposal mypy command executed successfully",
        "finding_or_residual": "#913/#996 compatibility evidence",
        "paths": [
            "src/metroliza/integrations/google_credentials_hygiene.py",
            "src/metroliza/industrial/anomaly/contracts.py",
            "src/metroliza/industrial/realtime/stream_contracts.py",
        ],
    },
    {
        "role": "exact tests named by captured dependency/package/native commands",
        "evidence_refs": ["DP-PR973-FAMILY", "DP-PR973-QT", "DP-PR973-POLICY", "DP-CARGO-TESTS"],
        "execution_status": "executed in recorded focused probes and covered by receipt-bound pre-publication application pytest",
        "finding_or_residual": "family-specific #913/#901/#920 and downstream waves",
        "paths": [
            "tests/test_google_drive_credentials_hygiene.py",
            "tests/test_google_drive_export.py",
            "tests/test_matplotlib_runtime.py",
            "tests/test_matplotlib_distribution_geometry.py",
            "tests/test_matplotlib_iqr_trend_geometry.py",
            "tests/test_distribution_shape_analysis.py",
            "tests/test_export_workbook_output.py",
            "tests/test_export_sheet_writer.py",
            "tests/test_xlsx_chart_utils.py",
            "tests/test_anomaly_isolation_forest.py",
            "tests/test_anomaly_online_drift.py",
            "tests/test_realtime_detector_consumer.py",
            "tests/test_realtime_end_to_end_replay.py",
            "tests/test_qt_runtime_validation.py",
            "tests/test_pyqt_ui_geometry_audit.py",
            "tests/test_packaged_pdf_parser_validation.py",
            "tests/test_pdf_parser_smoke.py",
            "tests/test_header_ocr_backend.py",
            "tests/test_pymupdf_backend_resolution.py",
            "tests/test_build_native_and_package_helper.py",
            "tests/test_packaging_spec_hiddenimports.py",
            "tests/test_build_provenance.py",
            "tests/test_stage_release_notices.py",
            "tests/test_ci_policy_sync.py",
            "tests/test_requirements_hygiene.py",
            "tests/test_security_audit.py",
            "tests/test_native_chart_renderer_smoke.py",
            "tests/test_chart_render_spec.py",
            "tests/test_native_chart_parity_fixtures.py",
            "tests/test_export_data_thread_group_analysis.py",
            "tests/test_cmm_parser_parity.py",
        ],
    },
    {
        "role": "directly relevant regression tests outside focused capture",
        "evidence_refs": ["EV-SECONDARY-REGRESSION-SURFACES"],
        "execution_status": "covered by receipt-bound pre-publication application pytest; no narrower duplicate invocation retained",
        "finding_or_residual": "availability evidence only",
        "paths": [
            "tests/test_release_metadata_sync.py",
            "tests/test_release_hygiene.py",
            "tests/test_third_party_inventory.py",
            "tests/test_third_party_notice_inventory.py",
            "tests/test_header_ocr_diagnostics_script.py",
            "tests/test_help_menu.py",
            "tests/test_export_html_dashboard.py",
            "tests/test_industrial_analytics_dashboard.py",
            "tests/test_ui_revamp_foundation_layout.py",
            "tests/test_about_window_gif_lifetime.py",
            "tests/test_declarative_parser_profiles.py",
            "tests/test_parser_plugin_self_service_cli.py",
            "tests/test_report_parser_factory.py",
            "tests/test_parser_plugin_wizard.py",
            "tests/test_parser_plugin_scripts.py",
        ],
    },
)


class AuditError(RuntimeError):
    """Raised when build-delivery evidence cannot be proven."""


MAX_BOUND_FILE_BYTES = 128 * 1024 * 1024
GIT_CONFIG_OVERRIDES: tuple[str, ...] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.useBuiltinFSMonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.fileMode=true",
    "-c",
    "core.ignoreStat=false",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.excludesFile=/dev/null",
    "-c",
    "core.sparseCheckout=false",
    "-c",
    "core.trustCtime=true",
    "-c",
    "core.checkStat=default",
)


def _git_environment() -> dict[str, str]:
    """Return a minimal Git environment with no ambient path, loader or repo selectors."""
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def _read_descriptor_bytes(
    descriptor: int,
    *,
    maximum_bytes: int = MAX_BOUND_FILE_BYTES,
) -> bytes:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise AuditError("descriptor byte source is not a regular file")
    if metadata.st_size < 0 or metadata.st_size > maximum_bytes:
        raise AuditError(f"descriptor byte source exceeds the {maximum_bytes}-byte safety bound")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum_bytes:
            raise AuditError(
                f"descriptor byte source exceeded the {maximum_bytes}-byte safety bound"
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if len(content) != metadata.st_size:
        raise AuditError("descriptor byte source size changed during bounded read")
    return content


@contextmanager
def _bound_executable(argv_path: str) -> Iterable[tuple[int, dict[str, Any]]]:
    specs = {str(row["argv_path"]): row for row in BOUND_EXECUTABLES}
    expected = specs.get(argv_path)
    if expected is None:
        raise AuditError(f"unbound validation executable: {argv_path}")
    lexical = Path(argv_path)
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise AuditError(f"bound executable is unavailable: {argv_path}") from exc
    if str(resolved) != expected["resolved_path"]:
        raise AuditError(f"bound executable target drifted: {argv_path}")
    descriptor = os.open(
        resolved,
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = _observe_bound_executable_descriptor(
            descriptor,
            argv_path=argv_path,
            resolved_path=str(resolved),
        )
        _require_exact_json_value(observed, expected, label=f"bound executable {argv_path}")
        yield descriptor, observed
    finally:
        os.close(descriptor)


def _observe_bound_executable_descriptor(
    descriptor: int,
    *,
    argv_path: str,
    resolved_path: str,
) -> dict[str, Any]:
    before = os.fstat(descriptor)
    content = _read_stable_descriptor(descriptor, label=f"bound executable {argv_path}")
    after = os.fstat(descriptor)
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise AuditError(f"bound executable changed during observation: {argv_path}")
    if not stat.S_ISREG(after.st_mode) or after.st_size != len(content):
        raise AuditError(f"bound executable is not a stable regular file: {argv_path}")
    if stat.S_IMODE(after.st_mode) & 0o111 == 0:
        raise AuditError(f"bound executable is not executable: {argv_path}")
    return {
        "argv_path": argv_path,
        "resolved_path": resolved_path,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "file_type": "regular",
        "mode": f"{stat.S_IMODE(after.st_mode):04o}",
        "execution_binding": "held descriptor supplied as subprocess executable",
    }


def _execution_tool_refs() -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for row in BOUND_EXECUTABLES:
        with _bound_executable(str(row["argv_path"])) as (_descriptor, observed):
            refs.append(observed)
    return refs


def _run_git_completed(
    arguments: Sequence[str],
    *,
    cwd: Path = ROOT,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    with _bound_executable("/usr/bin/git") as (descriptor, _observed):
        return subprocess.run(
            ["/usr/bin/git", *GIT_CONFIG_OVERRIDES, *arguments],
            executable=f"/proc/self/fd/{descriptor}",
            cwd=cwd,
            check=False,
            capture_output=True,
            input=input_bytes,
            env=_git_environment(),
            pass_fds=(descriptor,),
            timeout=30,
        )


def _run_git(arguments: Sequence[str], *, cwd: Path = ROOT) -> bytes:
    completed = _run_git_completed(arguments, cwd=cwd)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AuditError(f"git {' '.join(arguments)} failed: {stderr or 'unknown error'}")
    return completed.stdout


def _read_at_baseline(path: str) -> bytes:
    return _run_git(["show", f"{BASELINE_SHA}:{path}"])


def _read_at_commit(commit: str, path: str) -> bytes:
    return _run_git(["show", f"{commit}:{path}"])


def _require_commit_snapshot(
    *, commit: str, tree: str, parent: str | None, check_parent: bool = True
) -> None:
    require_commit_available(ROOT, commit)
    actual_tree = _run_git(["rev-parse", f"{commit}^{{tree}}"]).decode().strip()
    if actual_tree != tree:
        raise AuditError(f"exact input tree mismatch for {commit}: {actual_tree} != {tree}")
    if check_parent:
        parents = _run_git(["rev-list", "--parents", "-n", "1", commit]).decode().split()
        actual_parents = parents[1:]
        expected_parents = [] if parent is None else [parent]
        if actual_parents != expected_parents:
            raise AuditError(
                f"exact input parent mismatch for {commit}: {actual_parents} != {expected_parents}"
            )


def _changed_paths(parent: str, head: str) -> list[str]:
    raw = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", parent, head])
    return sorted(path.decode("utf-8") for path in raw.split(b"\0") if path)


def _action_ref_counts(content: bytes) -> Counter[tuple[str, str]]:
    text = content.decode("utf-8")
    return Counter(
        (match.group("action"), match.group("sha"))
        for match in re.finditer(
            r"^\s*uses:\s+(?P<action>actions/(?:checkout|setup-python|upload-artifact))@"
            r"(?P<sha>[0-9a-f]{40})(?:\s|$)",
            text,
            flags=re.MULTILINE,
        )
    )


def _require_pr972_matrix() -> list[dict[str, Any]]:
    parent_counts = _action_ref_counts(
        _read_at_commit(PR_INPUT_PARENT_SHA, ".github/workflows/ci.yml")
    )
    head_counts = _action_ref_counts(_read_at_commit(PR972_SHA, ".github/workflows/ci.yml"))
    matrix_by_action = {row["action"]: row for row in PR972_MATRIX}
    if len(matrix_by_action) != len(PR972_MATRIX):
        raise AuditError("PR #972 matrix contains duplicate Action families")
    changed_actions = {
        action
        for action in {name for name, _sha in parent_counts | head_counts}
        if Counter({sha: count for (name, sha), count in parent_counts.items() if name == action})
        != Counter({sha: count for (name, sha), count in head_counts.items() if name == action})
    }
    if changed_actions != set(matrix_by_action):
        raise AuditError("PR #972 Action matrix does not match the exact workflow transition")

    transitions: list[dict[str, Any]] = []
    for action, row in sorted(matrix_by_action.items()):
        parent_refs = {sha: count for (name, sha), count in parent_counts.items() if name == action}
        head_refs = {sha: count for (name, sha), count in head_counts.items() if name == action}
        if set(head_refs) != {row["sha"]} or len(parent_refs) != 1:
            raise AuditError(f"PR #972 declared SHA does not match exact {action} occurrences")
        transitions.append(
            {
                "action": action,
                "parent_refs": parent_refs,
                "head_refs": head_refs,
                "occurrence_count": sum(head_refs.values()),
            }
        )
    return transitions


def _require_pr973_declaration_edits() -> dict[str, dict[str, list[str]]]:
    expected_by_path: dict[str, dict[str, list[str]]] = {}
    for row in PR973_DECLARATION_EDITS:
        expected = expected_by_path.setdefault(row["path"], {"removed": [], "added": []})
        expected["removed"].append(row["old"])
        expected["added"].append(row["new"])

    derived: dict[str, dict[str, list[str]]] = {}
    for path, expected in sorted(expected_by_path.items()):
        parent_lines = Counter(
            line.strip()
            for line in _read_at_commit(PR_INPUT_PARENT_SHA, path).decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        head_lines = Counter(
            line.strip()
            for line in _read_at_commit(PR973_SHA, path).decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        actual = {
            "removed": sorted((parent_lines - head_lines).elements()),
            "added": sorted((head_lines - parent_lines).elements()),
        }
        normalized_expected = {
            "removed": sorted(expected["removed"]),
            "added": sorted(expected["added"]),
        }
        if actual != normalized_expected:
            raise AuditError(f"PR #973 declaration matrix drifted for {path}")
        derived[path] = actual
    return derived


def require_exact_pr_inputs() -> dict[str, Any]:
    _require_commit_snapshot(
        commit=PR_INPUT_PARENT_SHA,
        tree=PR_INPUT_PARENT_TREE,
        parent=None,
        check_parent=False,
    )
    _require_commit_snapshot(commit=PR972_SHA, tree=PR972_TREE, parent=PR_INPUT_PARENT_SHA)
    _require_commit_snapshot(commit=PR973_SHA, tree=PR973_TREE, parent=PR_INPUT_PARENT_SHA)
    if _changed_paths(PR_INPUT_PARENT_SHA, PR972_SHA) != [".github/workflows/ci.yml"]:
        raise AuditError("PR #972 exact changed-path set drifted")
    expected_pr973_paths = sorted({row["path"] for row in PR973_DECLARATION_EDITS})
    if _changed_paths(PR_INPUT_PARENT_SHA, PR973_SHA) != expected_pr973_paths:
        raise AuditError("PR #973 exact changed-path set drifted")
    return {
        "common_parent": {"commit": PR_INPUT_PARENT_SHA, "tree": PR_INPUT_PARENT_TREE},
        "pr_972_action_transitions": _require_pr972_matrix(),
        "pr_973_declaration_transitions": _require_pr973_declaration_edits(),
    }


def _git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _read_rooted_regular_file(root: Path, relative_path: str, *, label: str) -> tuple[bytes, int]:
    root_fd, root_identity = _open_publication_root(root)
    descriptor: int | None = None
    verification_fd: int | None = None
    try:
        descriptor = _openat2_beneath(
            root_fd,
            relative_path,
            flags=(
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuditError(f"{label} is not a regular file")
        content = _read_stable_descriptor(descriptor, label=label)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise AuditError(f"{label} identity or metadata changed during rooted read")
        verification_fd = _openat2_beneath(
            root_fd,
            relative_path,
            flags=(
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        verification_metadata = os.fstat(verification_fd)
        verification_content = _read_stable_descriptor(
            verification_fd,
            label=f"{label} final path binding",
        )
        if content != verification_content or any(
            getattr(after, field) != getattr(verification_metadata, field)
            for field in stable_fields
        ):
            raise AuditError(f"{label} final rooted entry changed during read")
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError(f"{label} root identity changed during rooted read")
        return content, stat.S_IMODE(after.st_mode)
    finally:
        _close_descriptors(verification_fd, descriptor, root_fd)


def _implementation_refs_at_root(root: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path in (
        "scripts/quality/audit_build_delivery.py",
        "tests/test_build_delivery_audit.py",
    ):
        content, mode = _read_rooted_regular_file(
            root,
            path,
            label=f"Phase-A implementation {path}",
        )
        if mode != 0o644:
            raise AuditError(f"Phase-A implementation mode is not exact 0644: {path}")
        refs.append(
            {
                "path": path,
                "file_type": "regular",
                "mode": f"{mode:04o}",
                "git_blob_sha1": _git_blob_sha1(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "binding": "content-addressed Phase-A harness; parked commit binding is a parking gate",
            }
        )
    return refs


def _audit_implementation_refs() -> list[dict[str, Any]]:
    return _implementation_refs_at_root(ROOT)


def _baseline_blob_refs(paths: Sequence[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path in paths:
        content = _read_at_baseline(path)
        refs.append(
            {
                "path": path,
                "commit": BASELINE_SHA,
                "tree": BASELINE_TREE,
                "git_blob_sha1": _run_git(["rev-parse", f"{BASELINE_SHA}:{path}"]).decode().strip(),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return refs


def _baseline_paths() -> list[str]:
    output = _run_git(["ls-tree", "-r", "-z", "--name-only", "--full-tree", BASELINE_SHA])
    return sorted(item.decode("utf-8", errors="strict") for item in output.split(b"\0") if item)


def _baseline_ledger() -> dict[str, Any]:
    relative_path = LEDGER_PATH.relative_to(ROOT).as_posix()
    return json.loads(_read_at_baseline(relative_path).decode("utf-8"))


def _local_git_config_keys(config_content: bytes, *, label: str) -> list[str]:
    completed = _run_git_completed(
        ["config", "--file", "-", "--no-includes", "--null", "--name-only", "--list"],
        cwd=Path(CAPTURE_TEMP_ROOT),
        input_bytes=config_content,
    )
    if completed.returncode != 0 or completed.stderr != b"":
        raise AuditError(f"{label} local Git configuration could not be inspected")
    return [
        item.decode("utf-8", errors="strict").lower()
        for item in completed.stdout.split(b"\0")
        if item
    ]


def _require_safe_local_git_key_values(
    config_content: bytes,
    keys: Sequence[str],
    *,
    label: str,
) -> None:
    unsafe_exact = {
        "core.attributesfile",
        "core.excludesfile",
        "core.fsmonitor",
        "core.hookspath",
        "core.ignorecase",
        "core.ignorestat",
        "core.sparsecheckout",
        "core.sparsecheckoutcone",
        "core.symlinks",
        "core.untrackedcache",
        "core.usebuiltinfsmonitor",
        "core.worktree",
        "extensions.worktreeconfig",
        "interactive.difffilter",
    }
    unsafe_prefixes = ("include.", "includeif.", "filter.", "diff.")
    unsafe = sorted(
        key
        for key in keys
        if key in unsafe_exact or any(key.startswith(prefix) for prefix in unsafe_prefixes)
    )
    if unsafe:
        raise AuditError(f"{label} has unsafe local Git configuration: {', '.join(unsafe)}")
    filemode = _run_git_completed(
        ["config", "--file", "-", "--no-includes", "--get-all", "core.filemode"],
        cwd=Path(CAPTURE_TEMP_ROOT),
        input_bytes=config_content,
    )
    if filemode.returncode != 0 or filemode.stderr != b"" or filemode.stdout != b"true\n":
        raise AuditError(f"{label} must retain exact core.fileMode=true semantics")


def _require_safe_local_git_auxiliary_paths(repo: Path, *, label: str) -> None:
    for relative in (".git/info/exclude", ".git/info/attributes"):
        lexical = repo / relative
        if not lexical.exists() and not lexical.is_symlink():
            continue
        content, mode = _read_rooted_regular_file(
            repo,
            relative,
            label=f"{label} {relative}",
        )
        if mode not in {0o444, 0o644}:
            raise AuditError(f"{label} {relative} mode is not an accepted exact mode")
        active_lines = [
            line
            for line in content.decode("utf-8", errors="strict").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if active_lines:
            raise AuditError(f"{label} contains active repository-local excludes/attributes")
    for relative in (
        ".git/config.worktree",
        ".git/info/sparse-checkout",
        ".git/info/grafts",
        ".git/objects/info/alternates",
    ):
        lexical = repo / relative
        if lexical.exists() or lexical.is_symlink():
            raise AuditError(f"{label} contains unsafe repository-local control: {relative}")


def _require_safe_local_git_config(repo: Path, *, label: str) -> None:
    """Reject repository-local knobs that can redirect or execute Git plumbing."""
    config_content, config_mode = _read_rooted_regular_file(
        repo,
        ".git/config",
        label=f"{label} local Git config",
    )
    if config_mode not in {0o444, 0o644}:
        raise AuditError(f"{label} local Git config mode is not an accepted exact mode")
    keys = _local_git_config_keys(config_content, label=label)
    _require_safe_local_git_key_values(config_content, keys, label=label)
    config_after, mode_after = _read_rooted_regular_file(
        repo,
        ".git/config",
        label=f"{label} local Git config",
    )
    if config_after != config_content or mode_after != config_mode:
        raise AuditError(f"{label} local Git configuration changed during inspection")
    _require_safe_local_git_auxiliary_paths(repo, label=label)


def _require_rooted_dot_git_directory(repo: Path) -> Path:
    resolved_repo = repo.resolve(strict=True)
    dot_git = resolved_repo / ".git"
    if not dot_git.is_dir() or dot_git.is_symlink():
        raise AuditError("execution checkout must use its rooted .git directory")
    return dot_git.resolve(strict=True)


def _require_git_repository_binding(repo: Path) -> None:
    resolved_repo = repo.resolve(strict=True)
    expected_git_dir = _require_rooted_dot_git_directory(repo)
    top_level = Path(
        _run_git(["rev-parse", "--show-toplevel"], cwd=repo)
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if top_level != resolved_repo:
        raise AuditError(
            f"execution checkout top-level drifted: expected {resolved_repo}, got {top_level}"
        )
    git_dir = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=repo)
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    common_dir = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo)
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if git_dir != expected_git_dir or common_dir != expected_git_dir:
        raise AuditError(
            "execution checkout Git/common directory drifted: "
            f"expected {expected_git_dir}, got git-dir={git_dir}, common-dir={common_dir}"
        )


def _require_exact_baseline_worktree(repo: Path, *, baseline_sha: str) -> None:
    raw = _run_git(["ls-tree", "-r", "-z", "--full-tree", baseline_sha], cwd=repo)
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            header, encoded_path = item.split(b"\t", 1)
            encoded_mode, object_type, encoded_oid = header.split(b" ", 2)
            relative_path = encoded_path.decode("utf-8", errors="strict")
            mode = encoded_mode.decode("ascii")
            oid = encoded_oid.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuditError("baseline Git tree inventory is malformed") from exc
        if object_type != b"blob" or mode not in {"100644", "100755"}:
            raise AuditError(
                f"unsupported exact-baseline entry type/mode at {relative_path}: "
                f"{object_type!r}/{mode}"
            )
        content, observed_mode = _read_rooted_regular_file(
            repo,
            relative_path,
            label=f"exact baseline worktree path {relative_path}",
        )
        expected_mode = 0o755 if mode == "100755" else 0o644
        if observed_mode != expected_mode or _git_blob_sha1(content) != oid:
            raise AuditError(
                f"execution checkout tracked path differs from exact baseline: {relative_path}"
            )


def _require_exact_baseline_index(repo: Path, *, baseline_sha: str) -> None:
    baseline_raw = _run_git(["ls-tree", "-r", "-z", "--full-tree", baseline_sha], cwd=repo)
    expected: dict[str, tuple[str, str, str]] = {}
    for item in baseline_raw.split(b"\0"):
        if not item:
            continue
        try:
            header, encoded_path = item.split(b"\t", 1)
            encoded_mode, object_type, encoded_oid = header.split(b" ", 2)
            path = encoded_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuditError("baseline index inventory is malformed") from exc
        if object_type != b"blob":
            raise AuditError(f"baseline index contains unsupported entry type at {path}")
        expected[path] = (
            encoded_mode.decode("ascii"),
            encoded_oid.decode("ascii"),
            "0",
        )

    observed: dict[str, tuple[str, str, str]] = {}
    index_raw = _run_git(["ls-files", "--stage", "-z"], cwd=repo)
    for item in index_raw.split(b"\0"):
        if not item:
            continue
        try:
            header, encoded_path = item.split(b"\t", 1)
            encoded_mode, encoded_oid, encoded_stage = header.split(b" ", 2)
            path = encoded_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuditError("execution checkout index inventory is malformed") from exc
        if path in observed:
            raise AuditError(f"execution checkout index has duplicate/unmerged path: {path}")
        observed[path] = (
            encoded_mode.decode("ascii"),
            encoded_oid.decode("ascii"),
            encoded_stage.decode("ascii"),
        )
    if observed != expected:
        raise AuditError("execution checkout index does not exactly match the authorized baseline")


def _require_normal_index_flags(repo: Path) -> None:
    raw = _run_git(["ls-files", "-v", "-z"], cwd=repo)
    special: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        if len(item) < 3 or item[1:2] != b" ":
            raise AuditError("execution checkout index-flag inventory is malformed")
        if item[:1] != b"H":
            special.append(item[2:].decode("utf-8", errors="strict"))
    if special:
        raise AuditError(
            "execution checkout uses assume-unchanged/skip-worktree or other special "
            "index flags: " + ", ".join(sorted(special))
        )


def require_execution_checkout(
    repo: Path,
    *,
    baseline_sha: str,
    expected_branch: str,
    allowed_paths: frozenset[str],
) -> None:
    _require_rooted_dot_git_directory(repo)
    _require_safe_local_git_config(repo, label="execution checkout")
    _require_git_repository_binding(repo)
    symbolic_ref = _run_git_completed(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=repo,
    )
    if symbolic_ref.returncode == 1:
        raise AuditError(
            f"execution checkout must be attached to branch {expected_branch}; detached HEAD is not authorized"
        )
    if symbolic_ref.returncode != 0:
        raise AuditError("unable to resolve execution checkout attachment state")
    branch = symbolic_ref.stdout.decode("utf-8", errors="strict").strip()
    if branch != expected_branch:
        raise AuditError(
            f"execution checkout branch drifted: expected {expected_branch}, got {branch}"
        )
    head = _run_git(["rev-parse", "HEAD"], cwd=repo).decode("ascii").strip()
    if head != baseline_sha:
        raise AuditError(
            f"execution checkout must remain at exact baseline {baseline_sha}; got {head}"
        )
    _require_normal_index_flags(repo)
    _require_exact_baseline_index(repo, baseline_sha=baseline_sha)
    _require_exact_baseline_worktree(repo, baseline_sha=baseline_sha)

    changed: set[str] = set()
    for arguments in (
        ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", f"{baseline_sha}...HEAD"],
        ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z"],
        ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--name-only", "-z"],
        ["ls-files", "--others", "-z"],
    ):
        output = _run_git(arguments, cwd=repo)
        paths = [item.decode("utf-8", errors="strict") for item in output.split(b"\0") if item]
        changed.update(paths)
    unauthorized = sorted(changed - allowed_paths)
    if unauthorized:
        raise AuditError(
            "execution checkout contains paths outside the Phase-A boundary: "
            + ", ".join(unauthorized)
        )
    _require_normal_index_flags(repo)
    _require_exact_baseline_index(repo, baseline_sha=baseline_sha)
    _require_safe_local_git_config(repo, label="execution checkout")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    chunks = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                if index + 2 < len(pattern) and pattern[index + 2] == "/":
                    chunks.append("(?:.*/)?")
                    index += 3
                else:
                    chunks.append(".*")
                    index += 2
            else:
                chunks.append("[^/]*")
                index += 1
        elif character == "?":
            chunks.append("[^/]")
            index += 1
        else:
            chunks.append(re.escape(character))
            index += 1
    chunks.append("$")
    return re.compile("".join(chunks))


def _matches(rule: Mapping[str, Any], path: str) -> bool:
    included = any(_glob_regex(pattern).fullmatch(path) for pattern in rule["include"])
    excluded = any(_glob_regex(pattern).fullmatch(path) for pattern in rule["exclude"])
    return included and not excluded


def _owned_rules_and_paths() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ledger = _baseline_ledger()
    rules = [rule for rule in ledger["rules"] if rule["primary_owner"] == OWNER]
    paths = _baseline_paths()
    records: list[dict[str, Any]] = []
    for rule in rules:
        for path in paths:
            if not _matches(rule, path):
                continue
            content = _read_at_baseline(path)
            blob = _run_git(["rev-parse", f"{BASELINE_SHA}:{path}"]).decode().strip()
            records.append(
                {
                    "path": path,
                    "rule": rule["id"],
                    "class": rule["class"],
                    "consequence_tier": rule["consequence_tier"],
                    "git_blob_sha1": blob,
                    "content_sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )
    records.sort(key=lambda item: item["path"])
    if len(rules) != EXPECTED_RULE_COUNT or len(records) != EXPECTED_PATH_COUNT:
        raise AuditError(
            f"#976 expansion drifted: expected {EXPECTED_RULE_COUNT} rules/{EXPECTED_PATH_COUNT} "
            f"paths, got {len(rules)} rules/{len(records)} paths"
        )
    if len({record["path"] for record in records}) != len(records):
        raise AuditError("#976 expansion contains duplicate primary paths")
    expanded_paths = {record["path"] for record in records}
    if set(PATH_AUDIT) != expanded_paths:
        missing = sorted(expanded_paths - set(PATH_AUDIT))
        extra = sorted(set(PATH_AUDIT) - expanded_paths)
        raise AuditError(
            "explicit per-path audit map drifted: "
            f"missing={missing or 'none'}; extra={extra or 'none'}"
        )
    finding_index = {finding["id"]: finding for finding in FINDINGS}
    residual_index = {risk["id"]: risk for risk in RESIDUAL_RISKS}
    for record in records:
        audit = PATH_AUDIT[record["path"]]
        unknown_findings = sorted(set(audit["finding_ids"]) - set(finding_index))
        if unknown_findings:
            raise AuditError(
                f"unknown finding IDs for {record['path']}: {', '.join(unknown_findings)}"
            )
        residual_id = audit["residual_risk_id"]
        if residual_id is not None and residual_id not in residual_index:
            raise AuditError(f"unknown residual-risk ID for {record['path']}: {residual_id}")
        evidence_refs = [
            f"{reference}:{record['path']}"
            if reference in {"EV-PYTHON-MANIFEST", "EV-RUST-MANIFEST-LOCK"}
            else reference
            for reference in audit["evidence_refs"]
        ]
        record.update(
            {
                "phase_a_status": audit["phase_a_status"],
                "ledger_status": next(
                    rule["audit_status"] for rule in rules if rule["id"] == record["rule"]
                ),
                "disposition": audit["disposition"],
                "evidence_refs": evidence_refs,
                "finding_ids": list(audit["finding_ids"]),
                "finding_links": [
                    finding_index[finding_id]["issue"] for finding_id in audit["finding_ids"]
                ],
                "residual_risk": residual_index.get(residual_id),
                "snapshot_status": audit["snapshot_status"],
                "terminal_snapshot": audit["terminal_snapshot"],
            }
        )
    rule_summary = [
        {
            "id": rule["id"],
            "class": rule["class"],
            "consequence_tier": rule["consequence_tier"],
            "consequence_tags": rule["consequence_tags"],
            "path_count": sum(record["rule"] == rule["id"] for record in records),
            "ledger_status": rule["audit_status"],
            "terminal_snapshot": rule["terminal_snapshot"],
            "phase_a_status": "audited; ledger terminalization deferred",
        }
        for rule in rules
    ]
    return rule_summary, records


def _secondary_path_inventory(primary_paths: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ledger = _baseline_ledger()
    baseline_paths = set(_baseline_paths())
    primary = {record["path"] for record in primary_paths}
    grouped: dict[str, dict[str, Any]] = {}
    for group in SECONDARY_PATH_GROUPS:
        for path in group["paths"]:
            if path in grouped:
                raise AuditError(f"duplicate secondary-path record: {path}")
            grouped[path] = group
    overlap = sorted(primary & set(grouped))
    if overlap:
        raise AuditError(
            "secondary inventory overlaps primary ownership surface: " + ", ".join(overlap)
        )

    records: list[dict[str, Any]] = []
    for path in sorted(grouped):
        group = grouped[path]
        tracked = path in baseline_paths
        matching_rules = [rule for rule in ledger["rules"] if tracked and _matches(rule, path)]
        if tracked and len(matching_rules) != 1:
            raise AuditError(
                f"secondary path must retain exactly one baseline owner: {path} "
                f"matched {len(matching_rules)} rules"
            )
        if tracked:
            content = _read_at_baseline(path)
            blob = _run_git(["rev-parse", f"{BASELINE_SHA}:{path}"]).decode().strip()
            owner: dict[str, Any] | None = {
                "issue": matching_rules[0]["primary_owner"],
                "rule": matching_rules[0]["id"],
            }
            missing_reason = None
        else:
            content = b""
            blob = None
            owner = None
            missing_reason = (
                "expected Plotly companion notice is absent at the baseline"
                if path.endswith("plotly.min.js.LICENSE.txt")
                else "generated build-provenance path is intentionally absent from Git"
            )
        records.append(
            {
                "path": path,
                "tracked": tracked,
                "git_blob_sha1": blob,
                "content_sha256": hashlib.sha256(content).hexdigest() if tracked else None,
                "size_bytes": len(content) if tracked else None,
                "roles": [group["role"]],
                "evidence_refs": [f"EV-SECONDARY-PATH:{path}", *group["evidence_refs"]],
                "primary_owner_at_baseline": owner,
                "relationship": "secondary evidence only; primary ownership is not transferred",
                "execution_status": group["execution_status"],
                "finding_or_residual": group["finding_or_residual"],
                "missing_reason": missing_reason,
            }
        )
    tracked_count = sum(record["tracked"] for record in records)
    if tracked_count != 122 or len(records) != 124:
        raise AuditError(
            f"bounded secondary inventory drifted: expected 122 tracked/124 total, "
            f"got {tracked_count} tracked/{len(records)} total"
        )
    return records


def _parse_requirements(path: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for raw_line in _read_at_baseline(path).decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        kind = (
            "include" if line.startswith("-r ") else "git" if " @ git+" in line else "requirement"
        )
        pin = (
            "exact"
            if "==" in line or " @ git+" in line
            else "bounded"
            if "<" in line
            else "lower-bound"
        )
        records.append({"declaration": line, "kind": kind, "resolution": pin})
    return records


def _python_inventory() -> dict[str, list[dict[str, str]]]:
    paths = (
        "requirements.txt",
        "requirements-anomaly.txt",
        "requirements-build.txt",
        "requirements-dev.txt",
        "requirements-ocr.txt",
    )
    return {path: _parse_requirements(path) for path in paths}


def _cargo_inventory() -> dict[str, Any]:
    manifests = sorted(
        path
        for path in _baseline_paths()
        if path.startswith("src/metroliza/native/") and path.endswith("/Cargo.toml")
    )
    manifest_records: list[dict[str, Any]] = []
    package_variants: dict[str, dict[str, Any]] = {}
    coordinate_variants: dict[str, set[str]] = {}
    lock_packages: dict[str, list[dict[str, Any]]] = {}
    lock_membership: dict[str, list[str]] = {}
    for manifest_path in manifests:
        manifest = tomllib.loads(_read_at_baseline(manifest_path).decode("utf-8"))
        lock_path = str(Path(manifest_path).with_name("Cargo.lock"))
        lock = tomllib.loads(_read_at_baseline(lock_path).decode("utf-8"))
        keys: list[str] = []
        packages: list[dict[str, Any]] = []
        for package_index, package in enumerate(lock["package"]):
            source = package.get("source", "workspace")
            coordinate = f"{package['name']}@{package['version']}|{source}"
            record = {
                "name": package["name"],
                "version": package["version"],
                "source": source,
                "checksum": package.get("checksum"),
                "dependencies": sorted(package.get("dependencies", [])),
            }
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            variant_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            key = f"{coordinate}|{variant_sha256}"
            keys.append(key)
            package_variants[key] = {**record, "variant_sha256": variant_sha256}
            coordinate_variants.setdefault(coordinate, set()).add(variant_sha256)
            packages.append(
                {
                    **record,
                    "package_index": package_index,
                    "variant_sha256": variant_sha256,
                }
            )
        lock_packages[lock_path] = packages
        lock_membership[lock_path] = sorted(keys)
        manifest_records.append(
            {
                "path": manifest_path,
                "package": manifest["package"],
                "lib": manifest["lib"],
                "direct_dependencies": manifest["dependencies"],
                "lock_path": lock_path,
                "locked": True,
            }
        )
    return {
        "manifests": manifest_records,
        "unique_locked_package_variants": [
            package_variants[key] for key in sorted(package_variants)
        ],
        "coordinates_with_multiple_dependency_variants": sorted(
            coordinate for coordinate, variants in coordinate_variants.items() if len(variants) > 1
        ),
        "lock_packages": lock_packages,
        "lock_membership": lock_membership,
    }


def _action_inventory() -> list[dict[str, Any]]:
    workflow = _read_at_baseline(".github/workflows/ci.yml").decode("utf-8")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(workflow.splitlines(), start=1):
        match = re.search(r"uses:\s+([^@\s]+)@([0-9a-f]{40})(?:\s+#\s*(.*))?$", line)
        if match:
            records.append(
                {
                    "line": line_number,
                    "action": match.group(1),
                    "sha": match.group(2),
                    "annotation": match.group(3) or "",
                    "immutable_sha": True,
                }
            )
    if not records:
        raise AuditError("no SHA-pinned Actions were discovered")
    return records


def _python_cli_options(source: str) -> list[str]:
    options: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute) and function.attr in {"add_argument", "add_parser"}
        ):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                options.add(argument.value)
    return sorted(options)


def _powershell_cli_options(path: str, source: str) -> list[str]:
    match = re.search(r"(?ms)^param\(\n(?P<body>.*?)^\)\s*$", source)
    if match is None:
        match = re.search(
            r"(?ms)^\[CmdletBinding\(\)\]\s*\nparam\(\n(?P<body>.*?)^\)\s*$",
            source,
        )
    if match is None:
        raise AuditError(f"PowerShell entrypoint parameter block drifted: {path}")
    parameters: set[str] = set()
    ignored_attributes = {"Parameter", "ValidateSet", "AllowNull"}
    for line in match.group("body").splitlines():
        declaration = re.match(
            r"^\s*\[(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:\[\])?)\]\s*\$(?P<name>\w+)",
            line,
        )
        if declaration and declaration.group("type") not in ignored_attributes:
            parameters.add(declaration.group("name"))
    if not parameters:
        raise AuditError(f"PowerShell entrypoint has no declared parameters: {path}")
    return sorted(parameters)


def _declared_cli_options(path: str, source: str) -> list[str]:
    """Return fail-closed option/parameter names from an exact baseline entrypoint."""
    if path.endswith(".py"):
        return _python_cli_options(source)
    if path.endswith(".ps1"):
        return _powershell_cli_options(path, source)
    if path.endswith(".bat"):
        return ["%* (forwarded verbatim)"]
    if path.endswith(".spec"):
        return ["--noconfirm", "spec path"]
    return []


def _build_command_inventory() -> list[dict[str, Any]]:
    contracts = list(BUILD_COMMAND_CONTRACTS)

    paths = [contract["path"] for contract in contracts]
    if len(paths) != len(set(paths)):
        raise AuditError("build-command inventory contains duplicate entrypoint paths")
    if len(paths) != 25:
        raise AuditError(f"build-command entrypoint closure drifted: expected 25, got {len(paths)}")
    baseline_paths = set(_baseline_paths())
    missing = sorted(set(paths) - baseline_paths)
    if missing:
        raise AuditError("build-command entrypoint missing at baseline: " + ", ".join(missing))

    caller_suffixes = (".md", ".yml", ".yaml", ".bat", ".ps1", ".spec", ".py")
    caller_sources: dict[str, str] = {}
    for candidate in sorted(path for path in baseline_paths if path.endswith(caller_suffixes)):
        try:
            caller_sources[candidate] = _read_at_baseline(candidate).decode("utf-8")
        except UnicodeDecodeError:
            continue

    rows: list[dict[str, Any]] = []
    for contract in contracts:
        path = contract["path"]
        content = _read_at_baseline(path)
        source = content.decode("utf-8", errors="strict")
        tokens = {path, Path(path).name}
        reference_edges: list[dict[str, Any]] = []
        for caller_path, caller_source in caller_sources.items():
            if caller_path == path:
                continue
            line_numbers = [
                line_number
                for line_number, line in enumerate(caller_source.splitlines(), start=1)
                if any(token in line for token in tokens)
            ]
            if line_numbers:
                reference_edges.append({"path": caller_path, "line_numbers": line_numbers})
        rows.append(
            {
                **contract,
                "environment": contract.get("environment", "see exact platform/caller contract"),
                "declared_options": _declared_cli_options(path, source),
                "baseline_ref": f"{BASELINE_SHA}:{path}",
                "git_blob_sha1": _run_git(["rev-parse", f"{BASELINE_SHA}:{path}"]).decode().strip(),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "baseline_reference_edges": reference_edges,
                "status": "statically inventoried at exact baseline; execution status is stated separately",
            }
        )
    return sorted(rows, key=lambda row: row["path"])


def _yaml_scalar(lines: Sequence[str], key: str, *, indent: int) -> str | None:
    prefix = " " * indent + key + ":"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if value not in {"|", ">", "|-", ">-"}:
            return value or None
        block: list[str] = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            block.append(following[indent + 2 :] if following else "")
        return "\n".join(block).rstrip()
    return None


def _yaml_child_mapping(lines: Sequence[str], section: str, *, indent: int) -> dict[str, str]:
    header = " " * indent + section + ":"
    try:
        start = next(index for index, line in enumerate(lines) if line == header)
    except StopIteration:
        return {}
    child_indent = indent + 2
    records: dict[str, str] = {}
    index = start + 1
    while index < len(lines):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip()) if line.strip() else child_indent + 2
        if line.strip() and current_indent <= indent:
            break
        match = re.match(rf"^ {{{child_indent}}}([^:#]+):\s*(.*)$", line)
        if not match:
            index += 1
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        if value in {"|", ">", "|-", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines):
                following = lines[index]
                following_indent = (
                    len(following) - len(following.lstrip())
                    if following.strip()
                    else child_indent + 2
                )
                if following.strip() and following_indent <= child_indent:
                    break
                block.append(following[child_indent + 2 :] if following else "")
                index += 1
            records[key] = "\n".join(block).rstrip()
            continue
        records[key] = value
        index += 1
    return records


def _workflow_step_record(
    job_id: str,
    job_start: int,
    step_position: int,
    step_start: int,
    step_end: int,
    step_lines: Sequence[str],
) -> dict[str, Any]:
    name = step_lines[0].split(":", 1)[1].strip()
    uses = _yaml_scalar(step_lines, "uses", indent=8)
    run = _yaml_scalar(step_lines, "run", indent=8)
    if uses is None and run is None:
        raise AuditError(f"workflow step has neither uses nor run: {job_id}/{name}")
    condition = _yaml_scalar(step_lines, "if", indent=8)
    continue_on_error = _yaml_scalar(step_lines, "continue-on-error", indent=8)
    inputs = _yaml_child_mapping(step_lines, "with", indent=8)
    raw_yaml = "\n".join(line[6:] for line in step_lines).rstrip() + "\n"
    record: dict[str, Any] = {
        "index": step_position + 1,
        "name": name,
        "id": _yaml_scalar(step_lines, "id", indent=8),
        "shell": _yaml_scalar(step_lines, "shell", indent=8),
        "source_lines": [job_start + step_start + 1, job_start + step_end],
        "source_yaml": raw_yaml,
        "source_yaml_sha256": hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest(),
        "uses": uses,
        "run": run,
        "with": inputs,
        "env": _yaml_child_mapping(step_lines, "env", indent=8),
        "if": condition,
        "effective_if": condition or "success()",
        "continue_on_error": continue_on_error == "true",
        "skip_and_failure_semantics": (
            "failure is advisory; later steps continue"
            if continue_on_error == "true"
            else (
                f"runs under explicit {condition}; failure remains blocking"
                if condition
                else "runs only after prior success; failure blocks later success()-gated steps"
            )
        ),
    }
    if uses and uses.startswith("actions/setup-python@"):
        record["cache_semantics"] = {
            "manager": inputs.get("cache", "not enabled"),
            "dependency_paths": inputs.get("cache-dependency-path", "").splitlines(),
            "resolved_key": (
                "action-managed from runner OS, architecture, resolved Python, package manager "
                "and dependency-file hashes; exact runtime key is unavailable statically"
            ),
            "restore_boundary": "download cache only; installed environment is rebuilt by pip",
        }
    if uses and uses.startswith("actions/upload-artifact@"):
        record["artifact_semantics"] = {
            "name": inputs.get("name", "not set"),
            "path": inputs.get("path", "not set").splitlines(),
            "if_no_files_found": inputs.get("if-no-files-found", "not set; action default applies"),
            "retention_days": inputs.get(
                "retention-days", "not set; repository/default retention applies"
            ),
            "upload_condition": condition or "success()",
        }
    return record


def _workflow_tool_resolution(job_lines: Sequence[str]) -> list[str]:
    job_text = "\n".join(job_lines)
    resolution: list[str] = []
    if "python-version: '3.11'" in job_text:
        resolution.append("CPython 3.11 minor selector; hosted patch resolution floats")
    if "python -m pip install --upgrade pip" in job_text:
        resolution.append("pip is upgraded without a version pin")
    if "apt-get install" in job_text:
        resolution.append("APT package versions float with ubuntu-latest repositories")
    if "toolchain: 1.95.0" in job_text:
        resolution.append("Rust toolchain is fixed to 1.95.0")
    if "requirements" in job_text and "pip install" in job_text:
        resolution.append("pip resolves lower-bound requirement manifests without a lock")
    return resolution


def _workflow_job_record(lines: Sequence[str], start: int, end: int) -> dict[str, Any]:
    job_lines = lines[start:end]
    job_id = job_lines[0].strip()[:-1]
    step_starts = [
        index for index, line in enumerate(job_lines) if re.fullmatch(r"      - name: .+", line)
    ]
    steps: list[dict[str, Any]] = []
    for step_position, step_start in enumerate(step_starts):
        step_end = (
            step_starts[step_position + 1]
            if step_position + 1 < len(step_starts)
            else len(job_lines)
        )
        steps.append(
            _workflow_step_record(
                job_id,
                start,
                step_position,
                step_start,
                step_end,
                job_lines[step_start:step_end],
            )
        )
    return {
        "job": job_id,
        "source_lines": [start + 1, end],
        "name": _yaml_scalar(job_lines, "name", indent=4),
        "runner": _yaml_scalar(job_lines, "runs-on", indent=4),
        "timeout_minutes": _yaml_scalar(job_lines, "timeout-minutes", indent=4),
        "needs": _yaml_scalar(job_lines, "needs", indent=4),
        "if": _yaml_scalar(job_lines, "if", indent=4),
        "continue_on_error": _yaml_scalar(job_lines, "continue-on-error", indent=4) == "true",
        "env": _yaml_child_mapping(job_lines, "env", indent=4),
        "tool_resolution": _workflow_tool_resolution(job_lines),
        "steps": steps,
    }


def _workflow_step_inventory() -> dict[str, Any]:
    workflow_bytes = _read_at_baseline(".github/workflows/ci.yml")
    workflow = workflow_bytes.decode("utf-8")
    lines = workflow.splitlines()
    try:
        jobs_start = lines.index("jobs:") + 1
    except ValueError as exc:
        raise AuditError("workflow jobs mapping is absent") from exc

    job_starts = [
        index
        for index in range(jobs_start, len(lines))
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index])
    ]
    jobs = [
        _workflow_job_record(
            lines,
            start,
            job_starts[position + 1] if position + 1 < len(job_starts) else len(lines),
        )
        for position, start in enumerate(job_starts)
    ]
    if len(jobs) != 8 or any(not job["steps"] for job in jobs):
        raise AuditError("workflow job/step inventory drifted")
    return {
        "path": ".github/workflows/ci.yml",
        "baseline_blob": _run_git(["rev-parse", f"{BASELINE_SHA}:.github/workflows/ci.yml"])
        .decode()
        .strip(),
        "content_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
        "line_count": len(lines),
        "jobs": jobs,
    }


def _powershell_array(source: str, variable: str) -> list[str]:
    match = re.search(
        rf"(?m)^(?P<indent>[ \t]*)\${re.escape(variable)}\s*=\s*@\(\s*$",
        source,
    )
    if match is None:
        raise AuditError(f"PowerShell array not found: {variable}")
    indent = match.group("indent")
    body_lines: list[str] = []
    for line in source[match.end() :].splitlines():
        if line == f"{indent})":
            values = re.findall(r"['\"]([^'\"]+)['\"]", "\n".join(body_lines))
            if not values:
                raise AuditError(f"PowerShell array is empty: {variable}")
            return values
        body_lines.append(line)
    raise AuditError(f"PowerShell array is unterminated: {variable}")


def _pyinstaller_hidden_import_inventory(source: str) -> tuple[list[str], list[str]]:
    explicit: list[str] = []
    dynamic: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or key.value != "hiddenimports":
                continue
            if not isinstance(value, ast.List):
                raise AuditError("PyInstaller hiddenimports stopped being a literal list")
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    explicit.append(element.value)
                elif isinstance(element, ast.Starred) and isinstance(element.value, ast.Name):
                    dynamic.append(element.value.id)
    if not explicit or not dynamic:
        raise AuditError("PyInstaller hidden-import inventory drifted")
    return explicit, dynamic


def _rapidocr_asset_manifest(source: str) -> dict[str, Any]:
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "RAPIDOCR_MODEL_ASSET_MANIFEST"
            for target in node.targets
        ):
            continue
        literal = ast.literal_eval(node.value)
        if not isinstance(literal, dict):
            raise AuditError("RapidOCR asset manifest stopped being a literal mapping")
        return literal
    raise AuditError("RapidOCR asset manifest is absent from the baseline backend")


def _rapidocr_model_hash_inventory(
    manifest: Mapping[str, Any], model_files: Sequence[str]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for model_file in model_files:
        asset = manifest[model_file]
        if not isinstance(asset, dict) or not isinstance(asset.get("sha256"), str):
            raise AuditError(f"RapidOCR manifest hash is invalid: {model_file}")
        source = f"src/metroliza/resources/ocr_models/rapidocr/{model_file}"
        content = _read_at_baseline(source)
        expected_sha256 = asset["sha256"]
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise AuditError(
                f"RapidOCR baseline hash mismatch for {model_file}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        records.append(
            {
                "source": source,
                "manifest_source": "src/metroliza/parsing/header_ocr_backend.py:RAPIDOCR_MODEL_ASSET_MANIFEST",
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "match": True,
                "git_blob_sha1": _run_git(["rev-parse", f"{BASELINE_SHA}:{source}"])
                .decode()
                .strip(),
            }
        )
    return records


def _tracked_package_source(path: str, baseline_paths: set[str]) -> dict[str, Any]:
    if path not in baseline_paths:
        return {
            "source": path,
            "tracked": False,
            "git_blob_sha1": None,
            "content_sha256": None,
        }
    content = _read_at_baseline(path)
    return {
        "source": path,
        "tracked": True,
        "git_blob_sha1": _run_git(["rev-parse", f"{BASELINE_SHA}:{path}"]).decode().strip(),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def _package_resource(
    source: str,
    *,
    baseline_paths: set[str],
    kind: str,
    pyinstaller: str,
    nuitka: str,
    required_condition: str,
    destination: str,
    source_result: str,
    installed_result: str,
    frozen_result: str,
    evidence_refs: Sequence[str],
    finding_or_residual: str | None = None,
) -> dict[str, Any]:
    return {
        **_tracked_package_source(source, baseline_paths),
        "kind": kind,
        "packagers_and_modes": {
            "pyinstaller_onefile": pyinstaller,
            "pyinstaller_onedir": pyinstaller,
            "nuitka_onefile": nuitka,
            "nuitka_standalone": nuitka,
        },
        "required_condition": required_condition,
        "destination": destination,
        "discovery": {
            "source": source_result,
            "installed": installed_result,
            "frozen": frozen_result,
        },
        "evidence_refs": list(evidence_refs),
        "finding_or_residual": finding_or_residual,
    }


def _package_inventory() -> dict[str, Any]:
    pyinstaller_source = _read_at_baseline("packaging/pyinstaller_common.py").decode("utf-8")
    nuitka_source = _read_at_baseline("packaging/build_nuitka.ps1").decode("utf-8")
    baseline_paths = set(_baseline_paths())

    explicit_hiddenimports, dynamic_hiddenimport_collections = _pyinstaller_hidden_import_inventory(
        pyinstaller_source
    )

    required_collections = sorted(
        set(re.findall(r'collect_required_runtime_assets\(\s*["\']([^"\']+)', pyinstaller_source))
    )
    optional_metadata = sorted(
        set(
            re.findall(
                r'collect_optional_distribution_metadata\(["\']([^"\']+)', pyinstaller_source
            )
        )
    )
    nuitka_literal_flags = sorted(
        set(
            flag
            for flag in re.findall(
                r"['\"](--(?:enable-plugin|include-(?:package|module|package-data|distribution-metadata)|noinclude-data-files)[^'\"]*)['\"]",
                nuitka_source,
            )
            if "$" not in flag
        )
    )
    nuitka_pdf_modules = _powershell_array(nuitka_source, "requiredPdfBackendModules")
    nuitka_ocr_args = _powershell_array(nuitka_source, "headerOcrNuitkaArgs")
    nuitka_model_files = _powershell_array(nuitka_source, "rapidOcrModelFiles")
    nuitka_token_exclusions = _powershell_array(nuitka_source, "tokenExcludePatterns")

    ocr_manifest_source = _read_at_baseline("src/metroliza/parsing/header_ocr_backend.py").decode(
        "utf-8"
    )
    ocr_manifest = _rapidocr_asset_manifest(ocr_manifest_source)
    if set(ocr_manifest) != set(nuitka_model_files):
        raise AuditError("RapidOCR manifest and Nuitka model-file inventory drifted")
    ocr_model_hashes = _rapidocr_model_hash_inventory(ocr_manifest, nuitka_model_files)

    resources: list[dict[str, Any]] = []

    def resource(
        source: str,
        *,
        kind: str,
        pyinstaller: str,
        nuitka: str,
        required_condition: str,
        destination: str,
        source_result: str,
        installed_result: str,
        frozen_result: str,
        evidence_refs: Sequence[str],
        finding_or_residual: str | None = None,
    ) -> None:
        resources.append(
            _package_resource(
                source,
                baseline_paths=baseline_paths,
                kind=kind,
                pyinstaller=pyinstaller,
                nuitka=nuitka,
                required_condition=required_condition,
                destination=destination,
                source_result=source_result,
                installed_result=installed_result,
                frozen_result=frozen_result,
                evidence_refs=evidence_refs,
                finding_or_residual=finding_or_residual,
            )
        )

    resource(
        "src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js",
        kind="offline Plotly runtime",
        pyinstaller="included explicitly in shared datas",
        nuitka="included explicitly with --include-data-files",
        required_condition="required for offline dashboard export",
        destination="metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js",
        source_result="present and hash-bound",
        installed_result="resource locator assessed from isolated cwd",
        frozen_result="not executed",
        evidence_refs=["EV-PACKAGING-EXPLICIT-ASSETS"],
        finding_or_residual="HD-976-F008/#994",
    )
    resource(
        "src/metroliza/resources/html_dashboard_assets/plotly.min.js.LICENSE.txt",
        kind="Plotly companion notices",
        pyinstaller="absent",
        nuitka="absent",
        required_condition="referenced by vendored Plotly bundle",
        destination="metroliza/resources/html_dashboard_assets/plotly.min.js.LICENSE.txt",
        source_result="missing from baseline tree",
        installed_result="unavailable because source is absent",
        frozen_result="unavailable because source is absent",
        evidence_refs=["EV-PACKAGING-NOTICES"],
        finding_or_residual="HD-976-F008/#994",
    )
    resource(
        "THIRD_PARTY_NOTICES.md",
        kind="top-level third-party notices",
        pyinstaller="embedded and staged beside artifact",
        nuitka="embedded and staged beside artifact",
        required_condition="required; both paths fail when absent",
        destination="artifact root and notice sidecar",
        source_result="present and hash-bound",
        installed_result="not applicable",
        frozen_result="static inclusion only; packaged legal acceptance not executed",
        evidence_refs=["EV-PACKAGING-NOTICES"],
    )
    resource(
        "docs/release_checks/third_party_inventory_260711.json",
        kind="third-party inventory",
        pyinstaller="embedded and staged beside artifact",
        nuitka="staged beside artifact by notice helper; not embedded explicitly",
        required_condition="required by notice staging; current-release/dependency freshness is not enforced",
        destination="artifact root/sidecar",
        source_result="present and hash-bound; 260711 aligns with current VERSION_DATE but freshness provenance is absent",
        installed_result="capture-environment regeneration matched after excluding generated_at, but installed Python/Cargo environment identity is not bound and general determinism is not claimed",
        frozen_result="staging helper tested; release artifact not executed",
        evidence_refs=["EV-PACKAGING-NOTICES"],
        finding_or_residual="HD-976-F008/#994; HD-976-F011/#999",
    )
    resource(
        "build/provenance/build_provenance.json",
        kind="generated or externally supplied build provenance",
        pyinstaller="generated by default, or accepts METROLIZA_BUILD_PROVENANCE_PATH after schema/packager/release checks; embedded by both specs; staged as an artifact sidecar only by PowerShell build callers, not manual Linux packaging-smoke",
        nuitka="no equivalent generated/embedded binding",
        required_condition="PyInstaller required, but supplied same-release Git/time freshness is not enforced (#1001); Nuitka gap deferred",
        destination="metroliza/app/build_provenance.json and sidecar",
        source_result="generated, therefore not tracked",
        installed_result="generation/helper tests pass; synthetic stale-Git/time audit control exposes #1001",
        frozen_result="no release artifact executed",
        evidence_refs=["EV-PACKAGING-PROVENANCE"],
        finding_or_residual="HD-976-F015/#1001; HD-976-R004/#920",
    )
    for model_file in nuitka_model_files:
        resource(
            f"src/metroliza/resources/ocr_models/rapidocr/{model_file}",
            kind="RapidOCR model",
            pyinstaller="collected from current/legacy model roots when present",
            nuitka="included explicitly when present; release gate requires OCR unless unsafe override",
            required_condition="required for supported header OCR package build",
            destination=f"metroliza/resources/ocr_models/rapidocr/{model_file}",
            source_result="present; hash and deletion control passed",
            installed_result="PDF/OCR validator and model-load probe passed",
            frozen_result="packaged provider/model load not executed",
            evidence_refs=["EV-PACKAGING-OCR-MODELS", "DP-OCR-HASH-DELETE"],
            finding_or_residual="HD-976-R001/#901",
        )
    resource(
        "packaging/metroliza_icon2.ico",
        kind="application icon",
        pyinstaller="onefile and onedir icon",
        nuitka="--windows-icon-from-ico",
        required_condition="packager input; Windows rendering untested",
        destination="executable resources",
        source_result="present and hash-bound",
        installed_result="not applicable",
        frozen_result="not executed on Windows",
        evidence_refs=["EV-PACKAGING-EXPLICIT-ASSETS"],
        finding_or_residual="HD-976-R001/#901",
    )
    resource(
        "packaging/metroliza_bootloader_splash.png",
        kind="boot splash",
        pyinstaller="onefile on Windows only; onedir does not configure splash",
        nuitka="not configured",
        required_condition="optional presentation asset",
        destination="PyInstaller splash resources",
        source_result="present and hash-bound",
        installed_result="not applicable",
        frozen_result="not executed on Windows",
        evidence_refs=["EV-PACKAGING-EXPLICIT-ASSETS"],
        finding_or_residual="HD-976-R001/#901",
    )
    resource(
        "docs/user_manual/group_analysis/user_manual.pdf",
        kind="user manual/help",
        pyinstaller="not embedded",
        nuitka="not embedded",
        required_condition="online help is current behavior; offline availability unproven",
        destination="none",
        source_result="18 manual files inventoried; representative PDF hash-bound",
        installed_result="online-path behavior only",
        frozen_result="offline packaged help not executed",
        evidence_refs=["EV-PACKAGING-MANUALS"],
        finding_or_residual="HD-976-R003/#955",
    )
    resource(
        "src/metroliza/resources/app_assets.py",
        kind="resource locator/parser-profile boundary",
        pyinstaller="metroliza submodules collected; runtime user profiles are external",
        nuitka="metroliza package included; runtime user profiles are external",
        required_condition="source resources required; mutable parser profiles remain user data",
        destination="frozen metroliza package plus external profile home",
        source_result="source and isolated-cwd controls assessed",
        installed_result="not proven from installed wheel",
        frozen_result="not proven from packaged artifact",
        evidence_refs=["EV-PACKAGING-HIDDEN-IMPORTS", "NC-repository-root-only-import"],
        finding_or_residual="HD-976-R005/#901/#984",
    )
    resource(
        "PyQt6 platform plugins",
        kind="Qt platform libraries/plugins",
        pyinstaller="PyQt6 hook-managed; no exact expanded frozen file list captured",
        nuitka="--enable-plugin=pyqt6",
        required_condition="required for GUI startup",
        destination="packager-managed Qt plugin tree",
        source_result="Qt import/runtime validator passed on Linux",
        installed_result="proposal/baseline Linux validators passed",
        frozen_result="qwindows/package startup not executed",
        evidence_refs=["EV-PACKAGING-QT", "DP-PR973-QT"],
        finding_or_residual="HD-976-R001/#901",
    )
    resource(
        "_metroliza_* native extension modules",
        kind="five Rust native extensions",
        pyinstaller="five explicit hidden imports; compiled binaries collected when available",
        nuitka="five conditional --include-module flags; -RequireNative fails if CMM module absent",
        required_condition="native optional unless enforcement requested; fallback must remain truthful",
        destination="packager-managed extension-module path",
        source_result="five locked crates and local tests captured",
        installed_result="Linux native/fallback/parity evidence captured",
        frozen_result="Windows ABI/DLL execution not run",
        evidence_refs=["EV-RUST-MANIFEST-LOCK", "NC-misleading-native-fallback"],
        finding_or_residual="HD-976-R001/#901",
    )

    return {
        "pyinstaller": {
            "modes": ["onefile", "onedir"],
            "shared_collection_source": "packaging/pyinstaller_common.py",
            "explicit_hiddenimports": explicit_hiddenimports,
            "dynamic_collect_submodules_variables": dynamic_hiddenimport_collections,
            "required_package_data_binary_submodule_collections": required_collections,
            "optional_distribution_metadata": optional_metadata,
            "windows_runtime_dll_globs": [
                "libffi*.dll",
                "python3.dll",
                "python3*.dll",
                "vcruntime*.dll",
                "msvcp*.dll",
            ],
            "source_discovery": "statically complete and helper-tested",
            "installed_discovery": "representative isolated-cwd tests pass",
            "frozen_discovery": "not executed in Phase A",
        },
        "nuitka": {
            "modes": ["onefile", "standalone"],
            "literal_include_and_plugin_flags": nuitka_literal_flags,
            "conditional_native_modules": [
                "_metroliza_cmm_native",
                "_metroliza_chart_native",
                "_metroliza_group_stats_native",
                "_metroliza_comparison_stats_native",
                "_metroliza_distribution_fit_native",
            ],
            "conditional_pdf_modules": nuitka_pdf_modules,
            "conditional_ocr_arguments": nuitka_ocr_args,
            "credential_bundle": "optional -BundleCredentials; disabled by default; missing requested file fails",
            "token_exclusions": nuitka_token_exclusions,
            "source_discovery": "statically complete; exact flags preserved",
            "installed_discovery": "dependency availability probes assessed",
            "frozen_discovery": "not executed; standalone artifact freshness defect #992",
        },
        "resources": resources,
        "ocr_model_hashes": ocr_model_hashes,
        "windows_prerequisite": (
            "VC redistributable detection is explicit; optional installer download lacks "
            "pre-execution signer/digest verification (#997)"
        ),
    }


def required_paths_exist(root: Path, paths: Iterable[str]) -> None:
    missing = sorted(path for path in paths if not (root / path).is_file())
    if missing:
        raise AuditError("missing required packaged asset(s): " + ", ".join(missing))


def require_portable_import(*, source_root_ok: bool, isolated_cwd_ok: bool) -> None:
    if not source_root_ok or not isolated_cwd_ok:
        raise AuditError("import/resource discovery succeeds only from repository-root state")


def require_native_truth(*, required: bool, import_ok: bool, native_available: bool) -> None:
    if not import_ok:
        raise AuditError("native bridge import failed")
    if required and not native_available:
        raise AuditError("required native backend is unavailable despite import success")


def require_static_gates(results: Mapping[str, int]) -> None:
    failed = sorted(name for name, exit_code in results.items() if exit_code != 0)
    if failed:
        raise AuditError("static gate finding(s): " + ", ".join(failed))


def capture_artifact_state(
    artifact: Path,
    *,
    output_root: Path,
) -> dict[str, Any] | None:
    descriptor: int | None = None
    try:
        with _rooted_parent_directory(output_root, artifact) as parent_fd:
            try:
                descriptor = os.open(
                    artifact.name,
                    os.O_RDONLY
                    | getattr(os, "O_NONBLOCK", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                return None
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise AuditError(f"artifact target is an indirect symlink: {artifact}") from exc
                raise AuditError(
                    f"unable to open artifact target safely: {artifact}: {exc}"
                ) from exc
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise AuditError(f"artifact target is not a single-link regular file: {artifact}")
            content = _read_stable_descriptor(descriptor, label=f"artifact target {artifact}")
            after = os.fstat(descriptor)
            lexical = os.stat(artifact.name, dir_fd=parent_fd, follow_symlinks=False)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if any(
                getattr(left, field) != getattr(right, field)
                for left, right in ((before, after), (after, lexical))
                for field in stable_fields
            ):
                raise AuditError(f"artifact target identity changed during capture: {artifact}")
            return {
                "device": after.st_dev,
                "inode": after.st_ino,
                "link_count": after.st_nlink,
                "mode": stat.S_IMODE(after.st_mode),
                "size": after.st_size,
                "mtime_ns": after.st_mtime_ns,
                "ctime_ns": after.st_ctime_ns,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
    finally:
        _close_descriptors(descriptor)


def require_current_artifact(
    artifact: Path,
    *,
    output_root: Path,
    command_exit_code: int,
    attempt_started_ns: int,
    prior_state: Mapping[str, Any] | None,
    minimum_size: int = 1,
) -> None:
    if command_exit_code != 0:
        raise AuditError(f"build command failed with exit code {command_exit_code}")
    current_state = capture_artifact_state(artifact, output_root=output_root)
    if current_state is None:
        raise AuditError(f"zero-exit build produced no required artifact: {artifact}")
    if current_state["size"] < minimum_size:
        raise AuditError(f"artifact is partial or undersized: {artifact}")
    if current_state["mtime_ns"] < attempt_started_ns:
        raise AuditError(f"artifact predates current build attempt: {artifact}")
    if prior_state is not None:
        identity_and_content = ("device", "inode", "size", "sha256")
        if all(current_state[key] == prior_state.get(key) for key in identity_and_content):
            raise AuditError(f"artifact is unchanged from pre-build state: {artifact}")


def require_family_workflow(*, import_ok: bool, workflow_ok: bool) -> None:
    if not import_ok:
        raise AuditError("dependency family import smoke failed")
    if not workflow_ok:
        raise AuditError("dependency family passed imports but failed representative workflow")


def require_job_result(*, required: bool, conclusion: str) -> None:
    if required and conclusion != "success":
        raise AuditError(f"required CI job concluded {conclusion!r}, not success")


def require_cache_independence(*, cold_ok: bool, warm_ok: bool, key_matches: bool) -> None:
    if not cold_ok:
        raise AuditError("workflow succeeds only with warm cache state")
    if not warm_ok or not key_matches:
        raise AuditError("cache key/content does not match the declared dependency state")


def require_tool(*, name: str, available: bool, required: bool) -> str:
    if required and not available:
        raise AuditError(f"required tool/dependency is unavailable: {name}")
    return "available" if available else "optional capability unavailable"


def require_current_build_provenance(
    *,
    manifest_git_sha: str,
    expected_git_sha: str,
    manifest_built_at_ns: int,
    attempt_started_ns: int,
) -> None:
    if manifest_git_sha != expected_git_sha:
        raise AuditError("build provenance Git identity does not match the build checkout")
    if manifest_built_at_ns < attempt_started_ns:
        raise AuditError("build provenance predates the current build attempt")


def require_redacted_diagnostic(
    payload: Mapping[str, Any], *, sensitive_values: Sequence[str]
) -> None:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    leaked = sorted(value for value in sensitive_values if value and value in serialized)
    if leaked:
        raise AuditError("diagnostic output retains sensitive value(s): " + ", ".join(leaked))


def require_no_partial_fetch_temps(output_dir: Path) -> None:
    residues = sorted(path.name for path in output_dir.glob("*.tmp") if path.is_file())
    if residues:
        raise AuditError("partial model-fetch temporary file remains: " + ", ".join(residues))


def require_commit_available(repo: Path, commit_sha: str) -> None:
    completed = _run_git_completed(["cat-file", "-e", f"{commit_sha}^{{commit}}"], cwd=repo)
    if completed.returncode != 0:
        raise AuditError(f"audited commit is unavailable locally: {commit_sha}")


def require_writable_output(path: Path) -> None:
    existing_parent = next(
        (candidate for candidate in (path, *path.parents) if candidate.exists()), None
    )
    if existing_parent is None:
        raise AuditError(f"output has no existing parent: {path}")
    writable_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if existing_parent.stat().st_mode & writable_bits == 0:
        raise AuditError(f"output target is read-only: {existing_parent}")


def require_isolated_output(
    path: Path,
    *,
    repo_root: Path = ROOT,
    temp_root: Path = Path(tempfile.gettempdir()),
) -> Path:
    lexical = path.absolute()
    resolved = path.resolve(strict=False)
    resolved_repo = repo_root.resolve()
    resolved_temp = temp_root.resolve()
    if resolved == resolved_repo or resolved_repo in resolved.parents:
        raise AuditError(f"isolated output must be outside the repository: {resolved}")
    if resolved == resolved_temp or resolved_temp not in resolved.parents:
        raise AuditError(f"isolated output must be a file below {resolved_temp}: {resolved}")
    current = lexical
    while True:
        if current.is_symlink():
            raise AuditError(f"isolated output has a symlink component: {current}")
        if current == temp_root.absolute() or current.parent == current:
            break
        current = current.parent
    if resolved.exists():
        raise AuditError(f"isolated output already exists; refusing overwrite: {resolved}")
    try:
        with _rooted_parent_directory(temp_root, lexical):
            pass
    except AuditError as exc:
        raise AuditError(
            f"isolated output parent must preexist as a rooted directory: {lexical.parent}"
        ) from exc
    return resolved


def probe_path_permissions(base: Path) -> dict[str, str]:
    nested = base / ("Zażółć gęślą jaźń " + "x" * 96) / "artifact.bin"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"sanitized")
    if nested.read_bytes() != b"sanitized":
        raise AuditError("non-ASCII/spaces/long path round trip failed")
    return {"portable_path": "pass", "read_only": "covered by deterministic unit control"}


def _truth_contract_checks() -> None:
    workflow = _read_at_baseline(".github/workflows/ci.yml").decode("utf-8")
    required_snippets = (
        "permissions:\n  contents: read",
        "cancel-in-progress: true",
        "persist-credentials: false",
        "runs-on: ubuntu-latest",
        "runs-on: windows-latest",
        "continue-on-error: true",
        "inputs.run_packaging_smoke == '1'",
        "inputs.run_windows_startup_benchmark == '1'",
    )
    missing = [snippet for snippet in required_snippets if snippet not in workflow]
    if missing:
        raise AuditError("workflow truth contract drifted: " + ", ".join(missing))
    if "fetch-depth:" in workflow:
        raise AuditError("workflow checkout-depth finding changed; refresh Issue #991 evidence")
    if _run_git(["rev-parse", f"{BASELINE_SHA}^{{tree}}"]).decode().strip() != BASELINE_TREE:
        raise AuditError("authorized baseline tree mismatch")


EVIDENCE_POINTERS: dict[str, tuple[str, str, str]] = {
    "EV-ACTIONS": (
        "/dependencies/github_actions",
        "exact SHA-pinned Action occurrences",
        "dependency inventory",
    ),
    "EV-AUDIT-HARNESS": (
        "/audit_implementation",
        "content-addressed Phase-A harness bytes",
        "audit implementation",
    ),
    "EV-BUILD-COMMANDS": (
        "/build_command_inventory",
        "25 exact repository entrypoint records",
        "command inventory",
    ),
    "EV-CI": ("/ci", "exact workflow and existing-run boundary", "CI inventory"),
    "EV-CI-CMM-GATE": ("/ci/jobs/3", "CMM guardrail job semantics", "CI truth table"),
    "EV-CI-STATIC-COMMANDS": ("/ci/jobs/0", "static required job commands", "CI truth table"),
    "EV-CI-WINDOWS-LANES": (
        "/ci/jobs",
        "Windows core/manual rows at indices 6 and 7",
        "CI truth table",
    ),
    "EV-CLASSIFICATIONS-ACCEPTED": (
        "/classifications/accepted_behaviors",
        "accepted behavior evidence",
        "classifications",
    ),
    "EV-CONFIDENTIALITY": (
        "/confidentiality",
        "sanitized-fixture and credential boundary",
        "confidentiality",
    ),
    "EV-DEPENDABOT-GROUPING": (
        "/dependencies/dependabot_grouping",
        "grouped dependency policy",
        "dependency inventory",
    ),
    "EV-ENVIRONMENT": (
        "/environment",
        "captured and repository environment identities",
        "environment",
    ),
    "EV-ISSUE-EVIDENCE": (
        "/durable_issue_evidence",
        "focused and reused authoritative Issue evidence",
        "Issue evidence",
    ),
    "EV-PACKAGING": (
        "/packaging",
        "per-packager manifest and resource contract",
        "packaging contract",
    ),
    "EV-PACKAGING-EXPLICIT-ASSETS": (
        "/packaging/resources",
        "explicit resource rows and destinations",
        "packaging resources",
    ),
    "EV-PACKAGING-HIDDEN-IMPORTS": (
        "/packaging/pyinstaller",
        "exact PyInstaller import/data collection",
        "PyInstaller contract",
    ),
    "EV-PACKAGING-MANUALS": (
        "/packaging/resources",
        "manual resource row and bounded secondary inventory",
        "packaging resources",
    ),
    "EV-PACKAGING-NOTICES": (
        "/packaging/resources",
        "notice/inventory resource rows",
        "packaging resources",
    ),
    "EV-PACKAGING-OCR-MODELS": (
        "/packaging/resources",
        "three exact OCR model rows",
        "packaging resources",
    ),
    "EV-PACKAGING-PARSER-PROFILES": (
        "/scope/secondary_paths",
        "bounded parser-profile consumer inventory",
        "secondary paths",
    ),
    "EV-PACKAGING-PROVENANCE": (
        "/version_identity_matrix",
        "PyInstaller versus Nuitka provenance matrix",
        "version identity",
    ),
    "EV-PACKAGING-QT": ("/packaging/resources", "Qt plugin resource row", "packaging resources"),
    "EV-PACKAGING-WINDOWS-PREREQUISITE": (
        "/packaging/windows_prerequisite",
        "VC redistributable prerequisite boundary",
        "packaging contract",
    ),
    "EV-PLATFORM": (
        "/platform_failure_matrix",
        "platform/failure execution matrix",
        "platform matrix",
    ),
    "EV-PLATFORM-MANUAL-RELEASE": (
        "/platform_failure_matrix/12",
        "manual-lane conditional boundary",
        "platform matrix",
    ),
    "EV-PR972": (
        "/pr_972",
        "exact PR #972 Action-update and existing-run evidence",
        "PR 972 matrix",
    ),
    "EV-PR973": (
        "/pr_973",
        "exact PR #973 declaration/resolution/family evidence",
        "PR 973 matrix",
    ),
    "EV-PRECOMMIT-EXTERNAL": (
        "/dependencies/pre_commit_external",
        "external hook revisions",
        "dependency inventory",
    ),
    "EV-RUST-MANIFEST-LOCK": (
        "/dependencies/rust",
        "five exact manifest and per-lock inventories",
        "dependency inventory",
    ),
    "EV-SCOPE-CONTRACT": ("/scope", "baseline ledger expansion and wave-report contract", "scope"),
    "EV-SECONDARY-REGRESSION-SURFACES": (
        "/scope/secondary_paths",
        "bounded relevant regression surfaces",
        "secondary paths",
    ),
    "EV-VERSION-COMPAT": (
        "/version_identity_matrix",
        "release/build identity producers and consumers",
        "version identity",
    ),
    "EV-WINDOWS-SETUP-COMMAND": (
        "/build_command_inventory",
        "exact Windows setup/build entrypoints",
        "command inventory",
    ),
}


def _evidence_anchor(reference: str) -> str:
    return "evidence-" + re.sub(r"[^a-z0-9]+", "-", reference.lower()).strip("-")


def _falsifier_inventory(audit_refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    classifications = {
        "missing-packaged-asset": "production negative test plus audit mutation",
        "repository-root-only-import": "production positive boundary plus audit mutation",
        "misleading-native-fallback": "structural production support plus synthetic audit mutation",
        "new-static-finding": "observed PR #973 Ruff/policy nonzero plus audit mutation",
        "zero-exit-no-artifact": "production negative test plus audit mutation",
        "stale-partial-artifact": "production negative tests plus audit mutation",
        "import-green-workflow-broken": "observed PR #973 policy failures plus audit mutation",
        "upstream-required-job-skip": "observed exact-base skip propagation plus audit mutation",
        "warm-cache-only": "synthetic seam only; production warm-only failure not reproduced",
        "shallow-history": "production nested negative test plus audit mutation",
        "path-permission-boundary": "production staging success plus POSIX audit mutation; Windows ACL unavailable",
        "missing-tool-optional-dependency": "production required-dependency negative test plus audit mutation",
        "stale-same-release-provenance": "exact production validation gap plus synthetic stale-identity audit mutation",
        "sensitive-diagnostic-output": "exact production payload inspection plus synthetic redaction audit mutation",
        "interrupted-model-fetch-cleanup": "exact production cleanup-path inspection plus synthetic residue audit mutation",
    }
    pr973_observation_ids = {"new-static-finding", "import-green-workflow-broken"}
    rows: list[dict[str, Any]] = []
    for control in FALSIFIERS:
        result = control["result"]
        if control["id"] == "warm-cache-only":
            result = "not independently reproduced; synthetic detection seam only"
        rows.append(
            {
                **control,
                "result": result,
                "control_class": classifications[control["id"]],
                "harness_exit_code": 0,
                "subject_outcome": control["expected_diagnostic"],
                "subject_refs": [
                    BASELINE_SUBJECT_REF,
                    *([PR973_SUBJECT_REF] if control["id"] in pr973_observation_ids else []),
                ],
                "production_blob_refs": _baseline_blob_refs(control["source_paths"]),
                "audit_mutation_refs": [dict(ref) for ref in audit_refs],
            }
        )
    return rows


def _discovery_probe_inventory(
    audit_refs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    pytest_harness_ids = {"DP-HISTORY-SHALLOW", "DP-OCR-HASH-DELETE", "DP-PATH-BOUNDARIES"}
    rows: list[dict[str, Any]] = []
    for probe in DISCOVERY_PROBES:
        subject_exit_code = probe["exit_code"]
        subject_outcome = probe["result"]
        if probe["id"] == "DP-OCR-HASH-DELETE":
            subject_exit_code = None
            subject_outcome = (
                "three hashes matched; deleted model produced the expected validator exception"
            )
        elif probe["id"] == "DP-PATH-BOUNDARIES":
            subject_exit_code = None
            subject_outcome = "positive portable-path round trip passed and read-only target produced the expected exception"
        if not probe["exact_argv_retained"]:
            harness_exit_code: int | None = None
        elif probe["id"] in pytest_harness_ids:
            harness_exit_code = 0
        else:
            harness_exit_code = subject_exit_code
        rows.append(
            {key: value for key, value in probe.items() if key != "exit_code"}
            | {
                "harness_exit_code": harness_exit_code,
                "subject_exit_code": subject_exit_code,
                "subject_outcome": subject_outcome,
                "exit_semantics": (
                    "listed pytest harness passed while asserting a nested negative outcome"
                    if probe["id"] in pytest_harness_ids
                    else (
                        "original command not retained; subject exit is an observational record"
                        if not probe["exact_argv_retained"]
                        else "listed command exit code"
                    )
                ),
                "production_blob_refs": _baseline_blob_refs(probe.get("production_paths", [])),
                "audit_record_refs": [dict(ref) for ref in audit_refs],
                "durably_reproducible": False,
                "replay_boundary": (
                    "exact argv retained, but isolated environments/caches/artifacts are ephemeral and Python declarations are not fully locked"
                    if probe["exact_argv_retained"]
                    else "exact aggregate/original argv was not retained; use cited child rows or treat the result as observational"
                ),
            }
        )
    return rows


def _collect_evidence_refs(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence_refs" and isinstance(child, list):
                references.update(str(item) for item in child)
            else:
                references.update(_collect_evidence_refs(child))
    elif isinstance(value, list):
        for child in value:
            references.update(_collect_evidence_refs(child))
    return references


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise AuditError(f"invalid JSON pointer: {pointer}")
    current = document
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?:[^01]|$)", raw_token):
            raise AuditError(f"invalid JSON pointer escape in {pointer}")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise AuditError(f"JSON pointer does not resolve: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
                raise AuditError(f"invalid JSON array index in pointer: {pointer}")
            index = int(token)
            if index >= len(current):
                raise AuditError(f"JSON pointer array index is out of range: {pointer}")
            current = current[index]
        else:
            raise AuditError(f"JSON pointer traverses a scalar: {pointer}")
    return current


def _structured_provenance_map(
    evidence: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    baseline = {
        "kind": "git_tree",
        "repository": "hexafe/metroliza",
        "ref": "develop",
        "commit": BASELINE_SHA,
        "tree": BASELINE_TREE,
    }
    pr973 = {
        "kind": "git_tree",
        "repository": "hexafe/metroliza",
        "ref": "PR #973 head",
        "commit": PR973_SHA,
        "tree": PR973_TREE,
    }
    pr972 = {
        "kind": "git_tree",
        "repository": "hexafe/metroliza",
        "ref": "PR #972 head",
        "commit": PR972_SHA,
        "tree": PR972_TREE,
    }
    pr_input_parent = {
        "kind": "git_tree",
        "repository": "hexafe/metroliza",
        "ref": "common parent of PR #972 and PR #973",
        "commit": PR_INPUT_PARENT_SHA,
        "tree": PR_INPUT_PARENT_TREE,
    }
    capture = {
        "kind": "phase_a_local_capture",
        "date": CAPTURE_DATE,
        "platform": CAPTURED_ENVIRONMENT["capture_platform"],
        "runtime_model": RUNTIME_IDENTITY["runtime_model"],
        "runtime_reasoning": RUNTIME_IDENTITY["runtime_reasoning"],
    }
    hosted_run = {
        "kind": "public_github_actions_run",
        "run_id": 33151703847,
        "head_sha": BASELINE_SHA,
        "url": "https://github.com/hexafe/metroliza/actions/runs/33151703847",
        "access": "read-only; not dispatched by Phase A",
    }
    pr972_runs = [
        {
            "kind": "public_github_actions_run",
            "run_id": run_id,
            "head_sha": PR972_SHA,
            "conclusion": "success",
            "url": f"https://github.com/hexafe/metroliza/actions/runs/{run_id}",
            "access": "read-only; not dispatched by Phase A",
        }
        for run_id in (32932158352, 32932162551)
    ]
    pr973_runs = [
        {
            "kind": "public_github_actions_run",
            "run_id": run_id,
            "head_sha": PR973_SHA,
            "conclusion": "failure",
            "url": f"https://github.com/hexafe/metroliza/actions/runs/{run_id}",
            "access": "read-only; not dispatched by Phase A",
        }
        for run_id in (32932367574, 32932363678)
    ]
    audit_content = [{"kind": "phase_a_content", **ref} for ref in evidence["audit_implementation"]]
    issue_evidence = [
        {
            "kind": "public_github_issue_url_reference",
            "issue": row["issue"],
            "url": row["evidence_url"],
            "observed_at": row["observed_at"],
            "binding": row["binding"],
        }
        for row in evidence["durable_issue_evidence"]
    ]

    provenance = {
        "EV-ACTIONS": [baseline],
        "EV-AUDIT-HARNESS": audit_content,
        "EV-BUILD-COMMANDS": [baseline],
        "EV-CI": [baseline, hosted_run],
        "EV-CI-CMM-GATE": [baseline],
        "EV-CI-STATIC-COMMANDS": [baseline],
        "EV-CI-WINDOWS-LANES": [baseline, hosted_run],
        "EV-CLASSIFICATIONS-ACCEPTED": [baseline, capture],
        "EV-CONFIDENTIALITY": [capture, hosted_run],
        "EV-DEPENDABOT-GROUPING": [baseline, pr973],
        "EV-ENVIRONMENT": [baseline, capture],
        "EV-ISSUE-EVIDENCE": issue_evidence,
        "EV-PACKAGING": [baseline, pr973, capture],
        "EV-PACKAGING-EXPLICIT-ASSETS": [baseline],
        "EV-PACKAGING-HIDDEN-IMPORTS": [baseline],
        "EV-PACKAGING-MANUALS": [baseline],
        "EV-PACKAGING-NOTICES": [baseline],
        "EV-PACKAGING-OCR-MODELS": [baseline, capture],
        "EV-PACKAGING-PARSER-PROFILES": [baseline],
        "EV-PACKAGING-PROVENANCE": [baseline, capture],
        "EV-PACKAGING-QT": [baseline, pr973, capture],
        "EV-PACKAGING-WINDOWS-PREREQUISITE": [baseline],
        "EV-PLATFORM": [baseline, pr973, hosted_run, capture, *audit_content],
        "EV-PLATFORM-MANUAL-RELEASE": [baseline],
        "EV-PR972": [pr_input_parent, pr972, capture, *pr972_runs],
        "EV-PR973": [pr_input_parent, baseline, pr973, capture, *pr973_runs],
        "EV-PRECOMMIT-EXTERNAL": [baseline, pr973],
        "EV-RUST-MANIFEST-LOCK": [baseline, pr973, capture],
        "EV-SCOPE-CONTRACT": [baseline, *audit_content],
        "EV-SECONDARY-REGRESSION-SURFACES": [baseline, *audit_content],
        "EV-VERSION-COMPAT": [baseline, capture],
        "EV-WINDOWS-SETUP-COMMAND": [baseline],
    }
    if set(provenance) != set(EVIDENCE_POINTERS):
        raise AuditError("structured evidence provenance map is incomplete")
    return provenance


def _add_registry_record(
    registry: dict[str, dict[str, Any]], reference: str, **record: Any
) -> None:
    if reference in registry:
        raise AuditError(f"duplicate evidence registry ID: {reference}")
    registry[reference] = {
        "id": reference,
        "report_anchor": _evidence_anchor(reference),
        **record,
    }


def _add_structured_registry_records(
    registry: dict[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    structured_provenance = _structured_provenance_map(evidence)
    for reference, (pointer, binding, anchor_label) in EVIDENCE_POINTERS.items():
        target = resolve_json_pointer(evidence, pointer)
        target_bytes = (
            json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        _add_registry_record(
            registry,
            reference,
            kind="structured audit section",
            json_pointer=pointer,
            binding=binding,
            result="see exact structured record",
            report_section=anchor_label,
            provenance_refs=structured_provenance[reference],
            resolved_target_type=type(target).__name__,
            resolved_target_sha256=hashlib.sha256(target_bytes).hexdigest(),
        )


def _add_primary_path_registry_records(
    registry: dict[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    for index, record in enumerate(evidence["scope"]["paths"]):
        _add_registry_record(
            registry,
            f"EV-PATH:{record['path']}",
            kind="primary baseline blob",
            json_pointer=f"/scope/paths/{index}",
            binding=(
                f"{BASELINE_SHA}:{record['path']} blob={record['git_blob_sha1']} "
                f"sha256={record['content_sha256']} bytes={record['size_bytes']}"
            ),
            result=record["disposition"],
            report_section="primary path inventory",
            baseline_ref=f"{BASELINE_SHA}:{record['path']}",
        )
        if (
            record["path"] in evidence["dependencies"]["python_manifests"]
            or record["path"] == "pyproject.toml"
        ):
            _add_registry_record(
                registry,
                f"EV-PYTHON-MANIFEST:{record['path']}",
                kind="Python declaration baseline blob",
                json_pointer=f"/scope/paths/{index}",
                binding=f"exact declaration source {record['git_blob_sha1']} / {record['content_sha256']}",
                result="parsed under /dependencies/python_manifests or pyproject policy",
                report_section="dependency inventory",
                baseline_ref=f"{BASELINE_SHA}:{record['path']}",
            )
        if record["path"].endswith(("Cargo.toml", "Cargo.lock")):
            _add_registry_record(
                registry,
                f"EV-RUST-MANIFEST-LOCK:{record['path']}",
                kind="Rust manifest/lock baseline blob",
                json_pointer=f"/scope/paths/{index}",
                binding=f"exact Rust source {record['git_blob_sha1']} / {record['content_sha256']}",
                result="parsed without cross-lock overwrite",
                report_section="dependency inventory",
                baseline_ref=f"{BASELINE_SHA}:{record['path']}",
            )


def _add_secondary_path_registry_records(
    registry: dict[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    for index, record in enumerate(evidence["scope"]["secondary_paths"]):
        _add_registry_record(
            registry,
            f"EV-SECONDARY-PATH:{record['path']}",
            kind="secondary baseline path" if record["tracked"] else "untracked contract path",
            json_pointer=f"/scope/secondary_paths/{index}",
            binding=(
                f"{BASELINE_SHA}:{record['path']} blob={record['git_blob_sha1']} "
                f"sha256={record['content_sha256']}"
                if record["tracked"]
                else record["missing_reason"]
            ),
            result=record["execution_status"],
            report_section="secondary path inventory",
            baseline_ref=f"{BASELINE_SHA}:{record['path']}" if record["tracked"] else None,
        )


def _add_probe_registry_records(
    registry: dict[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    for index, probe in enumerate(evidence["discovery_probes"]):
        _add_registry_record(
            registry,
            probe["id"],
            kind="discovery probe",
            json_pointer=f"/discovery_probes/{index}",
            binding=(
                f"command={probe['command']}; cwd={probe['cwd']}; "
                f"exact_argv_retained={probe['exact_argv_retained']}; "
                f"durably_reproducible={probe['durably_reproducible']}"
            ),
            result=probe["result"],
            report_section="discovery probes",
            subject_refs=probe["subject_refs"],
            audit_record_refs=probe["audit_record_refs"],
        )


def _add_control_registry_records(
    registry: dict[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    for index, control in enumerate(evidence["falsification"]["controls"]):
        _add_registry_record(
            registry,
            f"NC-{control['id']}",
            kind="negative control",
            json_pointer=f"/falsification/controls/{index}",
            binding=f"command={control['command']}; production={control['production_gate']}; negative={control['negative_control']}",
            result=control["result"],
            report_section="negative controls",
            subject_refs=control["subject_refs"],
            production_blob_refs=control["production_blob_refs"],
            audit_mutation_refs=control["audit_mutation_refs"],
        )


def _bind_registry_targets(
    registry: Mapping[str, dict[str, Any]], evidence: Mapping[str, Any]
) -> None:
    for record in registry.values():
        target = resolve_json_pointer(evidence, record["json_pointer"])
        target_bytes = (
            json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        resolved_sha256 = hashlib.sha256(target_bytes).hexdigest()
        if record.get("resolved_target_sha256", resolved_sha256) != resolved_sha256:
            raise AuditError(f"evidence target hash drifted: {record['id']}")
        record["resolved_target_type"] = type(target).__name__
        record["resolved_target_sha256"] = resolved_sha256


def _build_evidence_registry(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    _add_structured_registry_records(registry, evidence)
    _add_primary_path_registry_records(registry, evidence)
    _add_secondary_path_registry_records(registry, evidence)
    _add_probe_registry_records(registry, evidence)
    _add_control_registry_records(registry, evidence)
    _bind_registry_targets(registry, evidence)
    referenced = _collect_evidence_refs(evidence)
    unresolved = sorted(referenced - set(registry))
    if unresolved:
        raise AuditError("unresolved evidence reference(s): " + ", ".join(unresolved))
    return {reference: registry[reference] for reference in sorted(registry)}


def require_phase_a_packet_checkout() -> None:
    """Apply the one-shot branch/path guard only when explicitly requested by Phase A."""
    require_execution_checkout(
        ROOT,
        baseline_sha=BASELINE_SHA,
        expected_branch=BRANCH,
        allowed_paths=AUTHORIZED_PHASE_A_PATHS,
    )


def baseline_object_available() -> bool:
    completed = _run_git_completed(["cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"])
    return completed.returncode == 0


def exact_input_objects_available() -> bool:
    return all(
        _run_git_completed(["cat-file", "-e", f"{commit}^{{commit}}"]).returncode == 0
        for commit in (
            BASELINE_SHA,
            PR_INPUT_PARENT_SHA,
            PR972_SHA,
            PR973_SHA,
        )
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        lexical = Path(os.path.abspath(path))
        root = Path(os.path.abspath(ROOT))
        temp_root = Path(os.path.abspath(tempfile.gettempdir()))
        if lexical != root and root in lexical.parents:
            relative = lexical.relative_to(root).as_posix()
            content, mode = _read_rooted_regular_file(ROOT, relative, label=label)
        elif lexical != temp_root and temp_root in lexical.parents:
            relative = lexical.relative_to(temp_root).as_posix()
            content, mode = _read_rooted_regular_file(temp_root, relative, label=label)
        else:
            raise AuditError(f"{label} must be rooted below the repository or temp root")
        if mode != 0o644:
            raise AuditError(f"{label} mode is not exact 0644")
        payload = json.loads(
            content.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_strict_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuditError(f"unable to read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuditError(f"{label} must be a JSON object: {path}")
    return payload


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise AuditError(
            f"{label} schema keys drifted: expected {sorted(expected)}, got {sorted(actual)}"
        )


def _require_exact_json_value(actual: Any, expected: Any, *, label: str) -> None:
    """Reject JSON values that compare equal while having a different exact type/shape."""
    if type(actual) is not type(expected):
        raise AuditError(f"{label} exact JSON type drifted")
    if isinstance(expected, dict):
        _require_exact_keys(actual, frozenset(expected), label=label)
        for key, expected_value in expected.items():
            _require_exact_json_value(actual[key], expected_value, label=f"{label}.{key}")
        return
    if isinstance(expected, list):
        if len(actual) != len(expected):
            raise AuditError(f"{label} exact JSON list length drifted")
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected, strict=True)):
            _require_exact_json_value(
                actual_value,
                expected_value,
                label=f"{label}[{index}]",
            )
        return
    if actual != expected:
        raise AuditError(f"{label} exact JSON value drifted")


def _validation_receipt_origin() -> dict[str, Any]:
    return {
        "agent_id": "HD-976-BUILD",
        "kind": "local fail-closed execution-harness receipt",
        "executor": "scripts/quality/audit_build_delivery.py --create-validation-receipt",
        "execution_output_boundary": (
            "every exact child invocation was executed without a shell; per-invocation "
            "stdout/stderr SHA-256 and byte counts are retained; successful raw streams are "
            "not duplicated in the four-file packet, while a failing child emits bounded tails; "
            "parser-root logical operands are retained for reporting but execute only through "
            "role-checked held descriptor aliases"
        ),
        "automatic_retargeting": False,
        "regeneration_rule": (
            "any source/test byte, held executable, copied Python runtime, validation-checkout "
            "content/identity manifest, held parser-smoke portable content/mode ref or live "
            "descriptor/inode guard, or pinned "
            "security materialization content/identity manifest change invalidates this receipt; "
            "a new receipt is written only after every exact child invocation exits zero"
        ),
    }


def _unwrap_validation_env(
    argv: list[str], environment: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    if not argv or argv[0] != "env":
        return argv, environment
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "-u":
            if index + 1 >= len(argv) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", argv[index + 1]
            ):
                raise AuditError("validation env wrapper has a malformed -u operand")
            environment.pop(argv[index + 1], None)
            index += 2
            continue
        if "=" not in token:
            break
        key, value = token.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise AuditError("validation env wrapper has a malformed assignment")
        environment[key] = value
        index += 1
    return argv[index:], environment


def _direct_validation_invocation(display: str) -> tuple[list[str], dict[str, str]]:
    argv, environment = _unwrap_validation_env(
        shlex.split(display),
        dict(VALIDATION_EXECUTION_ENV),
    )
    if not argv:
        raise AuditError("validation invocation has no direct executable")
    if argv[0] == "git":
        argv = ["/usr/bin/git", *GIT_CONFIG_OVERRIDES, *argv[1:]]
    elif argv[0] == str(CAPTURE_BASELINE_PYTHON):
        argv[0] = str(CAPTURE_VALIDATION_PYTHON)
    allowed = {str(row["argv_path"]) for row in BOUND_EXECUTABLES}
    if argv[0] not in allowed:
        raise AuditError(f"validation invocation uses an unbound executable: {argv[0]}")
    return argv, dict(sorted(environment.items()))


def _validation_invocation_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    sequence = 0
    for group_index, group in enumerate(CAPTURED_VALIDATION):
        for invocation_index, display in enumerate(group["argv"]):
            sequence += 1
            argv, environment = _direct_validation_invocation(display)
            executable_ref = next(
                dict(row) for row in BOUND_EXECUTABLES if row["argv_path"] == argv[0]
            )
            specs.append(
                {
                    "sequence": sequence,
                    "group_index": group_index,
                    "invocation_index": invocation_index,
                    "command": group["command"],
                    "argv": argv,
                    "argv_display": display,
                    "cwd": group["cwd"],
                    "environment": environment,
                    "executable_ref": executable_ref,
                    "observed_at": VALIDATION_GATE_DATE,
                }
            )
    return specs


def _validation_plan_sha256() -> str:
    payload = {
        "groups": list(CAPTURED_VALIDATION),
        "invocations": _validation_invocation_specs(),
        "execution_tools": [dict(row) for row in BOUND_EXECUTABLES],
        "validation_checkout": {
            "materialized_root": str(CAPTURE_AUDIT_CWD),
            "commit": BASELINE_SHA,
            "tree": BASELINE_TREE,
            "overlay_paths": list(VALIDATION_OVERLAY_PATHS),
            "mode": "private 0700 root with recursively read-only .git; standalone no-hardlink clone with exact portable and identity manifests plus one identity-bound external test.db symlink and target",
        },
        "python_runtime": {
            "materialized_root": str(CAPTURE_VALIDATION_RUNTIME),
            "source_base": str(CAPTURE_RUNTIME_SOURCE_BASE),
            "source_venv": str(CAPTURE_RUNTIME_SOURCE_VENV),
            "complete_portable_closure_pin": _expected_python_runtime_closure(),
            "mode": "private 0500 root; recursively read-only no-hardlink runtime closure matching an independently reviewed complete portable-manifest pin",
            "user_site": "disabled by PYTHONNOUSERSITE=1",
        },
        "parser_smoke_inputs": {
            "materialized_root": str(CAPTURE_PARSER_SMOKE_ROOT),
            "static_fixtures": [
                {
                    "path": "workspace/expected_results.csv",
                    "content_sha256": hashlib.sha256(PARSER_EXPECTED_RESULTS_CONTENT).hexdigest(),
                    "size_bytes": len(PARSER_EXPECTED_RESULTS_CONTENT),
                },
                {
                    "path": "workspace/samples/sample_report_01.csv",
                    "content_sha256": hashlib.sha256(PARSER_SAMPLE_REPORT_CONTENT).hexdigest(),
                    "size_bytes": len(PARSER_SAMPLE_REPORT_CONTENT),
                },
            ],
            "generated_profile": "workspace/profile.yaml is exclusively reserved empty, populated through its held writable descriptor by init, then reopened read-only for later parser children",
            "invocation_descriptor_roles": {
                "0": ["profile output"],
                "1": ["profile", "expected results", "frozen workspace/sample tree"],
                "2": ["profile", "sample"],
                "3": ["home", "profile", "expected results", "frozen workspace/sample tree"],
                "4": ["home"],
            },
            "installed_evidence_inputs": "profile and approval captured after install, retained open and frozen below mode-0500 ancestors for evidence",
            "binding": "logical lexical argv is retained in the receipt, while every parser-root runtime operand is rewritten to a held /proc/self/fd alias and exact live identities/content are checked around each child",
        },
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _expected_security_materialization_refs() -> list[dict[str, Any]]:
    return [
        {
            "repository": expected["repository"],
            "directory": expected["directory"],
            "commit": expected["commit"],
            "tree": expected["tree"],
            "materialized_root": str(CAPTURE_SECURITY_MATERIALIZED),
            "mode": "private 0500 root; recursively read-only standalone no-hardlink clone",
        }
        for expected in SECURITY_SIBLING_SUBJECTS
    ]


def _validate_security_materialization_refs(raw: Any) -> list[dict[str, Any]]:
    expected_refs = _expected_security_materialization_refs()
    if not isinstance(raw, list) or len(raw) != len(expected_refs):
        raise AuditError("validation security materialization refs are incomplete")
    validated: list[dict[str, Any]] = []
    dynamic_keys = frozenset(
        {
            "filesystem_manifest_sha256",
            "filesystem_identity_sha256",
            "filesystem_entry_count",
            "standalone",
        }
    )
    for index, (row, expected) in enumerate(zip(raw, expected_refs, strict=True)):
        if not isinstance(row, dict):
            raise AuditError("validation security materialization ref must be an object")
        _require_exact_keys(
            row,
            frozenset(expected) | dynamic_keys,
            label=f"validation security materialization ref {index}",
        )
        for key, expected_value in expected.items():
            _require_exact_json_value(
                row.get(key),
                expected_value,
                label=f"validation security materialization ref {index}.{key}",
            )
        digest = row.get("filesystem_manifest_sha256")
        identity_digest = row.get("filesystem_identity_sha256")
        entry_count = row.get("filesystem_entry_count")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AuditError("validation security materialization manifest digest is malformed")
        if not isinstance(identity_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", identity_digest
        ):
            raise AuditError("validation security materialization identity digest is malformed")
        if type(entry_count) is not int or entry_count <= 0:
            raise AuditError("validation security materialization entry count is malformed")
        if row.get("standalone") != "no remotes, alternates, ignored files or untracked files":
            raise AuditError("validation security materialization standalone proof drifted")
        validated.append(dict(row))
    return validated


def _manifest_identity_record(metadata: os.stat_result) -> dict[str, int]:
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "mode_bits": metadata.st_mode,
        "link_count": metadata.st_nlink,
        "size_bytes": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
    }


def _regular_manifest_record(
    path: Path,
    relative: str,
    before: os.stat_result,
    mode: int,
    *,
    label: str,
    immutable: bool,
    require_single_link: bool,
) -> dict[str, Any]:
    if immutable and mode not in (0o444, 0o555):
        raise AuditError(f"{label} regular-file mode drifted at {relative}: {mode:04o}")
    if not immutable and (mode & 0o022 or mode & 0o7000):
        raise AuditError(f"{label} unsafe regular-file mode at {relative}: {mode:04o}")
    if require_single_link and before.st_nlink != 1:
        raise AuditError(f"{label} hard-linked regular file refused at {relative}")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(opened, field) != getattr(before, field) for field in stable_fields):
            raise AuditError(f"{label} entry identity changed at {relative}")
        content = _read_stable_descriptor(descriptor, label=f"{label} {relative}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    lexical_after = path.lstat()
    stable = all(
        getattr(left, field) == getattr(right, field)
        for left, right in ((before, after), (after, lexical_after))
        for field in stable_fields
    )
    if not stable:
        raise AuditError(f"{label} regular file changed at {relative}")
    return {
        "path": relative,
        "mode": f"{mode:04o}",
        "type": "regular",
        "size_bytes": len(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "link_count": after.st_nlink,
        "_identity": _manifest_identity_record(after),
    }


def _symlink_manifest_record(
    path: Path,
    relative: str,
    before: os.stat_result,
    mode: int,
    *,
    label: str,
    resolved_root: Path,
    allowed_external_symlinks: Mapping[str, str],
) -> dict[str, Any]:
    target = os.readlink(path)
    allowed_external_target = allowed_external_symlinks.get(relative)
    if allowed_external_target is not None:
        if target != allowed_external_target or not Path(target).is_absolute():
            raise AuditError(f"{label} external symlink target drifted at {relative}")
    else:
        if Path(target).is_absolute():
            raise AuditError(f"{label} absolute symlink refused at {relative}")
        try:
            resolved_target = path.resolve(strict=True)
            resolved_target.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise AuditError(f"{label} escaping symlink refused at {relative}") from exc
    after = path.lstat()
    if (
        _manifest_identity_record(after) != _manifest_identity_record(before)
        or os.readlink(path) != target
    ):
        raise AuditError(f"{label} symlink changed at {relative}")
    return {
        "path": relative,
        "mode": f"{mode:04o}",
        "type": "symlink",
        "target": target,
        "_identity": _manifest_identity_record(after),
    }


def _manifest_children(
    path: Path,
    relative: str,
    *,
    label: str,
) -> list[tuple[Path, str]]:
    try:
        children = sorted(path.iterdir(), key=lambda child: os.fsencode(child.name))
    except OSError as exc:
        raise AuditError(f"unable to enumerate {label} at {relative}: {exc}") from exc
    return [
        (child, child.name if relative == "." else f"{relative}/{child.name}") for child in children
    ]


def _append_manifest_entry(
    path: Path,
    relative: str,
    entries: list[dict[str, Any]],
    *,
    label: str,
    resolved_root: Path,
    root_mode: int,
    immutable: bool,
    require_single_link: bool,
    allowed_external_symlinks: Mapping[str, str],
) -> None:
    before = path.lstat()
    if before.st_uid != os.getuid():
        raise AuditError(f"{label} entry is not owned by the executing UID at {relative}")
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISREG(before.st_mode):
        entries.append(
            _regular_manifest_record(
                path,
                relative,
                before,
                mode,
                label=label,
                immutable=immutable,
                require_single_link=require_single_link,
            )
        )
        return
    if stat.S_ISLNK(before.st_mode):
        entries.append(
            _symlink_manifest_record(
                path,
                relative,
                before,
                mode,
                label=label,
                resolved_root=resolved_root,
                allowed_external_symlinks=allowed_external_symlinks,
            )
        )
        return
    if not stat.S_ISDIR(before.st_mode):
        raise AuditError(f"{label} special filesystem entry refused at {relative}")
    expected_mode = root_mode if relative == "." else (0o555 if immutable else None)
    if expected_mode is not None and mode != expected_mode:
        raise AuditError(f"{label} directory mode drifted at {relative}: {mode:04o}")
    if expected_mode is None and (mode & 0o022 or mode & 0o7000):
        raise AuditError(f"{label} unsafe directory mode at {relative}: {mode:04o}")
    entries.append(
        {
            "path": relative,
            "mode": f"{mode:04o}",
            "type": "directory",
            "_identity": _manifest_identity_record(before),
        }
    )
    for child, child_relative in _manifest_children(
        path,
        relative,
        label=label,
    ):
        _append_manifest_entry(
            child,
            child_relative,
            entries,
            label=label,
            resolved_root=resolved_root,
            root_mode=root_mode,
            immutable=immutable,
            require_single_link=require_single_link,
            allowed_external_symlinks=allowed_external_symlinks,
        )
    after = path.lstat()
    if _manifest_identity_record(after) != _manifest_identity_record(before):
        raise AuditError(f"{label} directory changed during enumeration at {relative}")


def _filesystem_manifests(
    root: Path,
    *,
    label: str,
    root_mode: int = 0o500,
    immutable: bool = True,
    require_single_link: bool = True,
    allowed_external_symlinks: Mapping[str, str] | None = None,
) -> tuple[str, int, str]:
    external_symlinks = {} if allowed_external_symlinks is None else allowed_external_symlinks
    entries: list[dict[str, Any]] = []
    _append_manifest_entry(
        root,
        ".",
        entries,
        label=label,
        resolved_root=root.resolve(strict=True),
        root_mode=root_mode,
        immutable=immutable,
        require_single_link=require_single_link,
        allowed_external_symlinks=external_symlinks,
    )
    observed_external_symlinks = {
        entry["path"]: entry["target"]
        for entry in entries
        if entry["type"] == "symlink" and entry["path"] in external_symlinks
    }
    if observed_external_symlinks != dict(external_symlinks):
        raise AuditError(f"{label} external symlink boundary drifted")
    portable_entries = [
        {key: value for key, value in entry.items() if key != "_identity"} for entry in entries
    ]
    identity_entries = [
        {
            "path": entry["path"],
            "type": entry["type"],
            **entry["_identity"],
            **({"target": entry["target"]} if entry["type"] == "symlink" else {}),
        }
        for entry in entries
    ]
    portable_encoded = (
        json.dumps(
            portable_entries,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    identity_encoded = (
        json.dumps(
            identity_entries,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return (
        hashlib.sha256(portable_encoded).hexdigest(),
        len(entries),
        hashlib.sha256(identity_encoded).hexdigest(),
    )


def _read_only_filesystem_manifest(
    root: Path,
    *,
    label: str,
    root_mode: int = 0o500,
) -> tuple[str, int, str]:
    return _filesystem_manifests(
        root,
        label=label,
        root_mode=root_mode,
        immutable=True,
    )


def _private_checkout_filesystem_manifest(
    root: Path,
    *,
    label: str,
) -> tuple[str, int, str, dict[str, int], dict[str, int]]:
    output_before = _validation_test_output_identity()
    manifest = _filesystem_manifests(
        root,
        label=label,
        root_mode=0o700,
        immutable=False,
        allowed_external_symlinks={"test.db": str(CAPTURE_VALIDATION_TEST_DB)},
    )
    output_after = _validation_test_output_identity()
    if output_after != output_before:
        raise AuditError("validation checkout external test-output identity changed")
    return (*manifest, output_after["root"], output_after["test_db"])


def _validation_test_output_identity() -> dict[str, dict[str, int]]:
    output_root = Path(CAPTURE_VALIDATION_TEST_OUTPUT_ROOT)
    runtime_output = Path(CAPTURE_VALIDATION_TEST_DB)
    if (
        not output_root.is_absolute()
        or not runtime_output.is_absolute()
        or runtime_output.parent != output_root
    ):
        raise AuditError("validation checkout external test.db path boundary drifted")
    root_fd, root_identity = _open_publication_root(output_root)
    output_fd: int | None = None
    try:
        root_metadata = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.getuid()
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
            or set(os.listdir(root_fd)) != {"test.db"}
        ):
            raise AuditError("validation checkout external test-output root boundary drifted")
        output_fd = os.open(
            "test.db",
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        output_metadata = os.fstat(output_fd)
        lexical_output = os.stat("test.db", dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(output_metadata.st_mode)
            or output_metadata.st_uid != os.getuid()
            or output_metadata.st_nlink != 1
            or stat.S_IMODE(output_metadata.st_mode) != 0o600
            or _stat_identity(output_metadata) != _stat_identity(lexical_output)
            or _stat_identity(os.fstat(root_fd)) != root_identity
            or _stat_identity(os.stat(output_root, follow_symlinks=False)) != root_identity
        ):
            raise AuditError("validation checkout external test.db boundary drifted")
        return {
            "root": {"device": root_identity[0], "inode": root_identity[1]},
            "test_db": {
                "device": output_metadata.st_dev,
                "inode": output_metadata.st_ino,
            },
        }
    except OSError as exc:
        raise AuditError(f"unable to bind validation test-output identity: {exc}") from exc
    finally:
        _close_descriptors(output_fd, root_fd)


def _require_standalone_materialization(repo: Path, *, label: str) -> None:
    _require_safe_local_git_config(repo, label=label)
    alternates = repo / ".git" / "objects" / "info" / "alternates"
    if alternates.exists() or alternates.is_symlink():
        raise AuditError(f"{label} uses a Git object alternates indirection")
    if _run_git(["remote"], cwd=repo) != b"":
        raise AuditError(f"{label} retains a Git remote")
    common_dir_raw = (
        _run_git(["rev-parse", "--git-common-dir"], cwd=repo)
        .decode("utf-8", errors="strict")
        .strip()
    )
    common_dir = Path(common_dir_raw)
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    if common_dir.resolve(strict=True) != (repo / ".git").resolve(strict=True):
        raise AuditError(f"{label} uses a non-standalone Git common directory")
    ignored_or_untracked = _run_git(
        ["status", "--porcelain=v1", "--untracked-files=all", "--ignored"],
        cwd=repo,
    )
    if ignored_or_untracked != b"":
        raise AuditError(f"{label} contains ignored or untracked materialization files")
    ignored_inventory = _run_git(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        cwd=repo,
    )
    if ignored_inventory != b"":
        raise AuditError(f"{label} contains ignored materialization files")


def _security_materialization_refs() -> list[dict[str, Any]]:
    root = Path(CAPTURE_SECURITY_MATERIALIZED)
    if not root.is_dir() or root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o500:
        raise AuditError("pinned security materialization root is unavailable or not immutable")
    refs: list[dict[str, Any]] = []
    for expected, expected_ref in zip(
        SECURITY_SIBLING_SUBJECTS,
        _expected_security_materialization_refs(),
        strict=True,
    ):
        repo = root / expected["directory"]
        if repo.is_symlink() or not repo.is_dir():
            raise AuditError(f"pinned security materialization is unavailable: {repo}")
        manifest_before = _read_only_filesystem_manifest(
            repo,
            label=f"pinned security materialization {expected['repository']}",
            root_mode=0o555,
        )
        _require_standalone_materialization(
            repo,
            label=f"pinned security materialization {expected['repository']}",
        )
        commit = _run_git(["rev-parse", "HEAD"], cwd=repo).decode("ascii").strip()
        tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=repo).decode("ascii").strip()
        status_output = _run_git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=repo)
        manifest_after = _read_only_filesystem_manifest(
            repo,
            label=f"pinned security materialization {expected['repository']}",
            root_mode=0o555,
        )
        if commit != expected["commit"] or tree != expected["tree"] or status_output != b"":
            raise AuditError(f"pinned security materialization identity drifted: {repo}")
        if manifest_after != manifest_before:
            raise AuditError(f"pinned security materialization changed during verification: {repo}")
        refs.append(
            {
                **expected_ref,
                "commit": commit,
                "tree": tree,
                "filesystem_manifest_sha256": manifest_after[0],
                "filesystem_entry_count": manifest_after[1],
                "filesystem_identity_sha256": manifest_after[2],
                "standalone": "no remotes, alternates, ignored files or untracked files",
            }
        )
    return refs


def _make_materialization_read_only(root: Path) -> None:
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            continue
        if stat.S_ISDIR(metadata.st_mode):
            path.chmod(0o555)
        elif stat.S_ISREG(metadata.st_mode):
            executable = stat.S_IMODE(metadata.st_mode) & 0o111 != 0
            path.chmod(0o555 if executable else 0o444)
    root.chmod(0o500)


def _distribution_name_version(content: bytes, *, relative: str) -> dict[str, str]:
    name: str | None = None
    version: str | None = None
    for line in content.decode("utf-8", errors="strict").splitlines():
        if line.startswith("Name: ") and name is None:
            name = line.removeprefix("Name: ").strip()
        elif line.startswith("Version: ") and version is None:
            version = line.removeprefix("Version: ").strip()
        if name is not None and version is not None:
            break
    if not name or not version:
        raise AuditError(f"validation Python distribution metadata is incomplete: {relative}")
    return {"name": name, "version": version}


def _python_distribution_inventory(runtime_root: Path) -> list[dict[str, str]]:
    site_packages = Path(CAPTURE_VALIDATION_RUNTIME_VENV) / "lib/python3.11/site-packages"
    try:
        relative_site = site_packages.relative_to(runtime_root)
    except ValueError as exc:  # pragma: no cover - fixed capture constants
        raise AuditError("validation Python site-packages escapes the runtime root") from exc
    inventory: list[dict[str, str]] = []
    for metadata_path in sorted(
        (runtime_root / relative_site).glob("*.dist-info/METADATA"),
        key=lambda path: os.fsencode(path.as_posix()),
    ):
        relative = metadata_path.relative_to(runtime_root).as_posix()
        content, mode = _read_rooted_regular_file(
            runtime_root,
            relative,
            label=f"validation Python distribution metadata {relative}",
        )
        if mode not in {0o444, 0o555}:
            raise AuditError(f"validation Python distribution metadata mode drifted: {relative}")
        inventory.append(_distribution_name_version(content, relative=relative))
    inventory.sort(key=lambda row: (row["name"].lower(), row["version"], row["name"]))
    if not inventory:
        raise AuditError("validation Python distribution inventory is empty")
    if len({row["name"].lower() for row in inventory}) != len(inventory):
        raise AuditError("validation Python distribution inventory has duplicate names")
    return inventory


def _require_safe_runtime_pth_files(runtime_root: Path) -> None:
    site_packages = Path(CAPTURE_VALIDATION_RUNTIME_VENV) / "lib/python3.11/site-packages"
    for pth_path in sorted(site_packages.glob("*.pth"), key=lambda path: os.fsencode(path.name)):
        relative = pth_path.relative_to(runtime_root).as_posix()
        content, mode = _read_rooted_regular_file(
            runtime_root,
            relative,
            label=f"validation Python .pth file {relative}",
        )
        if mode not in {0o444, 0o555}:
            raise AuditError(f"validation Python .pth mode drifted: {relative}")
        lines = content.decode("utf-8", errors="strict").splitlines()
        has_executable_line = any(
            line.strip().startswith(("import ", "import\t")) for line in lines
        )
        if has_executable_line and (
            RUNTIME_EXECUTABLE_PTH_ALLOWLIST.get(relative) != hashlib.sha256(content).hexdigest()
        ):
            raise AuditError(
                f"validation Python executable .pth content is not allowlisted: {relative}"
            )
        for line in lines:
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith(("import ", "import\t"))
            ):
                continue
            candidate = Path(stripped)
            if candidate.is_absolute():
                raise AuditError(f"validation Python .pth absolute path refused: {relative}")
            lexical_candidate = Path(os.path.normpath(pth_path.parent / candidate))
            try:
                lexical_candidate.relative_to(runtime_root)
            except ValueError as exc:
                raise AuditError(f"validation Python .pth escape refused: {relative}") from exc
            try:
                resolved = (pth_path.parent / candidate).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise AuditError(
                    f"validation Python .pth target is unavailable or indirect: {relative}"
                ) from exc
            try:
                resolved.relative_to(runtime_root)
            except ValueError as exc:
                raise AuditError(f"validation Python .pth escape refused: {relative}") from exc


def _parse_pyvenv_config(
    content: bytes,
    *,
    expected_home: Path,
    label: str,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        content.decode("utf-8", errors="strict").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise AuditError(f"{label} has a malformed line {line_number}")
        raw_key, raw_value = stripped.split("=", 1)
        key = raw_key.strip().casefold()
        value = raw_value.strip()
        if not key or not value or key in parsed:
            raise AuditError(f"{label} has an empty or duplicate key at line {line_number}")
        if key != "home" and ("/" in value or "\\" in value):
            raise AuditError(f"{label} has an external path-bearing value at {key}")
        parsed[key] = value
    required = {
        "home": str(expected_home),
        "implementation": "CPython",
        "version_info": "3.11.16",
        "include-system-site-packages": "false",
    }
    if any(parsed.get(key) != value for key, value in required.items()):
        raise AuditError(f"{label} effective configuration drifted")
    return parsed


def _render_rebound_pyvenv_config(content: bytes) -> bytes:
    parsed = _parse_pyvenv_config(
        content,
        expected_home=Path(CAPTURE_RUNTIME_SOURCE_BASE) / "bin",
        label="validation Python source pyvenv.cfg",
    )
    parsed["home"] = str(Path(CAPTURE_VALIDATION_RUNTIME_BASE) / "bin")
    return "".join(f"{key} = {value}\n" for key, value in parsed.items()).encode("utf-8")


def _expected_python_runtime_probe() -> dict[str, Any]:
    base = Path(CAPTURE_VALIDATION_RUNTIME_BASE)
    venv = Path(CAPTURE_VALIDATION_RUNTIME_VENV)
    return {
        "base_prefix": str(base),
        "enable_user_site": False,
        "prefix": str(venv),
        "site_packages": [str(venv / "lib/python3.11/site-packages")],
        "sys_path": [
            str(base / "lib/python311.zip"),
            str(base / "lib/python3.11"),
            str(base / "lib/python3.11/lib-dynload"),
            str(venv / "lib/python3.11/site-packages"),
        ],
    }


def _expected_python_runtime_closure() -> dict[str, Any]:
    return dict(PINNED_VALIDATION_RUNTIME_CLOSURE)


def _canonical_json_value_sha256(value: Any) -> str:
    encoded = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _expected_python_runtime_inventory_sha256() -> str:
    return PINNED_VALIDATION_RUNTIME_INVENTORY_SHA256


def _expected_python_runtime_inventory() -> list[dict[str, str]]:
    return [
        {"name": name, "version": version}
        for name, version in PINNED_VALIDATION_RUNTIME_DISTRIBUTIONS
    ]


def _probe_python_runtime(runtime_root: Path) -> dict[str, Any]:
    code = (
        "import json,site,sys;"
        "print(json.dumps({'base_prefix':sys.base_prefix,'enable_user_site':site.ENABLE_USER_SITE,"
        "'prefix':sys.prefix,'site_packages':site.getsitepackages(),'sys_path':sys.path},"
        "sort_keys=True,separators=(',',':')))"
    )
    with _bound_executable(str(CAPTURE_VALIDATION_PYTHON)) as (descriptor, _executable_ref):
        try:
            completed = subprocess.run(
                [str(CAPTURE_VALIDATION_PYTHON), "-c", code],
                executable=f"/proc/self/fd/{descriptor}",
                cwd=runtime_root,
                check=False,
                capture_output=True,
                env=dict(VALIDATION_EXECUTION_ENV),
                pass_fds=(descriptor,),
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuditError(f"validation Python runtime probe could not complete: {exc}") from exc
    if completed.returncode != 0 or completed.stderr != b"":
        raise AuditError("validation Python runtime probe failed")
    try:
        observed = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuditError("validation Python runtime probe output is malformed") from exc
    expected = _expected_python_runtime_probe()
    _require_exact_json_value(observed, expected, label="validation Python runtime probe")
    for entry in expected["sys_path"]:
        try:
            Path(entry).relative_to(runtime_root)
        except ValueError as exc:  # pragma: no cover - fixed expected capture paths
            raise AuditError("validation Python runtime sys.path escapes the private root") from exc
    return expected


def _python_runtime_ref() -> dict[str, Any]:
    root = Path(CAPTURE_VALIDATION_RUNTIME)
    if not root.is_dir() or root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o500:
        raise AuditError("validation Python runtime is unavailable or not immutable")
    manifest_before = _read_only_filesystem_manifest(
        root,
        label="validation Python runtime",
    )
    pyvenv_content, pyvenv_mode = _read_rooted_regular_file(
        root,
        "venv/pyvenv.cfg",
        label="validation Python pyvenv.cfg",
    )
    if pyvenv_mode != 0o444:
        raise AuditError("validation Python pyvenv.cfg mode drifted")
    observed_closure = {
        "pyvenv_cfg_sha256": hashlib.sha256(pyvenv_content).hexdigest(),
        "filesystem_manifest_sha256": manifest_before[0],
        "filesystem_entry_count": manifest_before[1],
    }
    _require_exact_json_value(
        observed_closure,
        _expected_python_runtime_closure(),
        label="validation Python independently pinned complete closure",
    )
    _parse_pyvenv_config(
        pyvenv_content,
        expected_home=Path(CAPTURE_VALIDATION_RUNTIME_BASE) / "bin",
        label="validation Python pyvenv.cfg",
    )
    python_link = root / "venv/bin/python"
    if not python_link.is_symlink() or os.readlink(python_link) != "../../base/bin/python3.11":
        raise AuditError("validation Python executable link is not exact and internal")
    _require_safe_runtime_pth_files(root)
    runtime_probe = _probe_python_runtime(root)
    inventory = _python_distribution_inventory(root)
    inventory_sha256 = _canonical_json_value_sha256(inventory)
    _require_exact_json_value(
        inventory,
        _expected_python_runtime_inventory(),
        label="validation Python independently pinned distribution inventory",
    )
    _require_exact_json_value(
        inventory_sha256,
        _expected_python_runtime_inventory_sha256(),
        label="validation Python independently pinned distribution inventory digest",
    )
    versions = {row["name"].lower(): row["version"] for row in inventory}
    expected_tools = {"mypy": "2.2.0", "pip": "26.2.1", "pytest": "9.1.1", "ruff": "0.15.10"}
    if {name: versions.get(name) for name in expected_tools} != expected_tools:
        raise AuditError("validation Python tool-version inventory drifted")
    with _bound_executable(str(CAPTURE_VALIDATION_PYTHON)) as (_descriptor, executable_ref):
        observed_executable = executable_ref
    manifest_after = _read_only_filesystem_manifest(
        root,
        label="validation Python runtime",
    )
    if manifest_after != manifest_before:
        raise AuditError("validation Python runtime changed during verification")
    return {
        "materialized_root": str(CAPTURE_VALIDATION_RUNTIME),
        "source_base": str(CAPTURE_RUNTIME_SOURCE_BASE),
        "source_venv": str(CAPTURE_RUNTIME_SOURCE_VENV),
        "python_version": "3.11.16",
        "pyvenv_cfg_sha256": observed_closure["pyvenv_cfg_sha256"],
        "distribution_inventory": inventory,
        "distribution_inventory_sha256": inventory_sha256,
        "tool_versions": expected_tools,
        "runtime_probe": runtime_probe,
        "executable_ref": observed_executable,
        "filesystem_manifest_sha256": observed_closure["filesystem_manifest_sha256"],
        "filesystem_entry_count": observed_closure["filesystem_entry_count"],
        "filesystem_identity_sha256": manifest_after[2],
        "mode": "private 0500 root; recursively read-only no-hardlink runtime closure matching the exact complete portable-manifest pin",
        "user_site": "disabled by PYTHONNOUSERSITE=1",
        "pth_policy": "executable files require exact path/content allowlisting; non-code entries resolve strictly within the runtime; effective sys.path is probed",
    }


def _validate_python_distribution_inventory(raw: Any, *, expected_sha256: Any) -> None:
    inventory = raw
    if not isinstance(inventory, list) or not inventory:
        raise AuditError("validation Python distribution inventory is malformed")
    for row in inventory:
        if not isinstance(row, dict):
            raise AuditError("validation Python distribution row is malformed")
        _require_exact_keys(
            row, frozenset({"name", "version"}), label="validation Python distribution row"
        )
        if not all(isinstance(row[key], str) and row[key] for key in ("name", "version")):
            raise AuditError("validation Python distribution row is incomplete")
    if _canonical_json_value_sha256(inventory) != expected_sha256:
        raise AuditError("validation Python distribution inventory hash is stale")
    _require_exact_json_value(
        inventory,
        _expected_python_runtime_inventory(),
        label="validation Python independently pinned distribution inventory",
    )


def _validate_python_runtime_ref(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AuditError("validation Python runtime ref must be an object")
    expected_static = {
        "materialized_root": str(CAPTURE_VALIDATION_RUNTIME),
        "source_base": str(CAPTURE_RUNTIME_SOURCE_BASE),
        "source_venv": str(CAPTURE_RUNTIME_SOURCE_VENV),
        "python_version": "3.11.16",
        **_expected_python_runtime_closure(),
        "distribution_inventory_sha256": _expected_python_runtime_inventory_sha256(),
        "tool_versions": {"mypy": "2.2.0", "pip": "26.2.1", "pytest": "9.1.1", "ruff": "0.15.10"},
        "runtime_probe": _expected_python_runtime_probe(),
        "executable_ref": dict(BOUND_EXECUTABLES[1]),
        "mode": "private 0500 root; recursively read-only no-hardlink runtime closure matching the exact complete portable-manifest pin",
        "user_site": "disabled by PYTHONNOUSERSITE=1",
        "pth_policy": "executable files require exact path/content allowlisting; non-code entries resolve strictly within the runtime; effective sys.path is probed",
    }
    dynamic = {
        "distribution_inventory",
        "filesystem_identity_sha256",
    }
    _require_exact_keys(
        raw, frozenset(expected_static) | frozenset(dynamic), label="validation Python runtime ref"
    )
    for key, value in expected_static.items():
        _require_exact_json_value(raw.get(key), value, label=f"validation Python runtime ref.{key}")
    for key in ("pyvenv_cfg_sha256", "filesystem_manifest_sha256", "filesystem_identity_sha256"):
        value = raw.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise AuditError(f"validation Python runtime {key} is malformed")
    if type(raw.get("filesystem_entry_count")) is not int or raw["filesystem_entry_count"] <= 0:
        raise AuditError("validation Python runtime entry count is malformed")
    _validate_python_distribution_inventory(
        raw.get("distribution_inventory"),
        expected_sha256=raw.get("distribution_inventory_sha256"),
    )
    return dict(raw)


def _materialize_python_runtime() -> dict[str, Any]:
    root = Path(CAPTURE_VALIDATION_RUNTIME)
    source_base = Path(CAPTURE_RUNTIME_SOURCE_BASE)
    source_venv = Path(CAPTURE_RUNTIME_SOURCE_VENV)
    if root.exists() or root.is_symlink():
        raise AuditError(
            f"validation Python runtime root must be fresh; preserve and move it first: {root}"
        )
    if (
        not source_base.is_dir()
        or source_base.is_symlink()
        or not source_venv.is_dir()
        or source_venv.is_symlink()
    ):
        raise AuditError("validation Python runtime sources are unavailable or indirect")
    root.mkdir(mode=0o700)
    try:
        shutil.copytree(
            source_base,
            Path(CAPTURE_VALIDATION_RUNTIME_BASE),
            symlinks=True,
            copy_function=shutil.copy2,
        )
        shutil.copytree(
            source_venv,
            Path(CAPTURE_VALIDATION_RUNTIME_VENV),
            symlinks=True,
            copy_function=shutil.copy2,
        )
        python_link = Path(CAPTURE_VALIDATION_PYTHON)
        if not python_link.is_symlink():
            raise AuditError("validation Python source executable is not the expected symlink")
        python_link.unlink()
        python_link.symlink_to("../../base/bin/python3.11")
        pyvenv_path = Path(CAPTURE_VALIDATION_RUNTIME_VENV) / "pyvenv.cfg"
        pyvenv_content = pyvenv_path.read_bytes()
        pyvenv_path.write_bytes(_render_rebound_pyvenv_config(pyvenv_content))
        _make_materialization_read_only(root)
        return _python_runtime_ref()
    except BaseException:
        # Preserve incomplete runtime evidence for diagnosis; never recursively clean it.
        raise


def _materialize_security_siblings() -> list[dict[str, Any]]:
    root = Path(CAPTURE_SECURITY_MATERIALIZED)
    if root.exists():
        raise AuditError(
            f"security materialization root must be fresh; preserve and move it first: {root}"
        )
    root.mkdir(mode=0o700)
    try:
        for expected in SECURITY_SIBLING_SUBJECTS:
            source = Path(CAPTURE_SECURITY_SIBLINGS) / expected["directory"]
            _require_safe_local_git_config(
                source,
                label=f"security sibling source {expected['repository']}",
            )
            source_commit = _run_git(["rev-parse", "HEAD"], cwd=source).decode("ascii").strip()
            source_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=source).decode("ascii").strip()
            source_status = _run_git(
                ["status", "--porcelain=v1", "--untracked-files=all"], cwd=source
            )
            if (
                source_commit != expected["commit"]
                or source_tree != expected["tree"]
                or source_status != b""
            ):
                raise AuditError(
                    f"security sibling source drifted before materialization: {source}"
                )
            destination = root / expected["directory"]
            _run_git(
                [
                    "clone",
                    "--local",
                    "--no-hardlinks",
                    "--no-checkout",
                    str(source),
                    str(destination),
                ],
                cwd=root,
            )
            _run_git(["checkout", "--detach", expected["commit"]], cwd=destination)
            _run_git(["remote", "remove", "origin"], cwd=destination)
        _make_materialization_read_only(root)
        return _security_materialization_refs()
    except BaseException:
        # Preserve incomplete materialization evidence for diagnosis; never recursively
        # delete a path assembled from mutable filesystem state.
        raise


VALIDATION_OVERLAY_PATHS: tuple[str, ...] = (
    "scripts/quality/audit_build_delivery.py",
    "tests/test_build_delivery_audit.py",
)


def _require_exact_validation_checkout_status(
    status_output: bytes,
    ignored_output: bytes,
) -> None:
    visible = set(status_output.splitlines())
    ignored = {item for item in ignored_output.split(b"\0") if item}
    overlays = {f"?? {path}".encode("utf-8") for path in VALIDATION_OVERLAY_PATHS}
    ignored_case = visible == overlays and ignored == {b"test.db"}
    untracked_case = visible == overlays | {b"?? test.db"} and ignored == set()
    if not ignored_case and not untracked_case:
        raise AuditError("validation checkout status boundary drifted")


def _validation_checkout_ref() -> dict[str, Any]:
    root = Path(CAPTURE_AUDIT_CWD)
    if not root.is_dir() or root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise AuditError("validation checkout materialization is unavailable or not private")
    manifest_before = _private_checkout_filesystem_manifest(
        root,
        label="validation checkout materialization",
    )
    _require_safe_local_git_config(root, label="validation checkout materialization")
    commit = _run_git(["rev-parse", "HEAD"], cwd=root).decode("ascii").strip()
    tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=root).decode("ascii").strip()
    branch_probe = _run_git_completed(["symbolic-ref", "-q", "HEAD"], cwd=root)
    if branch_probe.returncode != 1 or branch_probe.stderr != b"":
        raise AuditError("validation checkout detached-HEAD probe drifted")
    branch = branch_probe.stdout
    remotes = _run_git(["remote"], cwd=root)
    status_output = _run_git(
        ["status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
    )
    ignored_output = _run_git(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        cwd=root,
    )
    _require_exact_validation_checkout_status(status_output, ignored_output)
    alternates = root / ".git" / "objects" / "info" / "alternates"
    if (
        commit != BASELINE_SHA
        or tree != BASELINE_TREE
        or branch != b""
        or remotes != b""
        or alternates.exists()
        or alternates.is_symlink()
    ):
        raise AuditError("validation checkout identity or standalone boundary drifted")
    overlay_refs = _audit_implementation_refs()
    for path, source_ref in zip(VALIDATION_OVERLAY_PATHS, overlay_refs, strict=True):
        content, mode = _read_rooted_regular_file(
            root,
            path,
            label=f"validation checkout overlay {path}",
        )
        if mode != 0o644:
            raise AuditError(f"validation checkout overlay mode is not exact 0644: {path}")
        observed_ref = {
            "git_blob_sha1": _git_blob_sha1(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for key, value in observed_ref.items():
            _require_exact_json_value(
                value,
                source_ref[key],
                label=f"validation checkout overlay {path}.{key}",
            )
    manifest_after = _private_checkout_filesystem_manifest(
        root,
        label="validation checkout materialization",
    )
    if manifest_after != manifest_before:
        raise AuditError("validation checkout changed during materialization verification")
    return {
        "materialized_root": str(CAPTURE_AUDIT_CWD),
        "commit": commit,
        "tree": tree,
        "head_state": "detached",
        "worktree_status": "exact two authorized untracked implementation overlays",
        "overlay_refs": overlay_refs,
        "filesystem_manifest_sha256": manifest_after[0],
        "filesystem_entry_count": manifest_after[1],
        "filesystem_identity_sha256": manifest_after[2],
        "test_output_root_identity": manifest_after[3],
        "test_db_identity": manifest_after[4],
        "mode": "private 0700 root with recursively read-only .git; standalone no-hardlink clone with exact portable and identity manifests plus one identity-bound external test.db symlink and target",
        "standalone": "no remotes or alternates; only an exact ignored test.db symlink to the private external output root",
    }


def _validate_validation_checkout_ref(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AuditError("validation checkout materialization ref must be an object")
    expected = {
        "materialized_root": str(CAPTURE_AUDIT_CWD),
        "commit": BASELINE_SHA,
        "tree": BASELINE_TREE,
        "head_state": "detached",
        "worktree_status": "exact two authorized untracked implementation overlays",
        "mode": "private 0700 root with recursively read-only .git; standalone no-hardlink clone with exact portable and identity manifests plus one identity-bound external test.db symlink and target",
        "standalone": "no remotes or alternates; only an exact ignored test.db symlink to the private external output root",
    }
    _require_exact_keys(
        raw,
        frozenset(expected)
        | frozenset(
            {
                "overlay_refs",
                "filesystem_manifest_sha256",
                "filesystem_identity_sha256",
                "filesystem_entry_count",
                "test_output_root_identity",
                "test_db_identity",
            }
        ),
        label="validation checkout materialization ref",
    )
    for key, expected_value in expected.items():
        _require_exact_json_value(
            raw.get(key),
            expected_value,
            label=f"validation checkout materialization ref.{key}",
        )
    _require_exact_json_value(
        raw.get("overlay_refs"),
        _audit_implementation_refs(),
        label="validation checkout materialization overlay refs",
    )
    digest = raw.get("filesystem_manifest_sha256")
    identity_digest = raw.get("filesystem_identity_sha256")
    count = raw.get("filesystem_entry_count")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AuditError("validation checkout manifest digest is malformed")
    if not isinstance(identity_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", identity_digest):
        raise AuditError("validation checkout identity digest is malformed")
    if type(count) is not int or count <= 0:
        raise AuditError("validation checkout manifest entry count is malformed")
    for key in ("test_output_root_identity", "test_db_identity"):
        identity = raw.get(key)
        if (
            not isinstance(identity, dict)
            or frozenset(identity) != frozenset({"device", "inode"})
            or any(type(identity[field]) is not int or identity[field] < 0 for field in identity)
        ):
            raise AuditError(f"validation checkout {key} is malformed")
    return dict(raw)


def _materialize_validation_checkout() -> dict[str, Any]:
    destination = Path(CAPTURE_AUDIT_CWD)
    if destination.exists() or destination.is_symlink():
        raise AuditError(
            f"validation checkout root must be fresh; preserve and move it first: {destination}"
        )
    source_refs = _audit_implementation_refs()
    try:
        _run_git(
            [
                "clone",
                "--local",
                "--no-hardlinks",
                "--no-checkout",
                str(ROOT),
                str(destination),
            ],
            cwd=Path(CAPTURE_TEMP_ROOT),
        )
        _run_git(["checkout", "--detach", BASELINE_SHA], cwd=destination)
        _run_git(["remote", "remove", "origin"], cwd=destination)
        destination.chmod(0o700)
        for path, source_ref in zip(VALIDATION_OVERLAY_PATHS, source_refs, strict=True):
            content, mode = _read_rooted_regular_file(
                ROOT,
                path,
                label=f"validation overlay source {path}",
            )
            if mode != 0o644:
                raise AuditError(f"validation overlay source mode is not exact 0644: {path}")
            if (destination / path).exists() or (destination / path).is_symlink():
                raise AuditError(f"validation overlay unexpectedly exists in baseline: {path}")
            published = _publish_new_bytes(destination, destination / path, content)
            if (
                published.mode != 0o644
                or published.size_bytes != source_ref["size_bytes"]
                or published.content_sha256 != source_ref["content_sha256"]
            ):
                raise AuditError(f"validation overlay publication drifted: {path}")
        test_db_link = destination / "test.db"
        if test_db_link.exists() or test_db_link.is_symlink():
            raise AuditError("validation checkout external test.db symlink already exists")
        os.symlink(str(CAPTURE_VALIDATION_TEST_DB), test_db_link)
        if not test_db_link.is_symlink() or os.readlink(test_db_link) != str(
            CAPTURE_VALIDATION_TEST_DB
        ):
            raise AuditError("validation checkout external test.db symlink publication drifted")
        _make_materialization_read_only(destination / ".git")
        return _validation_checkout_ref()
    except BaseException:
        # Preserve any incomplete checkout for diagnosis; never recursively clean a path
        # assembled from mutable filesystem state.
        raise


def _prepare_validation_test_output() -> None:
    test_output_root = Path(CAPTURE_VALIDATION_TEST_OUTPUT_ROOT)
    if test_output_root.exists() or test_output_root.is_symlink():
        raise AuditError(
            "validation test-output root must be fresh; preserve and move it first: "
            f"{test_output_root}"
        )
    test_output_root.mkdir(mode=0o700)
    test_db = Path(CAPTURE_VALIDATION_TEST_DB)
    descriptor = os.open(
        test_db,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != 0
    ):
        raise AuditError("validation external test.db publication drifted")


def _require_private_validation_directory(
    descriptor: int,
    *,
    label: str,
    expected_mode: int = 0o700,
) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise AuditError(f"{label} is not an exact UID-owned mode-{expected_mode:04o} directory")
    return _stat_identity(metadata)


def _parser_smoke_directory_record(
    descriptor: int,
    *,
    relative_path: str,
    label: str,
    expected_mode: int = 0o700,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = os.fstat(descriptor)
    _require_private_validation_directory(
        descriptor,
        label=label,
        expected_mode=expected_mode,
    )
    return (
        {
            "path": relative_path,
            "file_type": "directory",
            "mode": f"{expected_mode:04o}",
        },
        {
            "path": relative_path,
            **_manifest_identity_record(metadata),
        },
    )


def _parser_smoke_file_record(
    descriptor: int,
    *,
    parent_fd: int,
    name: str,
    relative_path: str,
    label: str,
    expected_mode: int = 0o600,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    try:
        before = os.fstat(descriptor)
        lexical_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != expected_mode
        ):
            raise AuditError(
                f"{label} is not an exact UID-owned single-link mode-{expected_mode:04o} file"
            )
        if any(getattr(before, field) != getattr(lexical_before, field) for field in stable_fields):
            raise AuditError(f"{label} lexical identity changed before verification")
        content = _read_stable_descriptor(descriptor, label=label)
        after = os.fstat(descriptor)
        lexical_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise AuditError(f"unable to verify {label}: {exc}") from exc
    if any(
        getattr(left, field) != getattr(right, field)
        for left, right in (
            (before, after),
            (after, lexical_after),
        )
        for field in stable_fields
    ):
        raise AuditError(f"{label} changed during stable verification")
    return (
        {
            "path": relative_path,
            "file_type": "regular",
            "mode": f"{expected_mode:04o}",
            "link_count": 1,
            "size_bytes": len(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        },
        {
            "path": relative_path,
            **_manifest_identity_record(after),
        },
    )


def _create_private_validation_child(parent_fd: int, name: str, *, label: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise AuditError(f"{label} was preclaimed during exclusive creation") from exc
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        _require_private_validation_directory(descriptor, label=label)
        lexical = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _stat_identity(lexical) != _stat_identity(os.fstat(descriptor)):
            raise AuditError(f"{label} identity changed during exclusive creation")
        return descriptor
    except BaseException:
        _close_descriptors(descriptor)
        raise


def _publish_private_validation_fixture(
    directory_fd: int,
    name: str,
    content: bytes,
    *,
    label: str,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        observed, _identity = _parser_smoke_file_record(
            descriptor,
            parent_fd=directory_fd,
            name=name,
            relative_path=name,
            label=label,
        )
        if (
            observed["size_bytes"] != len(content)
            or observed["content_sha256"] != hashlib.sha256(content).hexdigest()
        ):
            raise AuditError(f"{label} publication drifted")
        return descriptor
    except FileExistsError as exc:
        raise AuditError(f"{label} was preclaimed during exclusive publication") from exc
    except BaseException:
        _close_descriptors(descriptor)
        raise


def _reopen_private_validation_file_read_only(
    parent_fd: int,
    name: str,
    writable_fd: int,
    *,
    relative_path: str,
    label: str,
    expected_mode: int = 0o600,
) -> int:
    expected = _parser_smoke_file_record(
        writable_fd,
        parent_fd=parent_fd,
        name=name,
        relative_path=relative_path,
        label=label,
        expected_mode=expected_mode,
    )
    read_only_fd: int | None = None
    try:
        read_only_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        if (
            _parser_smoke_file_record(
                read_only_fd,
                parent_fd=parent_fd,
                name=name,
                relative_path=relative_path,
                label=label,
                expected_mode=expected_mode,
            )
            != expected
        ):
            raise AuditError(f"{label} changed while it was reopened read-only")
        os.close(writable_fd)
        return read_only_fd
    except BaseException:
        _close_descriptors(read_only_fd)
        raise


def _parser_smoke_static_records(
    state: Mapping[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        _parser_smoke_file_record(
            state["expected_results_fd"],
            parent_fd=state["workspace_fd"],
            name="expected_results.csv",
            relative_path="workspace/expected_results.csv",
            label="validation parser expected-results fixture",
            expected_mode=0o400,
        ),
        _parser_smoke_file_record(
            state["sample_report_fd"],
            parent_fd=state["samples_fd"],
            name="sample_report_01.csv",
            relative_path="workspace/samples/sample_report_01.csv",
            label="validation parser sample-report fixture",
            expected_mode=0o400,
        ),
    ]


def _verify_parser_smoke_bindings(state: Mapping[str, Any]) -> None:
    try:
        root_lexical = os.stat(
            Path(CAPTURE_PARSER_SMOKE_ROOT),
            follow_symlinks=False,
        )
        workspace_lexical = os.stat(
            "workspace",
            dir_fd=state["root_fd"],
            follow_symlinks=False,
        )
        samples_lexical = os.stat(
            "samples",
            dir_fd=state["workspace_fd"],
            follow_symlinks=False,
        )
        home_lexical = os.stat(
            "home",
            dir_fd=state["root_fd"],
            follow_symlinks=False,
        )
    except OSError as exc:
        raise AuditError(
            f"validation parser-smoke directory binding is unavailable: {exc}"
        ) from exc
    home_mode = 0o500 if state.get("installed_records") is not None else 0o700
    for descriptor, lexical, expected_identity, label, expected_mode in (
        (
            state["root_fd"],
            root_lexical,
            state["root_identity"],
            "validation parser-smoke root",
            0o700,
        ),
        (
            state["workspace_fd"],
            workspace_lexical,
            state["workspace_identity"],
            "validation parser-smoke workspace",
            0o500,
        ),
        (
            state["samples_fd"],
            samples_lexical,
            state["samples_identity"],
            "validation parser-smoke samples directory",
            0o500,
        ),
        (
            state["home_fd"],
            home_lexical,
            state["home_identity"],
            "validation parser-smoke home directory",
            home_mode,
        ),
    ):
        observed_identity = _require_private_validation_directory(
            descriptor,
            label=label,
            expected_mode=expected_mode,
        )
        if observed_identity != expected_identity or observed_identity != _stat_identity(lexical):
            raise AuditError(f"{label} lexical identity drifted")
    static_records = _parser_smoke_static_records(state)
    if static_records != state["static_records"]:
        raise AuditError("validation parser-smoke static fixture identity/content drifted")
    if state.get("installed_records") is not None:
        _verify_parser_smoke_install_outputs(state)


def _verify_parser_smoke_state(
    state: Mapping[str, Any],
    *,
    require_profile: bool,
) -> None:
    _verify_parser_smoke_bindings(state)
    profile_fd = state["profile_fd"]
    expected_record = (
        state.get("profile_record") if require_profile else state["reserved_profile_record"]
    )
    if require_profile and expected_record is None:
        raise AuditError("validation parser-smoke generated profile is not bound")
    observed_profile = _parser_smoke_file_record(
        profile_fd,
        parent_fd=state["workspace_fd"],
        name="profile.yaml",
        relative_path="workspace/profile.yaml",
        label="validation parser profile slot",
        expected_mode=0o400 if require_profile else 0o600,
    )
    if observed_profile != expected_record:
        state_label = "generated" if require_profile else "reserved"
        raise AuditError(f"validation parser {state_label} profile identity/content drifted")


def _capture_parser_smoke_profile(state: dict[str, Any]) -> None:
    if state.get("profile_record") is not None:
        raise AuditError("validation parser generated profile was already captured")
    _verify_parser_smoke_bindings(state)
    writable_fd = state["profile_fd"]
    generated_record = _parser_smoke_file_record(
        writable_fd,
        parent_fd=state["workspace_fd"],
        name="profile.yaml",
        relative_path="workspace/profile.yaml",
        label="validation parser generated profile",
    )
    if (
        generated_record[1]["device"],
        generated_record[1]["inode"],
    ) != state["profile_identity"] or generated_record[0]["size_bytes"] <= 0:
        raise AuditError("validation parser profile did not populate the reserved output inode")
    os.fchmod(writable_fd, 0o400)
    state["profile_fd"] = _reopen_private_validation_file_read_only(
        state["workspace_fd"],
        "profile.yaml",
        writable_fd,
        relative_path="workspace/profile.yaml",
        label="validation parser generated profile",
        expected_mode=0o400,
    )
    state["profile_record"] = _parser_smoke_file_record(
        state["profile_fd"],
        parent_fd=state["workspace_fd"],
        name="profile.yaml",
        relative_path="workspace/profile.yaml",
        label="validation parser generated profile",
        expected_mode=0o400,
    )


def _open_parser_smoke_child_directory(
    parent_fd: int,
    name: str,
    *,
    label: str,
    expected_mode: int | None = None,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        lexical = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise AuditError(f"{label} is not an exact UID-owned directory")
        if expected_mode is not None and stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise AuditError(f"{label} is not exact mode-{expected_mode:04o}")
        if _manifest_identity_record(lexical) != _manifest_identity_record(metadata):
            raise AuditError(f"{label} identity changed while it was opened")
        return descriptor
    except OSError as exc:
        _close_descriptors(descriptor)
        raise AuditError(f"unable to bind {label}: {exc}") from exc
    except BaseException:
        _close_descriptors(descriptor)
        raise


def _open_parser_smoke_generated_file(
    parent_fd: int,
    name: str,
    *,
    label: str,
    expected_mode: int | None = None,
) -> int:
    """Bind a child-created leaf without blocking or mutating it."""
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        lexical = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise AuditError(f"{label} is not a UID-owned single-link regular file")
        if expected_mode is not None and stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise AuditError(f"{label} is not exact mode-{expected_mode:04o}")
        if _manifest_identity_record(lexical) != _manifest_identity_record(metadata):
            raise AuditError(f"{label} identity changed while it was opened")
        return descriptor
    except OSError as exc:
        _close_descriptors(descriptor)
        raise AuditError(f"unable to bind {label}: {exc}") from exc
    except BaseException:
        _close_descriptors(descriptor)
        raise


def _parser_smoke_install_directory_roles() -> tuple[tuple[str, str], ...]:
    return (
        (".metroliza", "validation parser installed .metroliza directory"),
        ("parser_plugins", "validation parser installed plugin-root directory"),
        ("profiles", "validation parser installed profile-store directory"),
        ("approved", "validation parser installed approved directory"),
        ("ci_smoke", "validation parser installed plugin directory"),
    )


def _bind_parser_smoke_install_outputs(state: dict[str, Any], *, freeze: bool) -> None:
    if state.get("installed_records") is not None:
        raise AuditError("validation parser installed outputs were already captured")
    directory_fds: list[int] = []
    installed_profile_fd: int | None = None
    installed_approval_fd: int | None = None
    lock_fd: int | None = None
    try:
        parent_fd = state["home_fd"]
        for name, label in _parser_smoke_install_directory_roles():
            descriptor = _open_parser_smoke_child_directory(
                parent_fd,
                name,
                label=label,
                expected_mode=None if freeze else 0o500,
            )
            directory_fds.append(descriptor)
            parent_fd = descriptor
        installed_profile_fd = _open_parser_smoke_generated_file(
            directory_fds[-1],
            "profile.yaml",
            label="validation parser installed profile",
            expected_mode=None if freeze else 0o400,
        )
        installed_approval_fd = _open_parser_smoke_generated_file(
            directory_fds[-1],
            "approval.json",
            label="validation parser installed approval",
            expected_mode=None if freeze else 0o400,
        )
        lock_fd = _open_parser_smoke_generated_file(
            directory_fds[1],
            ".profile-store.lock",
            label="validation parser installed profile-store lock",
            expected_mode=None if freeze else 0o600,
        )
        if freeze:
            # All child-created leaves are now proven regular, owner-bound and
            # single-link.  Only this post-install transition may change modes.
            os.fchmod(installed_profile_fd, 0o400)
            os.fchmod(installed_approval_fd, 0o400)
            os.fchmod(lock_fd, 0o600)
            for descriptor in reversed(directory_fds):
                os.fchmod(descriptor, 0o500)
            os.fchmod(state["home_fd"], 0o500)
        else:
            _require_private_validation_directory(
                state["home_fd"],
                label="validation parser-smoke home directory",
                expected_mode=0o500,
            )
        directory_identities = [
            _stat_identity(os.fstat(descriptor)) for descriptor in directory_fds
        ]
        installed_records = [
            _parser_smoke_file_record(
                installed_profile_fd,
                parent_fd=directory_fds[-1],
                name="profile.yaml",
                relative_path=(
                    "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/profile.yaml"
                ),
                label="validation parser installed profile",
                expected_mode=0o400,
            ),
            _parser_smoke_file_record(
                installed_approval_fd,
                parent_fd=directory_fds[-1],
                name="approval.json",
                relative_path=(
                    "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/approval.json"
                ),
                label="validation parser installed approval",
                expected_mode=0o400,
            ),
        ]
        if (
            installed_records[0][0]["content_sha256"]
            != state["profile_record"][0]["content_sha256"]
        ):
            raise AuditError("validation parser installed profile differs from held source")
        lock_record = _parser_smoke_file_record(
            lock_fd,
            parent_fd=directory_fds[1],
            name=".profile-store.lock",
            relative_path="home/.metroliza/parser_plugins/.profile-store.lock",
            label="validation parser installed profile-store lock",
        )
        state.update(
            {
                "install_directory_fds": tuple(directory_fds),
                "install_directory_identities": tuple(directory_identities),
                "installed_profile_fd": installed_profile_fd,
                "installed_approval_fd": installed_approval_fd,
                "installed_lock_fd": lock_fd,
                "installed_records": installed_records,
                "installed_lock_record": lock_record,
            }
        )
    except BaseException:
        _close_descriptors(
            lock_fd,
            installed_approval_fd,
            installed_profile_fd,
            *reversed(directory_fds),
        )
        raise


def _capture_parser_smoke_install_outputs(state: dict[str, Any]) -> None:
    # The install child may create descendants, but it may not mutate any
    # preexisting held input or the mode/identity of the private home root.
    _verify_parser_smoke_state(state, require_profile=True)
    _bind_parser_smoke_install_outputs(state, freeze=True)


def _open_parser_smoke_install_outputs(state: dict[str, Any]) -> None:
    """Open and verify frozen install outputs without normalizing live state."""
    _bind_parser_smoke_install_outputs(state, freeze=False)


def _verify_parser_smoke_install_outputs(state: Mapping[str, Any]) -> None:
    directory_fds = state.get("install_directory_fds")
    identities = state.get("install_directory_identities")
    if not isinstance(directory_fds, tuple) or not isinstance(identities, tuple):
        raise AuditError("validation parser installed output directories are not bound")
    parent_fd = state["home_fd"]
    for descriptor, expected_identity, (name, label) in zip(
        directory_fds,
        identities,
        _parser_smoke_install_directory_roles(),
        strict=True,
    ):
        lexical = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        observed_identity = _require_private_validation_directory(
            descriptor,
            label=label,
            expected_mode=0o500,
        )
        if observed_identity != expected_identity or observed_identity != _stat_identity(lexical):
            raise AuditError(f"{label} lexical identity drifted")
        parent_fd = descriptor
    observed_records = [
        _parser_smoke_file_record(
            state["installed_profile_fd"],
            parent_fd=directory_fds[-1],
            name="profile.yaml",
            relative_path="home/.metroliza/parser_plugins/profiles/approved/ci_smoke/profile.yaml",
            label="validation parser installed profile",
            expected_mode=0o400,
        ),
        _parser_smoke_file_record(
            state["installed_approval_fd"],
            parent_fd=directory_fds[-1],
            name="approval.json",
            relative_path="home/.metroliza/parser_plugins/profiles/approved/ci_smoke/approval.json",
            label="validation parser installed approval",
            expected_mode=0o400,
        ),
    ]
    if observed_records != state["installed_records"]:
        raise AuditError("validation parser installed evidence inputs drifted")
    lock_record = _parser_smoke_file_record(
        state["installed_lock_fd"],
        parent_fd=directory_fds[1],
        name=".profile-store.lock",
        relative_path="home/.metroliza/parser_plugins/.profile-store.lock",
        label="validation parser installed profile-store lock",
    )
    if lock_record != state["installed_lock_record"]:
        raise AuditError("validation parser installed profile-store lock drifted")


def _parser_smoke_state_ref(state: Mapping[str, Any]) -> dict[str, Any]:
    _verify_parser_smoke_state(state, require_profile=True)
    installed_records = state.get("installed_records")
    if not isinstance(installed_records, list) or len(installed_records) != 2:
        raise AuditError("validation parser installed evidence inputs are not bound")
    directory_records = [
        _parser_smoke_directory_record(
            state["root_fd"],
            relative_path=".",
            label="validation parser-smoke root",
        ),
        _parser_smoke_directory_record(
            state["workspace_fd"],
            relative_path="workspace",
            label="validation parser-smoke workspace",
            expected_mode=0o500,
        ),
        _parser_smoke_directory_record(
            state["samples_fd"],
            relative_path="workspace/samples",
            label="validation parser-smoke samples directory",
            expected_mode=0o500,
        ),
    ]
    file_records = [
        *state["static_records"],
        state["profile_record"],
    ]
    portable_records = [row[0] for row in (*directory_records, *file_records, *installed_records)]
    return {
        "schema_version": 1,
        "materialized_root": str(CAPTURE_PARSER_SMOKE_ROOT),
        "directory_refs": [row[0] for row in directory_records],
        "input_refs": [row[0] for row in file_records],
        "evidence_input_refs": [row[0] for row in installed_records],
        "profile_lifecycle": {
            "initial_state": "exclusive empty output slot",
            "generated_by_invocation_index": 0,
            "consumed_by_invocation_indices": [1, 2, 3],
        },
        "install_output_lifecycle": {
            "generated_by_invocation_index": 3,
            "consumed_by_invocation_index": 4,
            "protection": "held descriptors plus mode-0500 ancestor directories and mode-0400 installed profile/approval",
        },
        "binding": "held descriptor aliases supplied to every parser child; derived samples stay beneath held mode-0500 workspace/sample directories; live inode and byte guards surround each invocation; installed evidence inputs are frozen and retained",
        "filesystem_manifest_sha256": _canonical_json_value_sha256(portable_records),
        "filesystem_entry_count": len(portable_records),
    }


def _close_parser_smoke_state(state: Mapping[str, Any]) -> None:
    _close_descriptors(
        state.get("installed_lock_fd"),
        state.get("installed_approval_fd"),
        state.get("installed_profile_fd"),
        *reversed(state.get("install_directory_fds", ())),
        state.get("profile_fd"),
        state.get("sample_report_fd"),
        state.get("expected_results_fd"),
        state.get("samples_fd"),
        state.get("home_fd"),
        state.get("workspace_fd"),
        state.get("root_fd"),
    )


def _open_parser_smoke_state() -> dict[str, Any]:
    root_fd: int | None = None
    workspace_fd: int | None = None
    samples_fd: int | None = None
    home_fd: int | None = None
    expected_results_fd: int | None = None
    sample_report_fd: int | None = None
    profile_fd: int | None = None
    state: dict[str, Any] = {}
    try:
        root_fd = os.open(
            Path(CAPTURE_PARSER_SMOKE_ROOT),
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        workspace_fd = os.open(
            "workspace",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        samples_fd = os.open(
            "samples",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=workspace_fd,
        )
        home_fd = os.open(
            "home",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        expected_results_fd = _open_parser_smoke_generated_file(
            workspace_fd,
            "expected_results.csv",
            label="validation parser expected-results fixture",
            expected_mode=0o400,
        )
        sample_report_fd = _open_parser_smoke_generated_file(
            samples_fd,
            "sample_report_01.csv",
            label="validation parser sample-report fixture",
            expected_mode=0o400,
        )
        profile_fd = _open_parser_smoke_generated_file(
            workspace_fd,
            "profile.yaml",
            label="validation parser generated profile",
            expected_mode=0o400,
        )
        state = {
            "root_fd": root_fd,
            "workspace_fd": workspace_fd,
            "samples_fd": samples_fd,
            "home_fd": home_fd,
            "expected_results_fd": expected_results_fd,
            "sample_report_fd": sample_report_fd,
            "profile_fd": profile_fd,
            "root_identity": _stat_identity(os.fstat(root_fd)),
            "workspace_identity": _stat_identity(os.fstat(workspace_fd)),
            "samples_identity": _stat_identity(os.fstat(samples_fd)),
            "home_identity": _stat_identity(os.fstat(home_fd)),
            "profile_identity": _stat_identity(os.fstat(profile_fd)),
            "reserved_profile_record": None,
            "installed_records": None,
        }
        state["static_records"] = _parser_smoke_static_records(state)
        state["profile_record"] = _parser_smoke_file_record(
            profile_fd,
            parent_fd=workspace_fd,
            name="profile.yaml",
            relative_path="workspace/profile.yaml",
            label="validation parser generated profile",
            expected_mode=0o400,
        )
        _open_parser_smoke_install_outputs(state)
        _verify_parser_smoke_state(state, require_profile=True)
        return state
    except BaseException:
        if state:
            _close_parser_smoke_state(state)
        else:
            _close_descriptors(
                profile_fd,
                sample_report_fd,
                expected_results_fd,
                samples_fd,
                home_fd,
                workspace_fd,
                root_fd,
            )
        raise


def _parser_smoke_input_ref() -> dict[str, Any]:
    state = _open_parser_smoke_state()
    try:
        return _parser_smoke_state_ref(state)
    finally:
        _close_parser_smoke_state(state)


def _validate_parser_smoke_input_row(
    ref: Any,
    *,
    index: int,
    expected_path: str,
    expected_mode: str = "0600",
) -> None:
    if not isinstance(ref, dict):
        raise AuditError("validation parser-smoke input row must be an object")
    _require_exact_keys(
        ref,
        frozenset(
            {
                "path",
                "file_type",
                "mode",
                "link_count",
                "size_bytes",
                "content_sha256",
            }
        ),
        label=f"validation parser-smoke input row {index}",
    )
    if (
        ref.get("path") != expected_path
        or ref.get("file_type") != "regular"
        or ref.get("mode") != expected_mode
        or type(ref.get("link_count")) is not int
        or ref["link_count"] != 1
        or type(ref.get("size_bytes")) is not int
        or ref["size_bytes"] <= 0
        or not isinstance(ref.get("content_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", ref["content_sha256"])
    ):
        raise AuditError(f"validation parser-smoke input row {index} is malformed")


def _validate_parser_smoke_primary_refs(raw: Any) -> list[dict[str, Any]]:
    expected_paths = (
        "workspace/expected_results.csv",
        "workspace/samples/sample_report_01.csv",
        "workspace/profile.yaml",
    )
    if not isinstance(raw, list) or len(raw) != len(expected_paths):
        raise AuditError("validation parser-smoke input refs are incomplete")
    for index, (ref, expected_path) in enumerate(zip(raw, expected_paths, strict=True)):
        _validate_parser_smoke_input_row(
            ref,
            index=index,
            expected_path=expected_path,
            expected_mode="0400",
        )
    for ref, expected_content in zip(
        raw[:2],
        (PARSER_EXPECTED_RESULTS_CONTENT, PARSER_SAMPLE_REPORT_CONTENT),
        strict=True,
    ):
        if (
            ref["size_bytes"] != len(expected_content)
            or ref["content_sha256"] != hashlib.sha256(expected_content).hexdigest()
        ):
            raise AuditError("validation parser-smoke static fixture content drifted")
    return list(raw)


def _validate_parser_smoke_evidence_refs(
    raw: Any,
    *,
    generated_profile_ref: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected_paths = (
        "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/profile.yaml",
        "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/approval.json",
    )
    if not isinstance(raw, list) or len(raw) != len(expected_paths):
        raise AuditError("validation parser installed evidence input refs are incomplete")
    for index, (ref, expected_path) in enumerate(
        zip(raw, expected_paths, strict=True),
        start=3,
    ):
        _validate_parser_smoke_input_row(
            ref,
            index=index,
            expected_path=expected_path,
            expected_mode="0400",
        )
    if raw[0]["content_sha256"] != generated_profile_ref["content_sha256"]:
        raise AuditError("validation parser installed profile does not bind the generated profile")
    return list(raw)


def _validate_parser_smoke_input_ref(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AuditError("validation parser-smoke input ref must be an object")
    expected_static = {
        "schema_version": 1,
        "materialized_root": str(CAPTURE_PARSER_SMOKE_ROOT),
        "directory_refs": [
            {"path": ".", "file_type": "directory", "mode": "0700"},
            {"path": "workspace", "file_type": "directory", "mode": "0500"},
            {
                "path": "workspace/samples",
                "file_type": "directory",
                "mode": "0500",
            },
        ],
        "profile_lifecycle": {
            "initial_state": "exclusive empty output slot",
            "generated_by_invocation_index": 0,
            "consumed_by_invocation_indices": [1, 2, 3],
        },
        "install_output_lifecycle": {
            "generated_by_invocation_index": 3,
            "consumed_by_invocation_index": 4,
            "protection": "held descriptors plus mode-0500 ancestor directories and mode-0400 installed profile/approval",
        },
        "binding": "held descriptor aliases supplied to every parser child; derived samples stay beneath held mode-0500 workspace/sample directories; live inode and byte guards surround each invocation; installed evidence inputs are frozen and retained",
        "filesystem_entry_count": 8,
    }
    _require_exact_keys(
        raw,
        frozenset(expected_static)
        | frozenset(
            {
                "input_refs",
                "evidence_input_refs",
                "filesystem_manifest_sha256",
            }
        ),
        label="validation parser-smoke input ref",
    )
    for key, value in expected_static.items():
        _require_exact_json_value(
            raw.get(key), value, label=f"validation parser-smoke input ref.{key}"
        )
    refs = _validate_parser_smoke_primary_refs(raw.get("input_refs"))
    evidence_refs = _validate_parser_smoke_evidence_refs(
        raw.get("evidence_input_refs"),
        generated_profile_ref=refs[2],
    )
    digest = raw.get("filesystem_manifest_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AuditError("validation parser-smoke filesystem manifest digest is malformed")
    portable_records = [*expected_static["directory_refs"], *refs, *evidence_refs]
    if raw["filesystem_manifest_sha256"] != _canonical_json_value_sha256(portable_records):
        raise AuditError("validation parser-smoke portable manifest digest is stale")
    return dict(raw)


def _prepare_parser_smoke_inputs() -> dict[str, Any]:
    parser_root = Path(CAPTURE_PARSER_SMOKE_ROOT)
    try:
        parser_root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise AuditError(
            "validation parser-smoke root must be fresh and exclusively created; "
            f"preserve and move it first: {parser_root}"
        ) from exc
    root_fd: int | None = None
    workspace_fd: int | None = None
    samples_fd: int | None = None
    home_fd: int | None = None
    expected_results_fd: int | None = None
    sample_report_fd: int | None = None
    profile_fd: int | None = None
    try:
        root_fd = os.open(
            parser_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        root_identity = _require_private_validation_directory(
            root_fd, label="validation parser-smoke root"
        )
        if root_identity != _stat_identity(os.stat(parser_root, follow_symlinks=False)):
            raise AuditError("validation parser-smoke root identity changed during creation")
        workspace_fd = _create_private_validation_child(
            root_fd,
            "workspace",
            label="validation parser-smoke workspace",
        )
        samples_fd = _create_private_validation_child(
            workspace_fd,
            "samples",
            label="validation parser-smoke samples directory",
        )
        home_fd = _create_private_validation_child(
            root_fd,
            "home",
            label="validation parser-smoke home directory",
        )
        expected_results_fd = _publish_private_validation_fixture(
            workspace_fd,
            "expected_results.csv",
            PARSER_EXPECTED_RESULTS_CONTENT,
            label="validation parser expected-results fixture",
        )
        os.fchmod(expected_results_fd, 0o400)
        expected_results_fd = _reopen_private_validation_file_read_only(
            workspace_fd,
            "expected_results.csv",
            expected_results_fd,
            relative_path="workspace/expected_results.csv",
            label="validation parser expected-results fixture",
            expected_mode=0o400,
        )
        sample_report_fd = _publish_private_validation_fixture(
            samples_fd,
            "sample_report_01.csv",
            PARSER_SAMPLE_REPORT_CONTENT,
            label="validation parser sample-report fixture",
        )
        os.fchmod(sample_report_fd, 0o400)
        sample_report_fd = _reopen_private_validation_file_read_only(
            samples_fd,
            "sample_report_01.csv",
            sample_report_fd,
            relative_path="workspace/samples/sample_report_01.csv",
            label="validation parser sample-report fixture",
            expected_mode=0o400,
        )
        profile_fd = _publish_private_validation_fixture(
            workspace_fd,
            "profile.yaml",
            b"",
            label="validation parser reserved profile slot",
        )
        os.fchmod(samples_fd, 0o500)
        os.fchmod(workspace_fd, 0o500)
        state: dict[str, Any] = {
            "root_fd": root_fd,
            "workspace_fd": workspace_fd,
            "samples_fd": samples_fd,
            "home_fd": home_fd,
            "expected_results_fd": expected_results_fd,
            "sample_report_fd": sample_report_fd,
            "profile_fd": profile_fd,
            "profile_record": None,
            "installed_records": None,
            "root_identity": root_identity,
            "workspace_identity": _stat_identity(os.fstat(workspace_fd)),
            "samples_identity": _stat_identity(os.fstat(samples_fd)),
            "home_identity": _stat_identity(os.fstat(home_fd)),
            "profile_identity": _stat_identity(os.fstat(profile_fd)),
        }
        state["static_records"] = _parser_smoke_static_records(state)
        state["reserved_profile_record"] = _parser_smoke_file_record(
            profile_fd,
            parent_fd=workspace_fd,
            name="profile.yaml",
            relative_path="workspace/profile.yaml",
            label="validation parser reserved profile slot",
        )
        _verify_parser_smoke_state(state, require_profile=False)
        return state
    except BaseException:
        _close_descriptors(
            profile_fd,
            sample_report_fd,
            expected_results_fd,
            samples_fd,
            home_fd,
            workspace_fd,
            root_fd,
        )
        raise


def _prepare_validation_environment() -> tuple[
    list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    if ROOT.resolve(strict=True) != Path(CAPTURE_EXECUTOR_CWD).resolve(strict=True):
        raise AuditError(
            f"validation executor checkout drifted: expected {CAPTURE_EXECUTOR_CWD}, got {ROOT}"
        )
    clean_roots = {
        key: Path(VALIDATION_EXECUTION_ENV[key])
        for key in ("HOME", "MPLCONFIGDIR", "XDG_CACHE_HOME")
    }
    clean_roots.update(
        {
            "PYTHONPYCACHEPREFIX": Path(CAPTURE_VALIDATION_PYCACHE),
            "MYPY_CACHE_DIR": Path(CAPTURE_TEMP_ROOT) / "metroliza-976-validation-mypy-cache-v5",
            "RUFF_CACHE_DIR": Path(CAPTURE_VALIDATION_RUFF_CACHE),
        }
    )
    for key, path in clean_roots.items():
        if path.exists():
            raise AuditError(
                f"validation {key} root must be fresh; preserve and move it first: {path}"
            )
    if Path(CAPTURE_SECURITY_MATERIALIZED).exists():
        raise AuditError(
            "security materialization root must be fresh; preserve and move it first: "
            f"{CAPTURE_SECURITY_MATERIALIZED}"
        )
    if Path(CAPTURE_VALIDATION_RUNTIME).exists() or Path(CAPTURE_VALIDATION_RUNTIME).is_symlink():
        raise AuditError(
            "validation Python runtime root must be fresh; preserve and move it first: "
            f"{CAPTURE_VALIDATION_RUNTIME}"
        )
    if Path(CAPTURE_AUDIT_CWD).exists() or Path(CAPTURE_AUDIT_CWD).is_symlink():
        raise AuditError(
            "validation checkout root must be fresh; preserve and move it first: "
            f"{CAPTURE_AUDIT_CWD}"
        )
    for path in clean_roots.values():
        path.mkdir(mode=0o700, parents=True)
    _prepare_validation_test_output()
    parser_smoke_state = _prepare_parser_smoke_inputs()
    try:
        python_runtime = _materialize_python_runtime()
        security_materializations = _materialize_security_siblings()
        validation_checkout = _materialize_validation_checkout()
        return (
            security_materializations,
            validation_checkout,
            python_runtime,
            parser_smoke_state,
        )
    except BaseException:
        _close_parser_smoke_state(parser_smoke_state)
        raise


def _execute_validation_child(
    spec: Mapping[str, Any],
    *,
    child_count: int,
    held_tools: Mapping[str, tuple[int, Mapping[str, Any]]],
    runtime_argv: Sequence[str] | None = None,
    retained_fds: Sequence[int] = (),
) -> dict[str, Any]:
    print(
        f"validation child {spec['sequence']}/{child_count}: {spec['argv_display']}",
        file=sys.stderr,
        flush=True,
    )
    executable_path = str(spec["argv"][0])
    descriptor, observed_tool = held_tools[executable_path]
    _require_exact_json_value(
        spec["executable_ref"],
        observed_tool,
        label=f"validation child {spec['sequence']} held executable ref",
    )
    executed_argv = list(runtime_argv) if runtime_argv is not None else list(spec["argv"])
    pass_fds = tuple(dict.fromkeys((descriptor, *retained_fds)))
    try:
        completed = subprocess.run(
            executed_argv,
            executable=f"/proc/self/fd/{descriptor}",
            cwd=spec["cwd"],
            check=False,
            capture_output=True,
            env=dict(spec["environment"]),
            pass_fds=pass_fds,
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"validation child {spec['sequence']} could not complete: {exc}") from exc
    observation = {
        **spec,
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stdout_bytes": len(completed.stdout),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "stderr_bytes": len(completed.stderr),
    }
    print(
        f"validation child {spec['sequence']}/{child_count} exit={completed.returncode} "
        f"stdout={observation['stdout_sha256']} stderr={observation['stderr_sha256']}",
        file=sys.stderr,
        flush=True,
    )
    if completed.returncode != 0:
        stdout_tail = completed.stdout[-2000:].decode("utf-8", errors="replace")
        stderr_tail = completed.stderr[-2000:].decode("utf-8", errors="replace")
        raise AuditError(
            f"validation child {spec['sequence']} exited {completed.returncode}; "
            f"stdout tail={stdout_tail!r}; stderr tail={stderr_tail!r}"
        )
    expected_stdout = SECURITY_SIBLING_PREFLIGHT_EXPECTED_STDOUT.get(spec["argv_display"])
    if expected_stdout is not None and (
        completed.stdout != expected_stdout or completed.stderr != b""
    ):
        raise AuditError(f"validation child {spec['sequence']} sibling checkout output drifted")
    return observation


def _bound_parser_smoke_invocation(
    spec: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[list[str], tuple[int, ...]]:
    if spec.get("command") != "parser smoke":
        raise AuditError("parser-smoke descriptor binding received a non-parser child")
    profile = f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/profile.yaml"
    expected = f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/expected_results.csv"
    sample = f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace/samples/sample_report_01.csv"
    workspace = f"{CAPTURE_PARSER_SMOKE_ROOT}/workspace"
    home = f"{CAPTURE_PARSER_SMOKE_ROOT}/home"
    role_maps: dict[int, tuple[tuple[str, str, str], ...]] = {
        0: ((profile, "profile_fd", ""),),
        1: (
            (profile, "profile_fd", ""),
            (expected, "expected_results_fd", ""),
            (workspace, "workspace_fd", ""),
        ),
        2: (
            (profile, "profile_fd", ""),
            (sample, "samples_fd", "/sample_report_01.csv"),
        ),
        3: (
            (home, "home_fd", ""),
            (profile, "profile_fd", ""),
            (expected, "expected_results_fd", ""),
            (workspace, "workspace_fd", ""),
        ),
        4: ((home, "home_fd", ""),),
    }
    invocation_index = spec.get("invocation_index")
    roles = role_maps.get(invocation_index)
    if roles is None:
        raise AuditError("parser-smoke invocation index has no descriptor role map")
    runtime_argv = list(spec["argv"])
    retained: list[int] = []
    for lexical, state_key, alias_suffix in roles:
        matches = [index for index, token in enumerate(runtime_argv) if token == lexical]
        if len(matches) != 1:
            raise AuditError(
                f"parser-smoke invocation {invocation_index} descriptor role {lexical} "
                "is missing or duplicated"
            )
        descriptor = state.get(state_key)
        if type(descriptor) is not int or descriptor < 0:
            raise AuditError(
                f"parser-smoke invocation {invocation_index} descriptor role {state_key} "
                "is unavailable"
            )
        runtime_argv[matches[0]] = f"/proc/self/fd/{descriptor}{alias_suffix}"
        retained.append(descriptor)
    if any(str(CAPTURE_PARSER_SMOKE_ROOT) in token for token in runtime_argv):
        raise AuditError(
            f"parser-smoke invocation {invocation_index} retains an unbound lexical operand"
        )
    return runtime_argv, tuple(dict.fromkeys(retained))


def _execute_guarded_validation_child(
    spec: Mapping[str, Any],
    *,
    child_count: int,
    held_tools: Mapping[str, tuple[int, Mapping[str, Any]]],
    parser_smoke_state: dict[str, Any],
) -> dict[str, Any]:
    parser_child = spec["command"] == "parser smoke"
    if parser_child:
        _verify_parser_smoke_state(
            parser_smoke_state,
            require_profile=spec["invocation_index"] > 0,
        )
        runtime_argv, retained_fds = _bound_parser_smoke_invocation(spec, parser_smoke_state)
    else:
        runtime_argv = None
        retained_fds = ()
    observation = _execute_validation_child(
        spec,
        child_count=child_count,
        held_tools=held_tools,
        runtime_argv=runtime_argv,
        retained_fds=retained_fds,
    )
    if not parser_child:
        return observation
    if spec["invocation_index"] == 0:
        _capture_parser_smoke_profile(parser_smoke_state)
    elif spec["invocation_index"] == 3:
        _capture_parser_smoke_install_outputs(parser_smoke_state)
    _verify_parser_smoke_state(
        parser_smoke_state,
        require_profile=True,
    )
    return observation


def _execute_validation_suite() -> dict[str, Any]:
    """Execute every receipt child and return observations bound to the tested bytes."""
    (
        security_materializations,
        validation_checkout,
        python_runtime,
        parser_smoke_state,
    ) = _prepare_validation_environment()
    try:
        implementation_before = _audit_implementation_refs()
        specs = _validation_invocation_specs()
        with ExitStack() as stack:
            held_tools: dict[str, tuple[int, dict[str, Any]]] = {}
            for row in BOUND_EXECUTABLES:
                argv_path = str(row["argv_path"])
                held_tools[argv_path] = stack.enter_context(_bound_executable(argv_path))
            execution_tools_before = [
                dict(held_tools[str(row["argv_path"])][1]) for row in BOUND_EXECUTABLES
            ]
            observations = [
                _execute_guarded_validation_child(
                    spec,
                    child_count=len(specs),
                    held_tools=held_tools,
                    parser_smoke_state=parser_smoke_state,
                )
                for spec in specs
            ]
            execution_tools_after = [
                _observe_bound_executable_descriptor(
                    held_tools[str(row["argv_path"])][0],
                    argv_path=str(row["argv_path"]),
                    resolved_path=str(row["resolved_path"]),
                )
                for row in BOUND_EXECUTABLES
            ]
            if execution_tools_after != execution_tools_before:
                raise AuditError("held validation executable identities changed during execution")
        implementation_after = _audit_implementation_refs()
        if implementation_after != implementation_before:
            raise AuditError("Phase-A audit implementation changed during validation execution")
        if _execution_tool_refs() != execution_tools_before:
            raise AuditError("validation executable identities changed during validation execution")
        if _security_materialization_refs() != security_materializations:
            raise AuditError("pinned security materializations changed during validation execution")
        if _validation_checkout_ref() != validation_checkout:
            raise AuditError("validation checkout materialization changed during execution")
        if _python_runtime_ref() != python_runtime:
            raise AuditError("validation Python runtime changed during execution")
        parser_smoke_inputs = _parser_smoke_state_ref(parser_smoke_state)
        if _parser_smoke_input_ref() != parser_smoke_inputs:
            raise AuditError("validation parser-smoke input identities changed during execution")
        return {
            "tested_implementation_refs": implementation_before,
            "tested_execution_tool_refs": execution_tools_before,
            "tested_security_materializations": security_materializations,
            "tested_validation_checkout": validation_checkout,
            "tested_python_runtime": python_runtime,
            "tested_parser_smoke_inputs": parser_smoke_inputs,
            "observations": observations,
        }
    finally:
        _close_parser_smoke_state(parser_smoke_state)


def _validate_validation_observation(spec: Mapping[str, Any], raw: Any) -> dict[str, Any]:
    observation_keys = frozenset(
        {
            "sequence",
            "group_index",
            "invocation_index",
            "command",
            "argv",
            "argv_display",
            "cwd",
            "environment",
            "executable_ref",
            "observed_at",
            "exit_code",
            "stdout_sha256",
            "stdout_bytes",
            "stderr_sha256",
            "stderr_bytes",
        }
    )
    if not isinstance(raw, dict):
        raise AuditError("validation child result must be an object")
    _require_exact_keys(raw, observation_keys, label="validation child result")
    for key, value in spec.items():
        _require_exact_json_value(
            raw.get(key),
            value,
            label=f"validation child {spec['sequence']} execution identity at {key}",
        )
    if type(raw.get("exit_code")) is not int or raw["exit_code"] != 0:
        raise AuditError(f"validation child {spec['sequence']} did not exit zero; receipt refused")
    for stream in ("stdout", "stderr"):
        digest = raw.get(f"{stream}_sha256")
        size = raw.get(f"{stream}_bytes")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AuditError(f"validation child {spec['sequence']} has malformed {stream} digest")
        if type(size) is not int or size < 0:
            raise AuditError(
                f"validation child {spec['sequence']} has malformed {stream} byte count"
            )
    expected_stdout = SECURITY_SIBLING_PREFLIGHT_EXPECTED_STDOUT.get(spec["argv_display"])
    if expected_stdout is not None and (
        raw["stdout_sha256"] != hashlib.sha256(expected_stdout).hexdigest()
        or raw["stdout_bytes"] != len(expected_stdout)
        or raw["stderr_sha256"] != hashlib.sha256(b"").hexdigest()
        or raw["stderr_bytes"] != 0
    ):
        raise AuditError(f"validation child {spec['sequence']} sibling checkout result drifted")
    return dict(raw)


def _validation_records_from_observations(observations: Any) -> list[dict[str, Any]]:
    specs = _validation_invocation_specs()
    if not isinstance(observations, list) or len(observations) != len(specs):
        raise AuditError("validation receipt requires one result for every exact child invocation")
    validated = [
        _validate_validation_observation(spec, raw)
        for spec, raw in zip(specs, observations, strict=True)
    ]

    records: list[dict[str, Any]] = []
    for group_index, group in enumerate(CAPTURED_VALIDATION):
        invocations = [row for row in validated if row["group_index"] == group_index]
        records.append({**group, "exit_code": 0, "invocations": invocations})
    return records


def create_validation_receipt(execution: Any = None) -> dict[str, Any]:
    """Create a tested-byte receipt only from complete per-child execution results."""
    if not isinstance(execution, dict):
        raise AuditError("validation receipt requires an execution result object")
    _require_exact_keys(
        execution,
        frozenset(
            {
                "tested_implementation_refs",
                "tested_execution_tool_refs",
                "tested_security_materializations",
                "tested_validation_checkout",
                "tested_python_runtime",
                "tested_parser_smoke_inputs",
                "observations",
            }
        ),
        label="validation execution result",
    )
    tested_refs = execution.get("tested_implementation_refs")
    _require_exact_json_value(
        tested_refs,
        _audit_implementation_refs(),
        label="validation execution tested-byte refs",
    )
    tested_tools = execution.get("tested_execution_tool_refs")
    _require_exact_json_value(
        tested_tools,
        _execution_tool_refs(),
        label="validation execution tool refs",
    )
    tested_materializations = _validate_security_materialization_refs(
        execution.get("tested_security_materializations")
    )
    _require_exact_json_value(
        tested_materializations,
        _security_materialization_refs(),
        label="validation execution live security materializations",
    )
    tested_validation_checkout = _validate_validation_checkout_ref(
        execution.get("tested_validation_checkout")
    )
    _require_exact_json_value(
        tested_validation_checkout,
        _validation_checkout_ref(),
        label="validation execution live checkout materialization",
    )
    tested_python_runtime = _validate_python_runtime_ref(execution.get("tested_python_runtime"))
    _require_exact_json_value(
        tested_python_runtime,
        _python_runtime_ref(),
        label="validation execution live Python runtime",
    )
    tested_parser_smoke_inputs = _validate_parser_smoke_input_ref(
        execution.get("tested_parser_smoke_inputs")
    )
    _require_exact_json_value(
        tested_parser_smoke_inputs,
        _parser_smoke_input_ref(),
        label="validation execution live parser-smoke inputs",
    )
    return {
        "schema_version": 2,
        "issue": 976,
        "phase": "A",
        "observed_at": VALIDATION_GATE_DATE,
        "tested_implementation_refs": tested_refs,
        "tested_execution_tool_refs": tested_tools,
        "tested_security_materializations": tested_materializations,
        "tested_validation_checkout": tested_validation_checkout,
        "tested_python_runtime": tested_python_runtime,
        "tested_parser_smoke_inputs": tested_parser_smoke_inputs,
        "validation_plan_sha256": _validation_plan_sha256(),
        "validation_records": _validation_records_from_observations(execution.get("observations")),
        "receipt_origin": _validation_receipt_origin(),
    }


def _require_validation_receipt_identity(
    receipt: Mapping[str, Any], audit_refs: Sequence[Mapping[str, Any]]
) -> None:
    _require_exact_keys(
        receipt,
        frozenset(
            {
                "schema_version",
                "issue",
                "phase",
                "observed_at",
                "tested_implementation_refs",
                "tested_execution_tool_refs",
                "tested_security_materializations",
                "tested_validation_checkout",
                "tested_python_runtime",
                "tested_parser_smoke_inputs",
                "validation_plan_sha256",
                "validation_records",
                "receipt_origin",
            }
        ),
        label="validation receipt",
    )
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 2:
        raise AuditError("validation receipt schema drifted")
    if (
        type(receipt.get("issue")) is not int
        or receipt["issue"] != 976
        or receipt.get("phase") != "A"
    ):
        raise AuditError("validation receipt owner/phase drifted")
    try:
        _require_exact_json_value(
            receipt.get("tested_implementation_refs"),
            list(audit_refs),
            label="validation receipt tested-byte refs",
        )
    except AuditError as exc:
        raise AuditError(
            "validation receipt tested-byte refs are stale; rerun complete validation and "
            "create a new explicit receipt"
        ) from exc
    try:
        _require_exact_json_value(
            receipt.get("tested_execution_tool_refs"),
            _execution_tool_refs(),
            label="validation receipt execution tool refs",
        )
    except AuditError as exc:
        raise AuditError("validation receipt executable refs are stale") from exc
    try:
        tested_security = _validate_security_materialization_refs(
            receipt.get("tested_security_materializations")
        )
        _require_exact_json_value(
            tested_security,
            _security_materialization_refs(),
            label="validation receipt live security materializations",
        )
    except AuditError as exc:
        raise AuditError("validation receipt security materializations are stale") from exc
    try:
        tested_checkout = _validate_validation_checkout_ref(
            receipt.get("tested_validation_checkout")
        )
        _require_exact_json_value(
            tested_checkout,
            _validation_checkout_ref(),
            label="validation receipt live checkout materialization",
        )
    except AuditError as exc:
        raise AuditError("validation receipt checkout materialization is stale") from exc
    try:
        tested_runtime = _validate_python_runtime_ref(receipt.get("tested_python_runtime"))
        _require_exact_json_value(
            tested_runtime,
            _python_runtime_ref(),
            label="validation receipt live Python runtime",
        )
    except AuditError as exc:
        raise AuditError("validation receipt Python runtime is stale") from exc
    try:
        tested_parser_inputs = _validate_parser_smoke_input_ref(
            receipt.get("tested_parser_smoke_inputs")
        )
        _require_exact_json_value(
            tested_parser_inputs,
            _parser_smoke_input_ref(),
            label="validation receipt live parser-smoke inputs",
        )
    except AuditError as exc:
        raise AuditError("validation receipt parser-smoke inputs are stale") from exc
    if receipt.get("validation_plan_sha256") != _validation_plan_sha256():
        raise AuditError("validation receipt execution plan drifted")


def _validation_observations_from_records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != len(CAPTURED_VALIDATION):
        raise AuditError("validation receipt command/result records drifted")
    observations: list[dict[str, Any]] = []
    for expected, record in zip(CAPTURED_VALIDATION, records, strict=True):
        if not isinstance(record, dict):
            raise AuditError("validation receipt group record must be an object")
        _require_exact_keys(
            record,
            frozenset({*expected, "exit_code", "invocations"}),
            label="validation receipt group record",
        )
        for key, value in expected.items():
            _require_exact_json_value(
                record.get(key),
                value,
                label=f"validation receipt group {key}",
            )
        if type(record.get("exit_code")) is not int or record["exit_code"] != 0:
            raise AuditError("validation receipt group did not exit zero")
        invocations = record.get("invocations")
        if not isinstance(invocations, list):
            raise AuditError("validation receipt group has no per-child results")
        observations.extend(invocations)
    return observations


def _validate_validation_observed_at(raw: Any) -> None:
    if not isinstance(raw, str):
        raise AuditError("validation receipt observation date must be an exact ISO calendar date")
    try:
        observed_at = date.fromisoformat(raw)
        validation_gate_date = date.fromisoformat(VALIDATION_GATE_DATE)
    except ValueError as exc:
        raise AuditError(
            "validation receipt observation date must be an exact ISO calendar date"
        ) from exc
    if observed_at.isoformat() != raw:
        raise AuditError("validation receipt observation date must be an exact ISO calendar date")
    if observed_at != validation_gate_date:
        raise AuditError("validation receipt observation date drifted")


def _validate_validation_receipt(
    receipt: Mapping[str, Any], audit_refs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _require_validation_receipt_identity(receipt, audit_refs)
    records = receipt.get("validation_records")
    observations = _validation_observations_from_records(records)
    if records != _validation_records_from_observations(observations):
        raise AuditError("validation receipt command/result records drifted")
    origin = receipt.get("receipt_origin")
    try:
        _require_exact_json_value(
            origin,
            _validation_receipt_origin(),
            label="validation receipt origin",
        )
    except AuditError as exc:
        raise AuditError("validation receipt origin/retargeting contract drifted") from exc
    _validate_validation_observed_at(receipt.get("observed_at"))
    return dict(receipt)


def _pending_review() -> dict[str, Any]:
    return {
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
        "status": "pending final gate",
        "unresolved_p0_p1_p2": -1,
    }


def _read_stable_descriptor(descriptor: int, *, label: str) -> bytes:
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuditError(f"{label} is not a regular file")
        first = _read_descriptor_bytes(descriptor)
        middle = os.fstat(descriptor)
        second = _read_descriptor_bytes(descriptor)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise AuditError(f"unable to read stable {label}: {exc}") from exc
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if first != second or any(
        getattr(left, field) != getattr(right, field)
        for left, right in ((before, middle), (middle, after))
        for field in stable_fields
    ):
        raise AuditError(f"{label} changed while it was hashed")
    return first


def _read_reviewed_packet_source(
    source: Path,
    *,
    repo_root: Path | None = None,
    temp_root: Path = Path(tempfile.gettempdir()),
) -> bytes:
    relative = _root_relative_path(temp_root, source)
    root_fd, root_identity = _open_publication_root(temp_root)
    descriptor: int | None = None
    try:
        descriptor = _openat2_beneath(
            root_fd,
            relative,
            flags=(
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        opened_path = Path(f"/proc/self/fd/{descriptor}").resolve(strict=True)
        resolved_repo = (ROOT if repo_root is None else repo_root).resolve(strict=True)
        if opened_path == resolved_repo or resolved_repo in opened_path.parents:
            raise AuditError("reviewed packet source must remain outside the repository")
        content = _read_stable_descriptor(descriptor, label="reviewed packet source")
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("temporary root identity changed while reading reviewed packet")
        return content
    finally:
        _close_descriptors(descriptor, root_fd)


def _read_current_packet_source(path: Path) -> bytes:
    relative = _root_relative_path(ROOT, path)
    root_fd, root_identity = _open_publication_root(ROOT)
    descriptor: int | None = None
    try:
        descriptor = _openat2_beneath(
            root_fd,
            relative,
            flags=(
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        content = _read_stable_descriptor(descriptor, label="current pre-stamp packet source")
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("repository root identity changed while reading reviewed packet")
        return content
    finally:
        _close_descriptors(descriptor, root_fd)


def _current_review_packet(
    reviewed_packet_sources: Mapping[str, Path] | None,
) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    paths = (EVIDENCE_PATH, REPORT_PATH)
    expected_paths = {str(path.relative_to(ROOT)) for path in paths}
    if reviewed_packet_sources is None:
        try:
            contents = {
                str(path.relative_to(ROOT)): _read_current_packet_source(path) for path in paths
            }
        except OSError as exc:
            raise AuditError(
                f"unable to hash current pre-stamp packet for review receipt: {exc}"
            ) from exc
    else:
        if set(reviewed_packet_sources) != expected_paths:
            raise AuditError("reviewed packet source map is incomplete")
        contents = {
            label: _read_reviewed_packet_source(reviewed_packet_sources[label])
            for label in sorted(expected_paths)
        }
    refs = [
        {
            "path": label,
            "content_sha256": hashlib.sha256(contents[label]).hexdigest(),
        }
        for label in sorted(expected_paths)
    ]
    return refs, contents


def _validate_review_packet_refs(
    packet_refs: Any,
    *,
    verify_current_packet: bool,
    reviewed_packet_sources: Mapping[str, Path] | None = None,
) -> dict[str, bytes] | None:
    expected_paths = {str(EVIDENCE_PATH.relative_to(ROOT)), str(REPORT_PATH.relative_to(ROOT))}
    if not isinstance(packet_refs, list) or len(packet_refs) != 2:
        raise AuditError("review receipt packet refs are incomplete")
    received_paths: list[str] = []
    for row in packet_refs:
        if not isinstance(row, dict):
            raise AuditError("review receipt packet refs must be objects")
        _require_exact_keys(
            row,
            frozenset({"path", "content_sha256"}),
            label="review receipt packet ref",
        )
        path = row.get("path")
        digest = row.get("content_sha256")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise AuditError("review receipt packet hashes are malformed")
        received_paths.append(path)
    if len(set(received_paths)) != 2 or set(received_paths) != expected_paths:
        raise AuditError("review receipt packet refs are incomplete or duplicated")
    if verify_current_packet:
        current_packet_refs, current_packet = _current_review_packet(reviewed_packet_sources)
        received_packet_refs = [
            {
                "path": str(row["path"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in packet_refs
            if isinstance(row, dict)
        ]
        if sorted(received_packet_refs, key=lambda row: row["path"]) != sorted(
            current_packet_refs, key=lambda row: row["path"]
        ):
            raise AuditError("review receipt does not bind the exact current pre-stamp packet")
        return current_packet
    return None


def _validate_review_receipt(
    receipt: Mapping[str, Any],
    audit_refs: Sequence[Mapping[str, Any]],
    *,
    verify_current_packet: bool,
    reviewed_packet_sources: Mapping[str, Path] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes] | None]:
    _require_exact_keys(
        receipt,
        frozenset(
            {
                "schema_version",
                "issue",
                "phase",
                "reviewed_at",
                "review_origin",
                "reviewed_implementation_refs",
                "reviewed_packet_refs",
                "status_only_stamp_authorized",
                "review",
            }
        ),
        label="review receipt",
    )
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise AuditError("review receipt schema drifted")
    if (
        type(receipt.get("issue")) is not int
        or receipt["issue"] != 976
        or receipt.get("phase") != "A"
    ):
        raise AuditError("review receipt owner/phase drifted")
    try:
        _require_exact_json_value(
            receipt.get("reviewed_implementation_refs"),
            list(audit_refs),
            label="review receipt implementation refs",
        )
    except AuditError as exc:
        raise AuditError("review receipt implementation refs are stale") from exc
    review = receipt.get("review")
    if not isinstance(review, dict):
        raise AuditError("review receipt has no review result")
    _require_exact_keys(
        review,
        frozenset(
            {
                "requested_model",
                "requested_reasoning",
                "runtime_model",
                "runtime_reasoning",
                "status",
                "unresolved_p0_p1_p2",
            }
        ),
        label="review result",
    )
    expected_identity = {
        "requested_model": "GPT-5.6 Sol",
        "requested_reasoning": "Ultra",
        "runtime_model": "not visible",
        "runtime_reasoning": "not visible",
    }
    try:
        _require_exact_json_value(
            {key: review.get(key) for key in expected_identity},
            expected_identity,
            label="review receipt runtime identity",
        )
    except AuditError as exc:
        raise AuditError("review receipt runtime identity drifted") from exc
    expected_origin = {
        "reviewer_role": "independent clean-slate static reviewer",
        "reviewer_identity": "not visible",
        **expected_identity,
    }
    _validate_reviewed_at(receipt.get("reviewed_at"))
    try:
        _require_exact_json_value(
            receipt.get("review_origin"),
            expected_origin,
            label="review receipt origin",
        )
    except AuditError as exc:
        raise AuditError("review receipt origin attestation drifted") from exc
    unresolved = review.get("unresolved_p0_p1_p2")
    if (
        type(unresolved) is not int
        or unresolved != 0
        or review.get("status") != CLEAN_REVIEW_STATUS
    ):
        raise AuditError("review receipt is not a clean zero-unresolved verdict")
    reviewed_packet = _validate_review_packet_refs(
        receipt.get("reviewed_packet_refs"),
        verify_current_packet=verify_current_packet,
        reviewed_packet_sources=reviewed_packet_sources,
    )
    if receipt.get("status_only_stamp_authorized") is not True:
        raise AuditError("review receipt does not authorize the status-only artifact stamp")
    return dict(receipt), dict(review), reviewed_packet


def _validate_reviewed_at(raw: Any) -> None:
    if not isinstance(raw, str):
        raise AuditError("review receipt review date must be an exact ISO calendar date")
    try:
        reviewed_at = date.fromisoformat(raw)
        capture_date = date.fromisoformat(CAPTURE_DATE)
        review_gate_date = date.fromisoformat(REVIEW_GATE_DATE)
    except ValueError as exc:
        raise AuditError("review receipt review date must be an exact ISO calendar date") from exc
    if reviewed_at.isoformat() != raw:
        raise AuditError("review receipt review date must be an exact ISO calendar date")
    if reviewed_at < capture_date:
        raise AuditError("review receipt review date predates the evidence capture")
    if reviewed_at > review_gate_date:
        raise AuditError("review receipt review date exceeds the exact review gate date")
    if reviewed_at != review_gate_date:
        raise AuditError("review receipt review date does not equal the exact review gate date")


def _archived_receipts() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not EVIDENCE_PATH.is_file():
        return None, None
    payload = _read_json_mapping(EVIDENCE_PATH, label="archived Phase-A evidence")
    validation = payload.get("validation_receipt")
    review = payload.get("review_receipt")
    return (
        dict(validation) if isinstance(validation, dict) else None,
        dict(review) if isinstance(review, dict) else None,
    )


def _select_review_receipt(
    explicit: Mapping[str, Any] | None,
    archived: Mapping[str, Any] | None,
    *,
    for_write: bool,
) -> Mapping[str, Any] | None:
    if explicit is not None:
        return explicit
    if for_write and archived is not None:
        raise AuditError(
            "a write transition cannot reuse an archived clean review receipt; provide an "
            "explicit receipt bound to the exact current pre-stamp packet"
        )
    return archived


def _require_status_only_review_transform(
    pending_evidence: Mapping[str, Any],
    reviewed_packet: Mapping[str, bytes],
) -> None:
    expected = {
        str(EVIDENCE_PATH.relative_to(ROOT)): canonical_json(pending_evidence).encode("utf-8"),
        str(REPORT_PATH.relative_to(ROOT)): render_report(pending_evidence).encode("utf-8"),
    }
    if set(reviewed_packet) != set(expected):
        raise AuditError("reviewed pending packet source map is incomplete")
    for label, expected_bytes in expected.items():
        if reviewed_packet[label] != expected_bytes:
            raise AuditError(
                "status-only review stamp refused: preserved reviewed packet is not the "
                f"exact regenerated pending packet at {label}"
            )


def _require_review_refs_bind_regenerated_pending(
    pending_evidence: Mapping[str, Any],
    packet_refs: Any,
) -> None:
    _validate_review_packet_refs(packet_refs, verify_current_packet=False)
    expected_bytes = {
        str(EVIDENCE_PATH.relative_to(ROOT)): canonical_json(pending_evidence).encode("utf-8"),
        str(REPORT_PATH.relative_to(ROOT)): render_report(pending_evidence).encode("utf-8"),
    }
    expected_refs = sorted(
        (
            {
                "path": path,
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in expected_bytes.items()
        ),
        key=lambda row: row["path"],
    )
    received_refs = sorted(
        (
            {
                "path": str(row["path"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in packet_refs
        ),
        key=lambda row: row["path"],
    )
    if received_refs != expected_refs:
        raise AuditError(
            "review receipt does not bind the exact regenerated pending packet for the "
            "selected validation receipt"
        )


def build_evidence(
    *,
    validation_receipt: Mapping[str, Any] | None = None,
    review_receipt: Mapping[str, Any] | None = None,
    reviewed_packet_sources: Mapping[str, Path] | None = None,
    for_write: bool = False,
) -> dict[str, Any]:
    if reviewed_packet_sources is not None and review_receipt is None:
        raise AuditError("reviewed packet sources require an explicit review receipt")
    _require_safe_local_git_config(ROOT, label="Phase-A evidence checkout")
    _truth_contract_checks()
    exact_pr_inputs = require_exact_pr_inputs()
    audit_refs = _audit_implementation_refs()
    archived_validation, archived_review = _archived_receipts()
    selected_validation = (
        validation_receipt if validation_receipt is not None else archived_validation
    )
    if selected_validation is None:
        raise AuditError(
            "no immutable validation receipt is available; rerun complete validation and "
            "provide an explicit receipt"
        )
    validated_receipt = _validate_validation_receipt(selected_validation, audit_refs)
    selected_review = _select_review_receipt(
        review_receipt,
        archived_review,
        for_write=for_write,
    )
    validated_review_receipt: dict[str, Any] | None = None
    clean_review: dict[str, Any] | None = None
    reviewed_pending_packet: dict[str, bytes] | None = None
    if selected_review is not None:
        validated_review_receipt, clean_review, reviewed_pending_packet = _validate_review_receipt(
            selected_review,
            audit_refs,
            verify_current_packet=review_receipt is not None,
            reviewed_packet_sources=reviewed_packet_sources,
        )
    rules, paths = _owned_rules_and_paths()
    secondary_paths = _secondary_path_inventory(paths)
    with tempfile.TemporaryDirectory(prefix="metroliza-976-path-probe-") as temp_dir:
        path_probe = probe_path_permissions(Path(temp_dir))
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "audit": {
            "issue": 976,
            "phase": "A",
            "capture_date": CAPTURE_DATE,
            "external_observation_date": CAPTURE_DATE,
            "validation_gate_date": VALIDATION_GATE_DATE,
            "branch": BRANCH,
            "mode": "LOCAL-FIRST / ACTIONS-CI-DEFERRED / PARKED",
            "baseline_sha": BASELINE_SHA,
            "baseline_tree": BASELINE_TREE,
            "runtime_identity": RUNTIME_IDENTITY,
            "ledger_terminalized": False,
            "runtime_or_delivery_behavior_changed": False,
            "routing": list(ROUTING),
        },
        "scope": {
            "rule_count": len(rules),
            "path_count": len(paths),
            "secondary_path_count": len(secondary_paths),
            "secondary_tracked_path_count": sum(row["tracked"] for row in secondary_paths),
            "rules": rules,
            "paths": paths,
            "secondary_paths": secondary_paths,
        },
        "environment": CAPTURED_ENVIRONMENT,
        "ci": {
            "workflow": ".github/workflows/ci.yml",
            "permissions": "contents: read",
            "credential_persistence": False,
            "checkout_depth": 1,
            "tags_lfs_submodules": "disabled/default",
            "cache": "setup-python pip cache keyed by dependency files; correctness must be cold-cache independent",
            "concurrency": "ci-${workflow}-${ref}; cancellation enabled; push and PR refs do not coalesce",
            "jobs": list(WORKFLOW_ROWS),
            "exact_baseline_inventory": _workflow_step_inventory(),
            "observed_existing_run": {
                "run_id": 33151703847,
                "head_sha": BASELINE_SHA,
                "not_dispatched_by_phase_a": True,
                "static_checks": "success",
                "unit_tests": "failure; combined coverage process exit 139",
                "crash_seam": "SIGSEGV while executing test_industrial_analytics_dialog.py coverage shard",
                "crash_finding": "https://github.com/hexafe/metroliza/issues/998",
                "native_artifacts": "success",
                "windows_core_smoke": "success",
                "cmm_and_perf": "skipped by failed needs",
                "manual_packaging_and_windows_startup": "skipped",
                "artifact_count": 0,
            },
            "historical_object_probe": {
                "full_history": "pass at exact head with synthetic older terminal snapshot",
                "depth_1": "fail closed: audited commit unavailable locally",
                "current_pending_ledger": "passes without exercising historical resolution",
                "targeted_fetch": "correct only if every exact SHA is validated; lower transfer cost, more orchestration",
                "full_history_fetch": "simpler completeness; higher transfer cost; credentials must remain disabled",
                "finding_issue": "https://github.com/hexafe/metroliza/issues/991",
            },
        },
        "dependencies": {
            "python_manifests": _python_inventory(),
            "rust": _cargo_inventory(),
            "rust_toolchain_contract": {
                "ci": "1.95.0 exact",
                "local_capture": "1.98.0",
                "repository_toolchain_file": "absent",
                "packaging_helpers": "active cargo/rustc; version is not enforced",
                "pyo3_boundary": "0.21 requires explicit Python 3.11 here; host Python 3.14 failed",
            },
            "github_actions": _action_inventory(),
            "pre_commit_external": [
                {
                    "repository": "https://github.com/pre-commit/pre-commit-hooks",
                    "revision": "v5.0.0 mutable tag",
                },
                {
                    "repository": "https://github.com/astral-sh/ruff-pre-commit",
                    "revision": "v0.15.10 mutable tag",
                },
            ],
            "dependabot_grouping": {
                "pip": "all dependencies in one python-dependencies group",
                "github_actions": "all Actions in one github-actions group",
                "target_branch": "develop",
                "risk": "cross-family updates hide compatibility boundaries; #973 demonstrates it",
            },
            "external_git": [
                "hexafe-groupstats@14cc60e7412fa2647a8906f3f8833d0d789fc552",
                "hexafe-plotstats@1e2c72107d342f44a37e5fb78d7d76992ea60315",
                "oznak@ed51580dfdec9f91f6320c7937af6d65dd5a1290",
                "three security-audit sibling repositories pinned in ci.yml",
            ],
            "resolution_summary": (
                "Cargo lockfiles and Action/Git SHAs are exact. Most Python declarations are lower bounds; "
                "clean resolution is time-dependent and 29/35 unique #973 proposals are current no-ops."
            ),
            "isolated_resolution_comparison": {
                "capture_python": "CPython 3.11.16",
                "repository_python_contract": "3.11 minor; patch floats",
                "capture": PR973_RESOLUTION_CAPTURE,
                "unique_proposals": 35,
                "resolved_distribution_changes": 6,
                "pip_check": "observational pass only; exact argv/raw output not retained; see capture.pip_check_observations",
                "cold_offline": "failed because required artifacts were not cached; no wheelhouse exists",
            },
        },
        "pr_972": {
            "head": PR972_SHA,
            "tree": PR972_TREE,
            "verified_input": {
                "common_parent": exact_pr_inputs["common_parent"],
                "action_transitions": exact_pr_inputs["pr_972_action_transitions"],
            },
            "state": "open; unmodified",
            "matrix": list(PR972_MATRIX),
            "overall": "split compatibility input; safe candidate but not history-depth remediation",
            "evidence_currentness": (
                "existing successful runs 32932158352/32932162551 predate current develop; "
                "merge ref parent is 303568bc, not bba2b905"
            ),
            "provenance": "local Git objects verify the exact parent/head workflow transition and immutable Action SHAs; upstream tag/signature verification evidence was not retained and is not claimed",
        },
        "pr_973": {
            "head": PR973_SHA,
            "tree": PR973_TREE,
            "verified_input": {
                "common_parent": exact_pr_inputs["common_parent"],
                "declaration_transitions": exact_pr_inputs["pr_973_declaration_transitions"],
            },
            "state": "open; unmodified",
            "proposal_count": 35,
            "manifest_edit_count": 36,
            "resolved_change_count": 6,
            "declaration_edits": list(PR973_DECLARATION_EDITS),
            "resolution_capture": _direct_resolution_capture(),
            "resolution_rows": list(PR973_RESOLUTION_ROWS),
            "windows_resolution_rows": _windows_resolution_inventory(),
            "windows_resolution_capture": {
                "tool": "uv 0.12.5",
                "cache": f"{CAPTURE_UV_CACHE} (ephemeral; not a durable wheelhouse)",
                "target": "CPython 3.11 / x86_64-pc-windows-msvc",
                "stream_contract": "opaque SHA-256 capture commitments only; normalized resolver text/package rows were not retained, so counts and digests cannot be recomputed",
                "artifact_boundary": "no wheel filename, URL, size, signature or artifact SHA-256 retained; no Windows install or execution",
                "vcs_boundary": "VCS/source declarations are resolver inputs and are not proven Windows wheels by --only-binary selectors",
                "reproducibility": "exact child argv/cwd retained, but raw results and the ephemeral cache are unavailable; observational only, not durable replay evidence",
            },
            "families": list(PR973_FAMILIES),
            "overall": "blocked as one group; split into family PRs and repair Ruff findings",
            "existing_run_evidence": {
                "run_ids": [32932367574, 32932363678],
                "static": "failure: Ruff 0.16.4 reported 1,671 findings",
                "unit": (
                    "failure: 4 policy-contract tests; full run 4 failed, 3031 passed, "
                    "21 skipped, 98 subtests"
                ),
                "native": "success",
                "windows_core": "success",
                "dependent_and_manual_jobs": "skipped",
                "phase_a_actions_operation": "none; existing evidence read only",
            },
        },
        "build_command_inventory": _build_command_inventory(),
        "external_executor_inventory": list(EXTERNAL_EXECUTOR_INVENTORY),
        "version_identity_matrix": list(VERSION_IDENTITY_MATRIX),
        "packaging": _package_inventory(),
        "platform_failure_matrix": list(PLATFORM_FAILURE_MATRIX),
        "platform_evidence": {
            "linux_source": "receipt-bound pre-publication non-self pytest, static, parser, metadata, hygiene and security gates passed; full packet pytest and combined coverage are external post-publication parking gates and are not embedded as pass claims",
            "linux_installed_dependencies": "executed in isolated Python 3.11 environments",
            "linux_packaged": "static manifest and helper probes only; no release artifact accepted",
            "windows_source": "existing workflow evidence inspected; not rerun",
            "windows_packaged": "not executed; deferred to #901",
            "manual_release": "not executed; deferred to #901/#920",
        },
        "falsification": {
            "path_probe": path_probe,
            "controls": _falsifier_inventory(audit_refs),
        },
        "discovery_probes": _discovery_probe_inventory(audit_refs),
        "audit_implementation": audit_refs,
        "findings": list(FINDINGS),
        "durable_issue_evidence": [
            {
                **row,
                "observed_at": CAPTURE_DATE,
                "binding": "mutable public URL reference only; re-read remote content before relying on it",
            }
            for row in DURABLE_ISSUE_EVIDENCE
        ],
        "classifications": CLASSIFICATIONS,
        "residual_risks": list(RESIDUAL_RISKS),
        "validation_receipt": validated_receipt,
        "validation_receipt_sha256": hashlib.sha256(
            canonical_json(validated_receipt).encode("utf-8")
        ).hexdigest(),
        "validation": validated_receipt["validation_records"],
        "review_receipt": None,
        "review_receipt_sha256": None,
        "review": _pending_review(),
        "confidentiality": {
            "mutation_fixtures": "generated/sanitized temporary state only",
            "observational_sources": (
                "public repository history, public Issues/PRs and public hosted CI logs; "
                "accessed read-only"
            ),
            "public_hosted_ci_logs_accessed": True,
            "public_hosted_ci_logs_sanitization": (
                "project CI command/process diagnostics were inspected; no credential or "
                "customer/production payload was retained or published"
            ),
            "credentials_accessed": False,
            "customer_or_production_data_accessed": False,
            "nonpublic_or_proprietary_logs_accessed": False,
            "local_windows_ocr_diagnostic_payload_accessed": False,
            "windows_ocr_diagnostic_publication_boundary": (
                "exact source inspected only; baseline output is potentially sensitive raw JSON, "
                "not sanitized support evidence, and #1002 requires redaction/unsafe-opt-in controls"
            ),
            "secrets_published": False,
        },
        "phase_boundaries": {
            "ledger": "deferred to Phase B",
            "actions_ci": "not dispatched or rerun; no new/current-packet result claimed; existing exact-base run inspected read-only",
            "pull_request": "not opened or finalized",
            "release_artifact": "not created or published",
        },
        "lifecycle": {
            "evidence_construction": "repository and archived Git inputs are read-only; one sanitized path probe writes and removes an ephemeral operating-system-temp artifact; no repository/ref mutation occurs",
            "phase_a_packet_preflight": "mandatory for --write, --check and validation-receipt creation; optional --packet-preflight also applies the exact branch, exact HEAD and four-path guard to isolated read-only generation",
            "artifact_publication": "cooperating writes are serialized by a nonblocking inode lock on the bound Git-directory descriptor, held from pre-construction target snapshots through ordered publication and postguards; preexisting parents and each fresh final name are bound with Linux openat2 RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS beneath a held authorized-root descriptor, and names are created directly with O_CREAT|O_EXCL before data and exact 0644 metadata are fsynced and identity/hash/size/mode reverified; existing targets are never overwritten and review stamping uses exact preserved temporary sources plus an absent-target fresh-name install; the pair is not cross-file atomic, an interrupted direct creation can remain detectably partial, and recovery never rolls back, unlinks a public name or creates lexical ancestor directories; the threat boundary requires the repository/temporary root inode itself to remain under exclusive operator ownership while the command runs",
            "canonical_acceptance_gate": "plain --check is an exact branch/HEAD/four-path guarded point-in-time canonical comparison but not a writer lock or transaction; complete focused/full/coverage checks are rerun externally after receipt-bound publication because an artifact cannot non-circularly embed proof of checking its own final bytes",
            "validation_execution_identity": "all direct child executables are absolute and SHA-256/size/resolved-path bound, retained open for the complete suite and supplied to subprocess as held /proc/self/fd executables; the complete CPython base prefix and venv are copied without hardlinks into a private recursively read-only runtime that must match an independently reviewed exact complete portable-manifest/entry-count/pyvenv pin before any runtime code executes, pyvenv.cfg is uniquely parsed and semantically rebound, executable .pth files require exact path/content allowlisting, non-code .pth entries and every internal symlink resolve strictly inside the runtime, user-site loading is disabled, and effective prefixes/site roots/sys.path plus the full runtime and distribution inventory are bound before and after execution; Git guards require resolved git-dir and common-dir equality with the rooted checkout .git directory, reject unsafe local configuration and special index flags, independently compare the exact baseline index and every rooted tracked file, and disable system attributes, fsmonitor, hooks, untracked cache, external diff/text conversion and ambient configuration; every child runs from a private 0700 standalone no-hardlink checkout with a recursively read-only .git database/index, the exact baseline, two content-bound harness overlays, and an identity-bound test.db symlink included in the complete portable and filesystem-identity manifests; the symlink targets the sole 0600 regular output file in a private 0700 root outside the checkout, and both output-root and target device/inode identities are bound across execution so SQLite journal churn cannot mutate checkout directory identity; parser-smoke static inputs and an empty profile-output slot are published exclusively beneath a fresh UID-owned mode-0700 root, and static fixtures are reopened read-only before execution; every logical parser-root argv role is rewritten to a held /proc/self/fd alias, directory/file lexical identities and bytes are guarded around every parser child, init must populate the reserved profile inode before it is reopened read-only, and install outputs consumed by evidence are retained and frozen below mode-0500 ancestors; the receipt carries only the portable content projection, never descriptor numbers or inode metadata; Ruff, Python and mypy caches are likewise rooted outside the checkout; the security child audits equivalent read-only dual-manifest materializations of the exact pinned sibling commit trees; artifact freshness controls likewise require an explicit trusted output root and open the complete root-relative parent below it with Linux openat2 no-symlink/beneath resolution before hashing one stable single-link target descriptor; this local threat boundary excludes a hostile same-UID process and requires exclusive operator ownership of the executor checkout and all fresh validation roots for the complete command duration",
            "historical_object_requirement": "exact regeneration requires the authorized baseline plus the common parent and exact #972/#973 head objects; GIT_NO_LAZY_FETCH prevents implicit network acquisition",
            "shallow_ci_behavior": "baseline-independent JSON/Markdown schema, pointer/provenance bindings, cross-file rendering and audit-byte hashes are checked; exact baseline/PR regeneration tests are skipped when their archived objects are unavailable, and #991 owns the broader history contract",
            "phase_b": "reconcile or retire the one-shot generator/test before terminalization",
        },
    }
    evidence["evidence_registry"] = _build_evidence_registry(evidence)
    if validated_review_receipt is not None:
        _require_review_refs_bind_regenerated_pending(
            evidence,
            validated_review_receipt["reviewed_packet_refs"],
        )
        if review_receipt is not None:
            if reviewed_pending_packet is None:
                raise AuditError("explicit review receipt did not retain reviewed packet bytes")
            _require_status_only_review_transform(evidence, reviewed_pending_packet)
        if clean_review is None:
            raise AuditError("review receipt did not retain a clean review result")
        evidence["review_receipt"] = validated_review_receipt
        evidence["review_receipt_sha256"] = hashlib.sha256(
            canonical_json(validated_review_receipt).encode("utf-8")
        ).hexdigest()
        evidence["review"] = clean_review
    return evidence


def canonical_json(evidence: Mapping[str, Any]) -> str:
    return (
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    )


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return lines


def _evidence_links(references: Sequence[str]) -> str:
    return "; ".join(f"[{reference}](#{_evidence_anchor(reference)})" for reference in references)


def render_report(evidence: Mapping[str, Any]) -> str:
    lines = [
        "# Issue #976 Phase-A build, CI, dependency, packaging and Windows audit",
        "",
        "Status: **PHASE A PARKED — LEDGER/CI/PR DEFERRED**",
        "",
        "## Identity and boundary",
        "",
        f"- Baseline: `develop@{BASELINE_SHA}`",
        f"- Tree: `{BASELINE_TREE}`",
        f"- Branch: `{BRANCH}`",
        f"- Fixed historical capture/observation date: `{CAPTURE_DATE}`.",
        f"- Exact local validation-gate date: `{VALIDATION_GATE_DATE}`.",
        "- Requested runtime: GPT-5.6 Sol / Ultra; actual runtime model/reasoning: `not visible`.",
        "- This audit changes no workflow, manifest, dependency, packaging runtime/configuration, release metadata or application behavior.",
        "- The coverage ledger and shared bug-sweep README are not terminalized or modified in Phase A.",
        "- GitHub Actions were not dispatched or rerun; no new/current-packet result is claimed. Existing exact-base run 33151703847 was inspected and reported read-only. No PR or release artifact was created.",
        "",
        "### Coordinator, worker and reviewer routing",
        "",
    ]
    lines.extend(
        _markdown_table(
            ("Agent", "Role", "Lane", "Mode", "Requested", "Actual"),
            (
                (
                    route["agent_id"],
                    route["role"],
                    route["lane"],
                    route["mode"],
                    f"{route['requested_model']} / {route['requested_reasoning']}",
                    f"{route['runtime_model']} / {route['runtime_reasoning']}",
                )
                for route in evidence["audit"]["routing"]
            ),
        )
    )
    lines.extend(["", "### Content-addressed Phase-A audit implementation", ""])
    lines.extend(
        _markdown_table(
            ("Path", "Git blob SHA-1", "Content SHA-256", "Bytes", "Binding"),
            (
                (
                    row["path"],
                    row["git_blob_sha1"],
                    row["content_sha256"],
                    row["size_bytes"],
                    row["binding"],
                )
                for row in evidence["audit_implementation"]
            ),
        )
    )
    lines.extend(["", "### Per-invocation validation receipts", ""])
    lines.extend(
        _markdown_table(
            (
                "Sequence / group",
                "Tokenized argv / cwd",
                "Exact base environment",
                "Exit / stdout / stderr",
            ),
            (
                (
                    f"{invocation['sequence']} / {row['command']}",
                    f"{json.dumps(invocation['argv'], ensure_ascii=False)} / {invocation['cwd']}",
                    json.dumps(invocation["environment"], sort_keys=True, ensure_ascii=False),
                    f"{invocation['exit_code']} / sha256={invocation['stdout_sha256']} bytes={invocation['stdout_bytes']} / sha256={invocation['stderr_sha256']} bytes={invocation['stderr_bytes']}",
                )
                for row in evidence["validation"]
                for invocation in row["invocations"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "## Exact owned surface",
            "",
            f"The schema-v4 ledger expands to **{evidence['scope']['rule_count']} rules and {evidence['scope']['path_count']} unique primary paths** at the exact baseline.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            ("Rule", "Class", "Tier", "Paths", "Ledger/snapshot", "Phase-A disposition"),
            (
                (
                    rule["id"],
                    rule["class"],
                    rule["consequence_tier"],
                    rule["path_count"],
                    f"{rule['ledger_status']} / null",
                    rule["phase_a_status"],
                )
                for rule in evidence["scope"]["rules"]
            ),
        )
    )
    lines.extend(["", "### File/blob and per-path audit inventory", ""])
    lines.extend(
        _markdown_table(
            (
                "Path",
                "Rule",
                "Blob / SHA-256 / bytes",
                "Status / disposition",
                "Evidence",
                "Findings",
                "Residual risk",
                "Snapshot",
            ),
            (
                (
                    record["path"],
                    record["rule"],
                    f"{record['git_blob_sha1']} / {record['content_sha256']} / {record['size_bytes']}",
                    f"{record['phase_a_status']} / {record['disposition']}",
                    _evidence_links(record["evidence_refs"]),
                    (
                        "; ".join(
                            f"{finding_id} ({link})"
                            for finding_id, link in zip(
                                record["finding_ids"], record["finding_links"], strict=True
                            )
                        )
                        or "none"
                    ),
                    (
                        "none"
                        if record["residual_risk"] is None
                        else (
                            f"{record['residual_risk']['id']} / "
                            f"{record['residual_risk']['target_issue_or_phase']} / "
                            f"{record['residual_risk']['reason']}"
                        )
                    ),
                    f"{record['snapshot_status']} / null",
                )
                for record in evidence["scope"]["paths"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "## Relevant secondary paths",
            "",
            (
                f"This bounded evidence-only inventory contains **{evidence['scope']['secondary_path_count']}** "
                f"secondary records (**{evidence['scope']['secondary_tracked_path_count']}** tracked baseline "
                "paths and two explicit untracked contract paths). They do not transfer primary ownership "
                "and are not counted among the 58 #976 paths."
            ),
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Path",
                "Tracked / blob / SHA-256",
                "Role",
                "Baseline owner",
                "Evidence",
                "Execution / finding or residual",
                "Boundary",
            ),
            (
                (
                    record["path"],
                    (
                        f"yes / {record['git_blob_sha1']} / {record['content_sha256']}"
                        if record["tracked"]
                        else f"no / {record['missing_reason']}"
                    ),
                    "; ".join(record["roles"]),
                    (
                        f"#{record['primary_owner_at_baseline']['issue']} / "
                        f"{record['primary_owner_at_baseline']['rule']}"
                        if record["primary_owner_at_baseline"]
                        else "not tracked; no ledger owner"
                    ),
                    _evidence_links(record["evidence_refs"]),
                    f"{record['execution_status']} / {record['finding_or_residual']}",
                    record["relationship"],
                )
                for record in evidence["scope"]["secondary_paths"]
            ),
        )
    )
    lines.extend(["", "## CI truth table", ""])
    lines.extend(
        _markdown_table(
            ("Job", "Trigger", "Runner", "Needs", "Requiredness", "Artifact/evidence boundary"),
            (
                (
                    job["job"],
                    job["trigger"],
                    job["runner"],
                    ", ".join(job["needs"]) or "none",
                    job["blocking"],
                    job["false_boundary"],
                )
                for job in evidence["ci"]["jobs"]
            ),
        )
    )
    exact_workflow = evidence["ci"]["exact_baseline_inventory"]
    lines.extend(
        [
            "",
            "### Lossless baseline workflow inventory",
            "",
            (
                f"The exact `{exact_workflow['path']}` baseline object is blob "
                f"`{exact_workflow['baseline_blob']}` / SHA-256 "
                f"`{exact_workflow['content_sha256']}` ({exact_workflow['line_count']} lines). "
                "Each step below is parsed from that object; the JSON preserves its exact source YAML, "
                "line range and source-fragment hash. Default `success()` behavior is made explicit."
            ),
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            ("Job", "Lines", "Job if/needs", "Timeout", "Continue", "Env", "Tool resolution"),
            (
                (
                    job["job"],
                    f"{job['source_lines'][0]}-{job['source_lines'][1]}",
                    f"if={job['if'] or 'success()'}; needs={job['needs'] or 'none'}",
                    job["timeout_minutes"],
                    job["continue_on_error"],
                    json.dumps(job["env"], sort_keys=True, ensure_ascii=False),
                    "; ".join(job["tool_resolution"]) or "no installer/tool selector in job",
                )
                for job in exact_workflow["jobs"]
            ),
        )
    )
    lines.extend(["", "#### Exact steps, assertions, caches and artifacts", ""])
    lines.extend(
        _markdown_table(
            (
                "Job/#",
                "Lines",
                "Step / declared id / shell",
                "Effective if / continue",
                "Exact uses or run",
                "With / env",
                "Cache / artifact / failure boundary",
            ),
            (
                (
                    f"{job['job']}/{step['index']}",
                    f"{step['source_lines'][0]}-{step['source_lines'][1]}",
                    f"{step['name']} / {step['id'] or 'none'} / {step['shell'] or 'runner default'}",
                    f"{step['effective_if']} / {step['continue_on_error']}",
                    (step["uses"] or step["run"] or "").replace("\n", "<br>"),
                    (
                        "with="
                        + json.dumps(step["with"], sort_keys=True, ensure_ascii=False)
                        + "; env="
                        + json.dumps(step["env"], sort_keys=True, ensure_ascii=False)
                    ).replace("\n", "<br>"),
                    (
                        json.dumps(
                            step.get("cache_semantics") or step.get("artifact_semantics") or {},
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                        + "; "
                        + step["skip_and_failure_semantics"]
                    ).replace("\n", "<br>"),
                )
                for job in exact_workflow["jobs"]
                for step in job["steps"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "Checkout credentials are disabled, but all checkout steps use the default depth 1; tags, LFS and submodules remain disabled/default. Runners, Python patch releases, pip, wheel, APT packages and most Python dependency resolutions float. Rust is fixed to 1.95.0 in CI. GitHub Actions and CI sibling checkouts are SHA-pinned; two pre-commit hook repositories use mutable tags. Concurrency cancels only the same workflow/ref; push and PR merge refs can both run. No final aggregate job exists.",
            "",
            "The paired historical-object probe passed in full history and failed closed in a depth-1 clone at the same head. Pending-only rules hide that constraint today. [#991](https://github.com/hexafe/metroliza/issues/991) owns the workflow correction. Full history is the simpler correctness proof; targeted acquisition is lower cost but must enumerate and validate every exact terminal SHA. Neither strategy may enable credential persistence or weaken the validator.",
            "",
            "Existing run `33151703847` was inspected read-only at the exact baseline: static, native and Windows-core succeeded; unit coverage received SIGSEGV while executing the `test_industrial_analytics_dialog.py` shard; CMM/performance and manual lanes skipped; artifact count was zero. [#998](https://github.com/hexafe/metroliza/issues/998) owns the P1 bounded root-cause hypothesis. Missing failure/coverage artifacts and skip observability route to #914.",
            "",
            "## Dependency and toolchain inventory",
            "",
            "The JSON evidence contains every Python declaration; all 36 exact #973 declaration edits; the 35-row baseline/proposal direct-resolution map; every direct Cargo manifest and every per-lock package record without cross-lock overwrites; and every SHA-pinned Action occurrence. Cargo lockfiles and Git/Action SHAs are exact. Python resolution is primarily lower-bound and time-dependent; #913 owns consolidation. Only six resolved distributions changed for 35 unique proposals. CI fixes Rust at 1.95.0, while local helpers have no repository toolchain file and use the active compiler. Pre-commit external sources use mutable version tags; its Ruff 0.15.10 tag also conflicts with #973.",
            "",
            "### PR #972 Action-major decisions",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Action",
                "From",
                "To",
                "Exact commit",
                "Decision",
                "Node/runner and compatibility boundary",
            ),
            (
                (
                    row["action"],
                    row["from"],
                    row["to"],
                    f"[{row['sha']}](https://github.com/{row['action']}/commit/{row['sha']})",
                    row["decision"],
                    row["notes"],
                )
                for row in evidence["pr_972"]["matrix"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "PR #972 stays open and untouched. Its immutable SHAs/Node 24 upgrades are compatible candidates on GitHub-hosted runners, but it preserves depth 1 and its eleven checkout comments remain stale `# v5`. Existing successful runs predate the current base; refresh/retest is required. This audit neither approves nor merges it.",
            "",
            "### PR #973 exact declaration edits",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Family",
                "Manifest",
                "Distribution",
                "Exact old declaration",
                "Exact new declaration",
            ),
            (
                (row["family"], row["path"], row["name"], row["old"], row["new"])
                for row in evidence["pr_973"]["declaration_edits"]
            ),
        )
    )
    lines.extend(["", "### PR #973 captured direct-resolution map", ""])
    lines.extend(
        _markdown_table(
            (
                "Family",
                "Name",
                "Baseline",
                "Proposal",
                "Requires-Python",
                "Installed WHEEL tags",
                "Provenance boundary",
            ),
            (
                (
                    row["family"],
                    row["name"],
                    row["baseline"]["resolved_version"],
                    row["proposal"]["resolved_version"],
                    row["proposal"]["requires_python"] or "not published",
                    ", ".join(row["proposal"]["wheel_tags"]),
                    row["source_provenance"] + "; " + row["artifact_provenance_boundary"],
                )
                for row in evidence["pr_973"]["resolution_rows"]
            ),
        )
    )
    resolution_capture = evidence["pr_973"]["resolution_capture"]
    lines.extend(
        [
            "",
            "The retained 35-row metadata arrays are recomputed as SHA-256 `"
            + resolution_capture["baseline_retained_rows_sha256"]
            + "` (baseline) and `"
            + resolution_capture["proposal_retained_rows_sha256"]
            + "` (proposal) using: "
            + resolution_capture["retained_row_normalization"]
            + ". Earlier capture commitments `"
            + resolution_capture["opaque_baseline_capture_sha256"]
            + "` / `"
            + resolution_capture["opaque_proposal_capture_sha256"]
            + "` are preserved but explicitly unverified because their original raw streams were not retained. Individual wheel filenames, URLs, sizes, signatures and hashes were not retained and are not claimed.",
            "",
            "#### Windows CPython 3.11 resolution observations",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Input paths",
                "Observed rows",
                "Opaque capture SHA-256",
                "Recomputed?",
                "Binary policy",
                "Exact argv",
                "Cwd / boundary",
            ),
            (
                (
                    f"{row['input']}: {', '.join(row['input_paths'])}",
                    row["observed_rows"],
                    row["opaque_capture_sha256"]
                    or (
                        "unavailable; malformed commitment="
                        + row["malformed_opaque_capture_commitment"]
                    ),
                    f"rows={row['row_count_recomputed']}; digest={row['digest_recomputed']}",
                    row["binary_policy"],
                    row["argv"],
                    f"{row['cwd']}; {row['evidence_boundary']}",
                )
                for row in evidence["pr_973"]["windows_resolution_rows"]
            ),
        )
    )
    capture = evidence["pr_973"]["windows_resolution_capture"]
    lines.extend(
        [
            "",
            f"Tool/cache/target: {capture['tool']}; {capture['cache']}; {capture['target']}. {capture['stream_contract']}. {capture['artifact_boundary']}. {capture['vcs_boundary']}. Reproducibility boundary: {capture['reproducibility']}.",
            "",
            "### PR #973 compatibility families",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Family",
                "Python 3.11",
                "Linux artifacts",
                "Windows evidence",
                "API risks",
                "Conflicts",
                "Downstream",
                "Decision/owner",
            ),
            (
                (
                    family["family"],
                    family["python_311"],
                    family["linux_artifacts"],
                    family["windows_evidence"],
                    family["api_risks"],
                    family["conflicts"],
                    family["downstream_waves"],
                    f"{family['decision']} — {family['owner']}",
                )
                for family in evidence["pr_973"]["families"]
            ),
        )
    )
    lines.extend(["", "#### Captured family commands and observed results", ""])
    lines.extend(
        _markdown_table(
            ("Family", "Captured argv", "Cwd", "Exit", "Observed result"),
            (
                (
                    family["family"],
                    command["argv"],
                    command["cwd"],
                    command["exit_code"],
                    command["result"],
                )
                for family in evidence["pr_973"]["families"]
                for command in family["commands"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "PR #973 stays open and untouched. Fresh Linux/Python 3.11 resolution changed only six distributions despite 35 unique proposals, so the group is not a lock or reproducibility mechanism. Import smoke was supplemented with family workflows. Ruff 0.16.4 produces 1,671 findings on the exact PR head (#996); four synchronized policy tests also fail. Qt/OpenCV/OCR/package changes still lack packaged-Windows proof. Overall decision: **blocked as one group; split and retest**.",
            "",
            "## Build/install/package command inventory",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Path",
                "Surface",
                "Exact command form",
                "Declared options",
                "Callers / platform",
                "Output / hard-failure contract",
                "Exact source",
            ),
            (
                (
                    row["path"],
                    row["surface"],
                    row["command"],
                    ", ".join(row["declared_options"]) or "none",
                    (
                        f"declared={'; '.join(row['callers'])}; exact_refs="
                        + "; ".join(
                            f"{edge['path']}:{','.join(str(line) for line in edge['line_numbers'])}"
                            for edge in row["baseline_reference_edges"]
                        )
                        + f" / {row['platform']} / {row['environment']}"
                    ),
                    f"{row['output_contract']} / {row['failure_contract']}",
                    f"{row['git_blob_sha1']} / {row['content_sha256']} / {row['status']}",
                )
                for row in evidence["build_command_inventory"]
            ),
        )
    )
    lines.extend(["", "### Direct external executor families", ""])
    lines.extend(
        _markdown_table(
            ("ID", "Executor", "Argv variant/template and exact callers", "Contract"),
            (
                (
                    row["id"],
                    row["executor"],
                    "; ".join(
                        f"{contract['argv']} <- {', '.join(contract['callers'])}"
                        for contract in row["argv_contracts"]
                    ),
                    row["contract"],
                )
                for row in evidence["external_executor_inventory"]
            ),
        )
    )
    lines.extend(["", "## Version and build identity matrix", ""])
    lines.extend(
        _markdown_table(
            (
                "Channel",
                "Exact value",
                "Source / consumer",
                "Verification / result",
                "Limitation / owner",
            ),
            (
                (
                    row["channel"],
                    row["value"],
                    f"{row['source']} / {row['consumer']}",
                    f"{row['verification']} / {row['result']}",
                    f"{row['limitation']} / {row['issue'] or 'no finding'}",
                )
                for row in evidence["version_identity_matrix"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "## Packaging and resource contract",
            "",
            "PyInstaller has onefile/onedir specs, explicit canonical/compatibility hidden imports, required PyMuPDF/OCR/industrial/scientific package collection, Windows Python runtime DLL discovery, Plotly offline JavaScript, optional vendored OCR models, notices and build provenance. [#1001](https://github.com/hexafe/metroliza/issues/1001) owns its confirmed acceptance of same-release provenance that is stale for the active Git checkout/build attempt. Nuitka has onefile/standalone paths with explicit packages/modules/assets and token exclusion. [#992](https://github.com/hexafe/metroliza/issues/992) owns its confirmed mode-specific stale-artifact defect. [#994](https://github.com/hexafe/metroliza/issues/994) owns the missing Plotly companion notice, [#997](https://github.com/hexafe/metroliza/issues/997) owns pre-execution VC redistributable provenance verification, [#999](https://github.com/hexafe/metroliza/issues/999) owns the fixed-name third-party inventory freshness defect, and [#1003](https://github.com/hexafe/metroliza/issues/1003) owns interrupted RapidOCR fetch temporary-file cleanup.",
            "PyInstaller specs embed the generated manifest. Artifact-hash sidecars are caller-specific: the PowerShell builders stage them, while the manual Linux `packaging-smoke` workflow invokes the spec and notice staging only. Nuitka has neither equivalent embedded provenance nor sidecar binding; #920 retains the policy/acceptance decision.",
            "",
            "Manual PDFs/help content is not embedded by either package manifest; the supported online help behavior is not misclassified as offline evidence. #955 owns offline/manual acceptance. Source/package collection does not prove installed-wheel or frozen discovery; #984/#901 retain those gates. [#1004](https://github.com/hexafe/metroliza/issues/1004) owns the confirmed parser self-service `--sample` argparse crash; the receipt therefore exercises existing workspace-derived sample discovery only beneath held, non-writable fixture directories.",
            "",
        ]
    )
    pyinstaller = evidence["packaging"]["pyinstaller"]
    lines.extend(["### PyInstaller exact contract", ""])
    lines.extend(
        _markdown_table(
            (
                "Modes",
                "Explicit hidden imports",
                "Dynamic collections",
                "Required collections",
                "Optional metadata",
                "Runtime DLL globs",
                "Discovery",
            ),
            [
                (
                    ", ".join(pyinstaller["modes"]),
                    ", ".join(pyinstaller["explicit_hiddenimports"]),
                    ", ".join(pyinstaller["dynamic_collect_submodules_variables"]),
                    ", ".join(pyinstaller["required_package_data_binary_submodule_collections"]),
                    ", ".join(pyinstaller["optional_distribution_metadata"]),
                    ", ".join(pyinstaller["windows_runtime_dll_globs"]),
                    f"source={pyinstaller['source_discovery']}; installed={pyinstaller['installed_discovery']}; frozen={pyinstaller['frozen_discovery']}",
                )
            ],
        )
    )
    nuitka = evidence["packaging"]["nuitka"]
    lines.extend(["", "### Nuitka exact contract", ""])
    lines.extend(
        _markdown_table(
            (
                "Modes",
                "Literal flags",
                "Native modules",
                "PDF modules",
                "OCR arguments",
                "Token exclusions",
                "Credential/discovery boundary",
            ),
            [
                (
                    ", ".join(nuitka["modes"]),
                    ", ".join(nuitka["literal_include_and_plugin_flags"]),
                    ", ".join(nuitka["conditional_native_modules"]),
                    ", ".join(nuitka["conditional_pdf_modules"]),
                    ", ".join(nuitka["conditional_ocr_arguments"]),
                    ", ".join(nuitka["token_exclusions"]),
                    f"{nuitka['credential_bundle']}; source={nuitka['source_discovery']}; installed={nuitka['installed_discovery']}; frozen={nuitka['frozen_discovery']}",
                )
            ],
        )
    )
    lines.extend(["", "### Resource, destination and discovery matrix", ""])
    lines.extend(
        _markdown_table(
            (
                "Source",
                "Tracked / exact hash",
                "Kind",
                "Per-mode inclusion",
                "Condition / destination",
                "Source / installed / frozen",
                "Evidence / disposition",
            ),
            (
                (
                    row["source"],
                    (
                        f"yes / {row['git_blob_sha1']} / {row['content_sha256']}"
                        if row["tracked"]
                        else "no / generated or absent contract input"
                    ),
                    row["kind"],
                    json.dumps(row["packagers_and_modes"], sort_keys=True, ensure_ascii=False),
                    f"{row['required_condition']} / {row['destination']}",
                    f"{row['discovery']['source']} / {row['discovery']['installed']} / {row['discovery']['frozen']}",
                    f"{_evidence_links(row['evidence_refs'])} / {row['finding_or_residual'] or 'no finding'}",
                )
                for row in evidence["packaging"]["resources"]
            ),
        )
    )
    lines.extend(["", "### RapidOCR exact-baseline hash validation", ""])
    lines.extend(
        _markdown_table(
            ("Source", "Manifest source", "Expected SHA-256", "Actual SHA-256", "Match / Git blob"),
            (
                (
                    row["source"],
                    row["manifest_source"],
                    row["expected_sha256"],
                    row["actual_sha256"],
                    f"{row['match']} / {row['git_blob_sha1']}",
                )
                for row in evidence["packaging"]["ocr_model_hashes"]
            ),
        )
    )
    lines.extend(["", "## Linux, Windows, manual and failure-path evidence", ""])
    lines.extend(
        _markdown_table(
            ("Surface", "Evidence"),
            (
                (key.replace("_", " "), value)
                for key, value in sorted(evidence["platform_evidence"].items())
            ),
        )
    )
    lines.extend(
        [
            "",
            "Windows OCR setup/diagnostic evidence has a confirmed false-green boundary: "
            "the Python diagnostic serializes failed required smoke rows but returns zero, so "
            "PowerShell checked-child handling cannot detect those failures. "
            "[#1000](https://github.com/hexafe/metroliza/issues/1000) owns the repair. The same "
            "diagnostic emits potentially sensitive raw local/environment/document/database data; "
            "it is do-not-publish evidence pending redaction/unsafe-opt-in controls under "
            "[#1002](https://github.com/hexafe/metroliza/issues/1002).",
            "",
            "### Platform and failure matrix",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "ID",
                "Platform/path",
                "Scenario",
                "Exact command or unavailable reason",
                "Harness/subject result",
                "Evidence class / limitation",
                "Owner/gate",
            ),
            (
                (
                    row["id"],
                    row["platform_path"],
                    row["scenario"],
                    row["command"],
                    f"exit={row['exit_code']} / {row['result']}",
                    f"{row['evidence_class']} / {row['limitation']}",
                    row["owner_or_gate"],
                )
                for row in evidence["platform_failure_matrix"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "Linux source and isolated dependency evidence is not represented as Windows, packaged or release evidence. Clean-machine Windows, packaged Qt/OCR/native DLL behavior, legal sign-off and user-flow promotion remain deferred to #901/#920.",
            "",
            "## Required falsification results",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Control",
                "Class/result",
                "Production/supporting seam",
                "Negative control",
                "Exact command / cwd",
                "Fixture / expected subject outcome",
                "Harness",
                "Subject / implementation provenance",
            ),
            (
                (
                    row["id"],
                    f"{row['control_class']} / {row['result']}",
                    row["production_gate"],
                    row["negative_control"],
                    f"{row['command']} / cwd={row['cwd']}",
                    f"{row['fixture']} / {row['subject_outcome']}",
                    f"exit={row['harness_exit_code']}; sources={'; '.join(row['source_paths'])}",
                    (
                        f"subjects={'; '.join(row['subject_refs'])}; "
                        f"production blobs={'; '.join(ref['git_blob_sha1'] for ref in row['production_blob_refs'])}; "
                        f"audit SHA-256={'; '.join(ref['content_sha256'] for ref in row['audit_mutation_refs'])}"
                    ),
                )
                for row in evidence["falsification"]["controls"]
            ),
        )
    )
    lines.extend(["", "### Discovery probe outcomes", ""])
    lines.extend(
        _markdown_table(
            (
                "ID / probe",
                "Exact command(s) / cwd",
                "Subject refs",
                "Argv retained / durable replay",
                "Harness / subject exit",
                "Exit semantics",
                "Result / replay boundary / audit-record SHA-256",
            ),
            (
                (
                    f"{row['id']} / {row['probe']}",
                    (
                        f"{row['command']}"
                        + (
                            f"; negative control: {row['negative_control_command']}"
                            if row.get("negative_control_command")
                            else ""
                        )
                        + f" / {row['cwd']}"
                    ),
                    "; ".join(row["subject_refs"]),
                    f"{row['exact_argv_retained']} / {row['durably_reproducible']}",
                    f"{row['harness_exit_code']} / {row['subject_exit_code']}",
                    row["exit_semantics"],
                    (
                        f"{row['result']}; replay={row['replay_boundary']}; audit record="
                        + "; ".join(ref["content_sha256"] for ref in row["audit_record_refs"])
                    ),
                )
                for row in evidence["discovery_probes"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "All mutation fixtures use generated/sanitized temporary state; observational controls use public repository, Issue/PR and hosted-project CI evidence read-only. The spaces/non-ASCII/long-path round trip passed; a read-only target fails through the isolated unit control. Public hosted CI command/process logs were inspected for the exact-base SIGSEGV, but no credential, customer/production payload, nonpublic log or proprietary measurement was accessed, retained or published.",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            ("ID", "Severity", "Taxonomy", "Disposition", "Finding", "Owner"),
            (
                (
                    row["id"],
                    row["severity"],
                    row["taxonomy"],
                    row["disposition"],
                    row["summary"],
                    row["issue"],
                )
                for row in evidence["findings"]
            ),
        )
    )
    lines.extend(["", "### Durable focused/reused Issue evidence", ""])
    lines.extend(
        _markdown_table(
            ("Issue", "Role", "Evidence", "Status"),
            (
                (
                    f"#{row['issue']}",
                    row["role"],
                    row["evidence_url"],
                    row["status"],
                )
                for row in evidence["durable_issue_evidence"]
            ),
        )
    )
    lines.extend(
        [
            "",
            "No P0 supply-chain, secret, unsafe-publication, deterministic artifact/data-loss or current materially false release-evidence event was found. Confirmed defects are parked as focused or authoritative existing Issues and are not fixed here. Four exact-base comments were posted where authorized; #920/#955 remain linked to their authoritative Issues because the remote-mutation gate did not authorize additional comments.",
            "",
            "## Accepted behaviors, rejected false positives and hypotheses",
            "",
        ]
    )
    for classification, entries in evidence["classifications"].items():
        lines.extend([f"### {classification.replace('_', ' ').title()}", ""])
        lines.extend(f"- {entry}" for entry in entries)
        lines.append("")
    lines.extend(["## Residual risks", ""])
    lines.extend(
        _markdown_table(
            (
                "ID",
                "Severity / taxonomy",
                "Classification / reason",
                "Accountable owner / target",
                "Next gate",
                "Preserved seam",
            ),
            (
                (
                    row["id"],
                    f"{row['severity']} / {row['taxonomy']}",
                    f"{row['classification']} / {row['reason']}",
                    f"{row['accountable_owner']} / {row['target_issue_or_phase']}",
                    row["next_gate"],
                    row["preserved_seam"],
                )
                for row in evidence["residual_risks"]
            ),
        )
    )
    lines.extend(["", "## Evidence reference index", ""])
    lines.extend(
        _markdown_table(
            ("ID", "Kind / JSON pointer", "Exact binding", "Result / report section"),
            (
                (
                    f'<a id="{record["report_anchor"]}"></a>`{reference}`',
                    f"{record['kind']} / `{record['json_pointer']}`",
                    record["binding"],
                    f"{record['result']} / {record['report_section']}",
                )
                for reference, record in evidence["evidence_registry"].items()
            ),
        )
    )
    lines.extend(["", "## Validation and review", ""])
    lines.extend(
        [
            "Validation receipt SHA-256: `"
            + evidence["validation_receipt_sha256"]
            + "`; tested implementation SHA-256: "
            + ", ".join(
                f"`{row['path']}={row['content_sha256']}`"
                for row in evidence["validation_receipt"]["tested_implementation_refs"]
            )
            + ".",
            "",
            "The per-invocation table above is authoritative for receipt-retained portable "
            "logical argv, environment and cwd. Parser logical operands execute only through "
            "unretained role-checked held-descriptor aliases. The grouped table below retains "
            "only the captured human-readable display plan.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Command/gate",
                "Captured display command(s)",
                "Cwd / observed",
                "Exit / result",
                "Subject / binding",
            ),
            (
                (
                    row["command"],
                    "; ".join(row["argv"]),
                    f"{row['cwd']} / {row['observed_at']}",
                    f"{row['exit_code']} / {row['result']}",
                    f"{'; '.join(row['subject_refs'])} / {row['binding']}",
                )
                for row in evidence["validation"]
            ),
        )
    )
    lines.extend(
        [
            "",
            f"Independent review: {evidence['review']['status']}; unresolved P0/P1/P2 = {evidence['review']['unresolved_p0_p1_p2']}.",
        ]
    )
    review_receipt = evidence["review_receipt"]
    if review_receipt is not None:
        lines.extend(
            [
                "",
                f"Review receipt SHA-256: `{evidence['review_receipt_sha256']}`; reviewed at `{review_receipt['reviewed_at']}`; reviewer identity: `{review_receipt['review_origin']['reviewer_identity']}`.",
                "",
                "Reviewed pre-stamp packet: "
                + ", ".join(
                    f"`{row['path']}={row['content_sha256']}`"
                    for row in review_receipt["reviewed_packet_refs"]
                )
                + ".",
            ]
        )
    lines.extend(
        [
            "",
            "## Phase-A disposition",
            "",
            "All 12 owned rules are audited at the exact baseline but remain non-terminal in the unchanged ledger. Phase B must reconcile then-current `develop`, bind schema-v4 snapshots and rerun final local/review/CI gates. Phase A does not claim ledger, CI, PR, Windows-package or release completion.",
            "",
            "**PHASE A PARKED — LEDGER/CI/PR DEFERRED**",
            "",
        ]
    )
    return "\n".join(lines)


def _compare(path: Path, expected: str) -> None:
    expected_bytes = expected.encode("utf-8")
    with _rooted_parent_directory(ROOT, path) as parent_fd:
        state = _capture_public_state(path, parent_fd)
    if not state.exists or state.mode != 0o644:
        raise AuditError(f"generated artifact mode is not exact regular 0644: {path}")
    if (
        state.size_bytes != len(expected_bytes)
        or state.content_sha256 != hashlib.sha256(expected_bytes).hexdigest()
    ):
        raise AuditError(f"generated artifact is stale or non-deterministic: {path}")


def require_safe_artifact_targets(
    root: Path,
    targets: Sequence[Path],
    allowed_paths: frozenset[str],
) -> None:
    resolved_root = root.resolve()
    for target in targets:
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise AuditError(f"artifact target is outside the repository: {target}") from exc
        if relative.as_posix() not in allowed_paths:
            raise AuditError(f"artifact target is outside the authorized packet: {relative}")
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise AuditError(f"artifact target has a symlink component: {current}")
            if not current.exists():
                break
        resolved = target.resolve(strict=False)
        if resolved_root not in resolved.parents:
            raise AuditError(f"artifact target resolves outside the repository: {target}")
        if target.exists() and not target.is_file():
            raise AuditError(f"artifact target is not a regular file: {target}")


def _stat_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _close_descriptors(*descriptors: int | None) -> None:
    errors: list[OSError] = []
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError as exc:
            errors.append(exc)
    if errors and sys.exc_info()[0] is None:
        raise AuditError(
            "descriptor cleanup failed after all owned descriptors were attempted: "
            + "; ".join(str(error) for error in errors)
        )


def _open_publication_directory(parent: Path) -> tuple[int, tuple[int, int]]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(parent, flags)
    try:
        opened_identity = _stat_identity(os.fstat(descriptor))
        if opened_identity != _stat_identity(os.stat(parent, follow_symlinks=False)):
            raise AuditError("isolated output parent identity changed during publication")
        return descriptor, opened_identity
    except BaseException:
        os.close(descriptor)
        raise


class _PublicState(NamedTuple):
    exists: bool
    identity: tuple[int, int] | None
    mode: int | None
    size_bytes: int | None
    content_sha256: str | None


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


def _require_openat2_publication_support() -> None:
    if sys.platform != "linux" or fcntl is None or not hasattr(ctypes.CDLL(None), "syscall"):
        raise AuditError("root-anchored no-clobber publication requires Linux openat2 support")


def _root_relative_path(root: Path, target: Path) -> str:
    lexical_root = Path(os.path.abspath(root))
    lexical_target = Path(os.path.abspath(target))
    try:
        relative = lexical_target.relative_to(lexical_root)
    except ValueError as exc:
        raise AuditError(f"publication target is outside its authorized root: {target}") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise AuditError(f"publication target has an unsafe relative path: {target}")
    return str(relative)


def _open_publication_root(root: Path) -> tuple[int, tuple[int, int]]:
    lexical = Path(os.path.abspath(root))
    metadata = os.stat(lexical, follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode):
        raise AuditError(f"publication root is not a directory: {root}")
    descriptor = os.open(
        lexical,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        identity = _stat_identity(os.fstat(descriptor))
        if identity != _stat_identity(metadata):
            raise AuditError("publication root identity changed during open")
        return descriptor, identity
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def _rooted_parent_directory(root: Path, target: Path) -> Iterable[int]:
    relative_path = _root_relative_path(root, target)
    parent_relative = str(Path(relative_path).parent)
    root_fd, root_identity = _open_publication_root(root)
    parent_fd: int | None = None
    try:
        parent_fd = _openat2_beneath(
            root_fd,
            parent_relative,
            flags=(
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        parent_metadata = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise AuditError("publication parent is not a rooted directory")
        parent_identity = _stat_identity(parent_metadata)
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("publication root identity changed while opening parent")
        yield parent_fd
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("publication root identity changed while parent was held")
        verification_fd: int | None = None
        try:
            verification_fd = _openat2_beneath(
                root_fd,
                parent_relative,
                flags=(
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                ),
            )
            if _stat_identity(os.fstat(verification_fd)) != parent_identity:
                raise AuditError("publication parent identity changed while held")
        except AuditError as exc:
            if str(exc) == "publication parent identity changed while held":
                raise
            raise AuditError("publication parent identity changed while held") from exc
        finally:
            _close_descriptors(verification_fd)
    finally:
        _close_descriptors(parent_fd, root_fd)


def _openat2_beneath(
    root_fd: int,
    relative_path: str,
    *,
    flags: int,
    mode: int = 0,
) -> int:
    _require_openat2_publication_support()
    how = _OpenHow(
        flags=flags,
        mode=mode,
        resolve=0x01 | 0x02 | 0x04 | 0x08,  # NO_XDEV|NO_MAGICLINKS|NO_SYMLINKS|BENEATH
    )
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    descriptor = libc.syscall(
        437,  # SYS_openat2 on the supported Linux architectures
        root_fd,
        os.fsencode(relative_path),
        ctypes.byref(how),
        ctypes.sizeof(how),
    )
    if descriptor >= 0:
        return int(descriptor)
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise AuditError(f"publication target already exists: {relative_path}")
    if error_number in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EPERM):
        raise AuditError(
            "root-anchored no-clobber publication is unsupported by this Linux filesystem/kernel: "
            f"{os.strerror(error_number)}"
        )
    if error_number in (errno.ELOOP, errno.EXDEV):
        raise AuditError(f"publication path escaped or crossed a symlink: {relative_path}")
    raise AuditError(
        f"unable to open publication path {relative_path}: {os.strerror(error_number)}"
    )


def _probe_openat2_capability(root: Path = Path(tempfile.gettempdir())) -> None:
    root_fd, root_identity = _open_publication_root(root)
    probe_fd: int | None = None
    try:
        probe_fd = _openat2_beneath(
            root_fd,
            ".",
            flags=(
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
        )
        if not stat.S_ISDIR(os.fstat(probe_fd).st_mode):
            raise AuditError("openat2 capability probe did not bind a directory")
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("openat2 capability probe root identity changed")
    finally:
        _close_descriptors(probe_fd, root_fd)


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise AuditError("publication write made no progress")
        remaining = remaining[written:]


def _read_published_state(
    root_fd: int,
    relative_path: str,
    *,
    expected_identity: tuple[int, int],
) -> _PublicState:
    descriptor = _openat2_beneath(
        root_fd,
        relative_path,
        flags=(
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        ),
    )
    try:
        before = os.fstat(descriptor)
        content = _read_stable_descriptor(descriptor, label="published artifact")
        after = os.fstat(descriptor)
        if (
            _stat_identity(before) != expected_identity
            or _stat_identity(after) != expected_identity
        ):
            raise AuditError("published artifact identity changed during verification")
        if (
            not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o644
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise AuditError("published artifact metadata changed or mode is not exact 0644")
        return _PublicState(
            True,
            expected_identity,
            stat.S_IMODE(after.st_mode),
            len(content),
            hashlib.sha256(content).hexdigest(),
        )
    finally:
        os.close(descriptor)


def _publish_new_bytes(root: Path, target: Path, content: bytes) -> _PublicState:
    relative_path = _root_relative_path(root, target)
    root_fd, root_identity = _open_publication_root(root)
    descriptor: int | None = None
    try:
        descriptor = _openat2_beneath(
            root_fd,
            relative_path,
            flags=(
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            ),
            mode=0o600,
        )
        identity = _stat_identity(os.fstat(descriptor))
        try:
            _write_all(descriptor, content)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
        except OSError as exc:
            raise AuditError(
                "publication failed after the fresh target became visible; the partial name "
                f"is retained for guarded rejection: {exc}"
            ) from exc
        finally:
            descriptor_to_close = descriptor
            descriptor = None
            os.close(descriptor_to_close)
        if _stat_identity(os.fstat(root_fd)) != root_identity:
            raise AuditError("publication root descriptor identity changed")
        parent_relative = str(Path(relative_path).parent)
        parent_fd = _openat2_beneath(
            root_fd,
            parent_relative,
            flags=(os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)),
        )
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        published = _read_published_state(
            root_fd,
            relative_path,
            expected_identity=identity,
        )
        if published.content_sha256 != hashlib.sha256(content).hexdigest() or (
            published.size_bytes != len(content)
        ):
            raise AuditError("published artifact content verification failed")
        return published
    finally:
        _close_descriptors(descriptor, root_fd)


def _publish_new_text(root: Path, target: Path, content: str) -> _PublicState:
    return _publish_new_bytes(root, target, content.encode("utf-8"))


def _capture_public_state(target: Path, parent_fd: int) -> _PublicState:
    try:
        descriptor = os.open(
            target.name,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return _PublicState(False, None, None, None, None)
    except OSError as exc:
        raise AuditError(f"unable to open public artifact state {target}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuditError(f"public artifact target is not a regular file: {target}")
        content = _read_stable_descriptor(descriptor, label=f"public artifact {target}")
        after = os.fstat(descriptor)
        lexical_after = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(left, field) != getattr(right, field)
            for left, right in ((before, after), (after, lexical_after))
            for field in stable_fields
        ):
            raise AuditError("public artifact identity or metadata changed during state capture")
    finally:
        os.close(descriptor)
    return _PublicState(
        True,
        _stat_identity(after),
        stat.S_IMODE(after.st_mode),
        len(content),
        hashlib.sha256(content).hexdigest(),
    )


def _verify_isolated_publication(
    target: Path,
    published: _PublicState,
    *,
    repo_root: Path,
    temp_root: Path,
) -> None:
    if not published.exists or published.identity is None or published.mode != 0o644:
        raise AuditError("isolated output identity changed before completion")
    lexical = os.stat(target, follow_symlinks=False)
    if _stat_identity(lexical) != published.identity or stat.S_IMODE(lexical.st_mode) != 0o644:
        raise AuditError("isolated output lexical target identity changed before completion")
    resolved_target = target.resolve(strict=True)
    resolved_repo = repo_root.resolve()
    resolved_temp = temp_root.resolve()
    if resolved_target == resolved_repo or resolved_repo in resolved_target.parents:
        raise AuditError("isolated output moved inside the repository during publication")
    if resolved_temp not in resolved_target.parents:
        raise AuditError("isolated output moved outside the temporary root during publication")


def _capture_packet_target_states() -> dict[Path, _PublicState]:
    targets = (EVIDENCE_PATH, REPORT_PATH)
    require_safe_artifact_targets(ROOT, targets, AUTHORIZED_PHASE_A_PATHS)
    states: dict[Path, _PublicState] = {}
    for target in targets:
        with _rooted_parent_directory(ROOT, target) as parent_fd:
            states[target] = _capture_public_state(target, parent_fd)
    return states


@contextmanager
def _packet_publication_lock(repo: Path) -> Iterable[None]:
    _require_openat2_publication_support()
    assert fcntl is not None
    _require_safe_local_git_config(repo, label="Phase-A publication checkout")
    git_dir = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=repo)
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    git_fd, git_identity = _open_publication_directory(git_dir)
    locked = False
    try:
        try:
            fcntl.flock(git_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise AuditError(f"unable to acquire Phase-A publication lock: {exc}") from exc
            raise AuditError(
                "Phase-A publication lock is already held; refusing concurrent write"
            ) from exc
        if _stat_identity(os.fstat(git_fd)) != git_identity:
            raise AuditError("Git directory identity changed while acquiring packet lock")
        yield
    finally:
        primary_exception_active = sys.exc_info()[0] is not None
        unlock_error: OSError | None = None
        try:
            if locked:
                try:
                    fcntl.flock(git_fd, fcntl.LOCK_UN)
                except OSError as exc:
                    unlock_error = exc
        finally:
            _close_descriptors(git_fd)
        if unlock_error is not None and not primary_exception_active:
            raise AuditError(f"unable to release Phase-A publication lock: {unlock_error}")


def write_new_isolated_output(
    path: Path,
    content: str,
    *,
    repo_root: Path = ROOT,
    temp_root: Path = Path(tempfile.gettempdir()),
) -> Path:
    target = require_isolated_output(path, repo_root=repo_root, temp_root=temp_root)
    target = require_isolated_output(target, repo_root=repo_root, temp_root=temp_root)
    try:
        published = _publish_new_text(temp_root, target, content)
        _verify_isolated_publication(
            target,
            published,
            repo_root=repo_root,
            temp_root=temp_root,
        )
        return target
    except BaseException as exc:
        # Never delete or overwrite the public final name during recovery. A failed
        # direct no-clobber creation may leave a partial 0600/0644 name; the raised
        # error prevents acceptance and callers must preserve it and choose a fresh name.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, AuditError):
            raise
        if isinstance(exc, OSError):
            raise AuditError(f"unable to publish isolated evidence output: {exc}") from exc
        raise


def _write_phase_a_artifacts_locked(
    evidence: Mapping[str, Any],
    json_text: str,
    report_text: str,
    expected_states: Mapping[Path, _PublicState],
) -> None:
    payloads = {
        EVIDENCE_PATH: json_text,
        REPORT_PATH: report_text,
    }
    try:
        require_phase_a_packet_checkout()
        require_safe_artifact_targets(ROOT, list(payloads), AUTHORIZED_PHASE_A_PATHS)
        if set(expected_states) != set(payloads):
            raise AuditError("Phase-A publication snapshot is incomplete")
        if any(state.exists for state in expected_states.values()):
            raise AuditError(
                "Phase-A canonical artifact exists; preserve the old packet and use an "
                "absent-target fresh-name publication"
            )
        require_safe_artifact_targets(ROOT, list(payloads), AUTHORIZED_PHASE_A_PATHS)
        if _audit_implementation_refs() != evidence["audit_implementation"]:
            raise AuditError("Phase-A audit implementation changed during evidence construction")

        for target, content in payloads.items():
            _publish_new_text(ROOT, target, content)

        _compare(EVIDENCE_PATH, json_text)
        _compare(REPORT_PATH, report_text)
        require_phase_a_packet_checkout()
        require_safe_artifact_targets(ROOT, list(payloads), AUTHORIZED_PHASE_A_PATHS)
        if _audit_implementation_refs() != evidence["audit_implementation"]:
            raise AuditError("Phase-A audit implementation changed during artifact publication")
    except BaseException as exc:
        # Cross-file publication is not atomic. Never roll a public name back after
        # failure: a concurrent owner may have claimed it, and conditional unlink is
        # unavailable on the supported filesystem interface.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, AuditError):
            raise
        raise AuditError(
            "unable to publish Phase-A artifacts safely; no public path was overwritten "
            f"during recovery; an interrupted ordered pair must be rejected by the final guarded check: {exc}"
        ) from exc


def _parse_cli_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packet-preflight",
        action="store_true",
        help="enforce the one-shot Phase-A branch, ancestry and exact four-path boundary",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write canonical JSON and Markdown")
    mode.add_argument("--check", action="store_true", help="verify canonical JSON and Markdown")
    mode.add_argument(
        "--output",
        type=Path,
        help="write canonical JSON to a new path below the operating-system temporary directory",
    )
    mode.add_argument(
        "--create-validation-receipt",
        type=Path,
        help="execute every pre-publication validation child and write a receipt to a fresh temp path only if all exit zero",
    )
    parser.add_argument(
        "--validation-receipt",
        type=Path,
        help="explicit immutable validation receipt to use with --write",
    )
    parser.add_argument(
        "--review-receipt",
        type=Path,
        help="clean independent-review receipt to use with --write",
    )
    parser.add_argument(
        "--reviewed-evidence",
        type=Path,
        help="preserved reviewed pre-stamp JSON below the temporary root",
    )
    parser.add_argument(
        "--reviewed-report",
        type=Path,
        help="preserved reviewed pre-stamp Markdown below the temporary root",
    )
    args = parser.parse_args(argv)

    if (args.validation_receipt is not None or args.review_receipt is not None) and not args.write:
        parser.error("--validation-receipt/--review-receipt require --write")
    if args.write and args.validation_receipt is None:
        parser.error("--write requires an explicit --validation-receipt")
    reviewed_source_args = (args.reviewed_evidence, args.reviewed_report)
    if any(path is not None for path in reviewed_source_args):
        if not args.write or args.review_receipt is None or not all(reviewed_source_args):
            parser.error(
                "--reviewed-evidence/--reviewed-report require each other, --write, and "
                "--review-receipt"
            )
    if args.review_receipt is not None and not all(reviewed_source_args):
        parser.error("--review-receipt requires both --reviewed-evidence and --reviewed-report")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_cli_args(argv)
    _probe_openat2_capability()
    reviewed_source_args = (args.reviewed_evidence, args.reviewed_report)
    if args.packet_preflight:
        require_phase_a_packet_checkout()
    if args.create_validation_receipt is not None:
        require_phase_a_packet_checkout()
        require_isolated_output(args.create_validation_receipt)
        execution = _execute_validation_suite()
        receipt = create_validation_receipt(execution)
        receipt_text = canonical_json(receipt)
        require_phase_a_packet_checkout()
        _require_exact_json_value(
            _audit_implementation_refs(),
            receipt["tested_implementation_refs"],
            label="validation receipt publication implementation refs",
        )
        _require_exact_json_value(
            _execution_tool_refs(),
            receipt["tested_execution_tool_refs"],
            label="validation receipt publication executable refs",
        )
        _require_exact_json_value(
            _security_materialization_refs(),
            receipt["tested_security_materializations"],
            label="validation receipt publication security materializations",
        )
        _require_exact_json_value(
            _validation_checkout_ref(),
            receipt["tested_validation_checkout"],
            label="validation receipt publication checkout materialization",
        )
        _require_exact_json_value(
            _python_runtime_ref(),
            receipt["tested_python_runtime"],
            label="validation receipt publication Python runtime",
        )
        _require_exact_json_value(
            _parser_smoke_input_ref(),
            receipt["tested_parser_smoke_inputs"],
            label="validation receipt publication parser-smoke inputs",
        )
        write_new_isolated_output(args.create_validation_receipt, receipt_text)
        _require_exact_json_value(
            _audit_implementation_refs(),
            receipt["tested_implementation_refs"],
            label="validation receipt published implementation refs",
        )
        _require_exact_json_value(
            _execution_tool_refs(),
            receipt["tested_execution_tool_refs"],
            label="validation receipt published executable refs",
        )
        _require_exact_json_value(
            _security_materialization_refs(),
            receipt["tested_security_materializations"],
            label="validation receipt published security materializations",
        )
        _require_exact_json_value(
            _validation_checkout_ref(),
            receipt["tested_validation_checkout"],
            label="validation receipt published checkout materialization",
        )
        _require_exact_json_value(
            _python_runtime_ref(),
            receipt["tested_python_runtime"],
            label="validation receipt published Python runtime",
        )
        _require_exact_json_value(
            _parser_smoke_input_ref(),
            receipt["tested_parser_smoke_inputs"],
            label="validation receipt published parser-smoke inputs",
        )
        print(f"Issue #976 validation receipt: {args.create_validation_receipt}")
        return 0

    validation_receipt = None
    review_receipt = None
    evidence: dict[str, Any]
    if args.write:
        with _packet_publication_lock(ROOT):
            require_phase_a_packet_checkout()
            expected_states = _capture_packet_target_states()
            validation_receipt = (
                _read_json_mapping(args.validation_receipt, label="validation receipt")
                if args.validation_receipt is not None
                else None
            )
            review_receipt = (
                _read_json_mapping(args.review_receipt, label="review receipt")
                if args.review_receipt is not None
                else None
            )
            reviewed_packet_sources = None
            if all(reviewed_source_args):
                assert args.reviewed_evidence is not None
                assert args.reviewed_report is not None
                reviewed_packet_sources = {
                    str(EVIDENCE_PATH.relative_to(ROOT)): args.reviewed_evidence,
                    str(REPORT_PATH.relative_to(ROOT)): args.reviewed_report,
                }
            evidence = build_evidence(
                validation_receipt=validation_receipt,
                review_receipt=review_receipt,
                reviewed_packet_sources=reviewed_packet_sources,
                for_write=True,
            )
            json_text = canonical_json(evidence)
            report_text = render_report(evidence)
            _write_phase_a_artifacts_locked(
                evidence,
                json_text,
                report_text,
                expected_states,
            )
            if _audit_implementation_refs() != evidence["audit_implementation"]:
                raise AuditError("Phase-A audit implementation changed during command execution")
            assert validation_receipt is not None
            _require_exact_json_value(
                _security_materialization_refs(),
                validation_receipt["tested_security_materializations"],
                label="published packet security materializations",
            )
            _require_exact_json_value(
                _validation_checkout_ref(),
                validation_receipt["tested_validation_checkout"],
                label="published packet validation checkout",
            )
            _require_exact_json_value(
                _python_runtime_ref(),
                validation_receipt["tested_python_runtime"],
                label="published packet Python runtime",
            )
            _require_exact_json_value(
                _parser_smoke_input_ref(),
                validation_receipt["tested_parser_smoke_inputs"],
                label="published packet parser-smoke inputs",
            )
            require_phase_a_packet_checkout()
    else:
        if args.check:
            require_phase_a_packet_checkout()
        evidence = build_evidence()
        json_text = canonical_json(evidence)
        report_text = render_report(evidence)
        if args.output is not None:
            write_new_isolated_output(args.output, json_text)
        else:
            _compare(EVIDENCE_PATH, json_text)
            _compare(REPORT_PATH, report_text)
        if _audit_implementation_refs() != evidence["audit_implementation"]:
            raise AuditError("Phase-A audit implementation changed during command execution")
        if args.check or args.packet_preflight:
            require_phase_a_packet_checkout()
    print(
        f"Issue #976 Phase-A evidence: {len(evidence['scope']['rules'])} rules, "
        f"{len(evidence['scope']['paths'])} paths"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"build-delivery audit failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
