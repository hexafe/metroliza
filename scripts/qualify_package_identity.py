"""Windows discriminator for the package identity check (#1111).

The supervisor, the OCR worker launch and the portable envelope all call
``metroliza.shared.diagnostic_package.inspect_package`` on the built onedir.
This script copies that onedir into disposable scenarios (modified component,
missing component, missing manifest, a two-version mix) and *records* what
``inspect_package`` reports for each one, together with the ``os.lstat`` facts
of the root and the affected component. A last scenario runs the full
supervised startup smoke from an untouched full copy at its normal path.

It is a discriminator, not a judge: rejected scenarios do not fail the run.
Only an invalid baseline (the untouched copy) or unusable input does. Rejection
scenarios call ``inspect_package`` in-process and never launch the executable,
so no interactive MessageBox can block CI. The one executable launch runs in
the closed synthetic qualification mode that suppresses native notices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/pdf/cmm_smoke_fixture.pdf"
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
_NAME_SURROGATE_BIT = 0x20000000

STATUS_RECORDED = "recorded"
STATUS_SKIPPED = "skipped"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
PROVENANCE = "_internal/metroliza/app/build_provenance.json"
MIXED_GIT_SHA = "f" * 40

APPLICATION = "metroliza_application.exe"
LAUNCHER = "metroliza.exe"
OCR_WORKER = "metroliza_ocr_worker.exe"
PYTHON_DLL = "_internal/python311.dll"


class Unsupported(Exception):
    """A scenario cannot be built on this machine; the reason is recorded."""


class Skipped(Exception):
    """A scenario was not attempted; the reason is recorded."""


# --------------------------------------------------------------------------
# Pure helpers (runnable on any OS)
# --------------------------------------------------------------------------

def describe_reparse_tag(tag: int | None) -> str:
    """Human label for a reparse tag, or ``-`` when there is none."""
    if not tag:
        return "-"
    if tag == IO_REPARSE_TAG_SYMLINK:
        return "symlink"
    if tag == IO_REPARSE_TAG_MOUNT_POINT:
        return "mount_point"
    if tag & 0xFFFF0FFF == 0x9000001A:
        return "cloud"
    names = {0x80000013: "dedup", 0x80000017: "wof", 0x8000001B: "appexeclink"}
    return names.get(tag, "other")


def is_name_surrogate_tag(tag: int | None) -> bool:
    return bool(tag) and bool(tag & _NAME_SURROGATE_BIT)


def stat_facts(info: os.stat_result) -> dict[str, Any]:
    """The ``os.lstat`` facts that decide whether a path looks like a link."""
    attributes = getattr(info, "st_file_attributes", None)
    tag = getattr(info, "st_reparse_tag", None)
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "file"
    else:
        kind = "other"
    reparse = None if attributes is None else bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    return {
        "kind": kind,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "file_attributes": None if attributes is None else f"0x{attributes:08x}",
        "reparse_point": reparse,
        "reparse_tag": None if tag is None else f"0x{tag:08x}",
        "reparse_tag_name": describe_reparse_tag(tag if reparse else None),
        "name_surrogate": bool(reparse) and is_name_surrogate_tag(tag),
    }


def path_facts(path: Path) -> dict[str, Any]:
    try:
        return stat_facts(os.lstat(path))
    except OSError as error:
        return {"error": type(error).__name__, "winerror": getattr(error, "winerror", None)}


def identity_summary(identity: object) -> dict[str, Any]:
    """Record only the stable fields; ``component`` exists after the #1111 fix."""
    return {
        "valid": bool(getattr(identity, "valid", False)),
        "reason": str(getattr(identity, "reason", "unknown")),
        "component": getattr(identity, "component", None),
        "git_sha": getattr(identity, "git_sha", None),
    }


@dataclass
class ScenarioResult:
    number: int
    key: str
    title: str
    status: str = STATUS_RECORDED
    detail: str = ""
    identity: dict[str, Any] | None = None
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "number": self.number, "key": self.key, "title": self.title,
            "status": self.status, "detail": self.detail, "identity": self.identity,
            "facts": self.facts, "exit_code": self.exit_code,
            "elapsed_seconds": self.elapsed_seconds, "extras": self.extras,
        }


def build_receipt(results: list[ScenarioResult], *, metadata: dict[str, Any]) -> dict[str, Any]:
    baseline = next((item for item in results if item.key == "baseline"), None)
    baseline_valid = bool(baseline and baseline.identity and baseline.identity["valid"])
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "qualify_package_identity",
        "issue": 1111,
        "judging": "none: scenarios are recorded, not accepted or rejected by this tool",
        **metadata,
        "baseline_valid": baseline_valid,
        "scenarios": [item.as_json() for item in results],
    }


def _cell(value: object) -> str:
    return "-" if value is None or value == "" else str(value)


def _link_cell(facts: dict[str, Any] | None) -> str:
    if not facts:
        return "-"
    if "error" in facts:
        return "err:" + str(facts["error"])
    if facts.get("reparse_point"):
        return f"reparse:{facts['reparse_tag_name']}"
    if facts.get("kind") == "symlink":
        return "symlink"
    nlink = facts.get("nlink")
    if facts.get("kind") == "file" and nlink not in (None, 1):
        return f"nlink={nlink}"
    return "plain"


def _status_cell(item: ScenarioResult) -> str:
    return item.status if not item.detail or item.status == STATUS_RECORDED else (
        f"{item.status}: {item.detail}"
    )


def format_table(results: list[ScenarioResult]) -> str:
    """Readable fixed-width table; every cell is a short fixed token."""
    header = ("#", "scenario", "status", "valid", "reason", "component",
              "root", "component facts", "exit")
    rows: list[tuple[str, ...]] = []
    for item in results:
        identity = item.identity or {}
        valid = identity.get("valid")
        rows.append((
            str(item.number), item.key, _status_cell(item),
            "-" if valid is None else ("yes" if valid else "NO"),
            _cell(identity.get("reason")), _cell(identity.get("component")),
            _link_cell(item.facts.get("root")),
            _link_cell(item.facts.get("component")),
            _cell(item.exit_code),
        ))
    widths = [max(len(row[column]) for row in [header, *rows]) for column in range(len(header))]
    lines = ["  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip()
             for row in [header, *rows]]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Scenario machinery
# --------------------------------------------------------------------------

def load_package_module() -> ModuleType:
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import importlib

    return importlib.import_module("metroliza.shared.diagnostic_package")


@dataclass
class Context:
    source: Path
    work: Path
    package: ModuleType
    full_copies: bool = False
    smoke_timeout: float = 240.0
    skip_smoke: bool = False
    run_smoke: Callable[..., dict[str, Any]] | None = None

    def identity_files(self) -> list[str]:
        names = [self.package.MANIFEST_NAME, LAUNCHER, APPLICATION, *self.package.COMPONENTS]
        return list(dict.fromkeys(names))

    def clone(self, destination: Path, *, full: bool = False) -> Path:
        """Fresh copy; regular files are copied, never linked to the source."""
        if full or self.full_copies:
            shutil.copytree(self.source, destination)
            return destination
        for name in self.identity_files():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.source / name, target)
        return destination

    def inspect(self, root: Path) -> dict[str, Any]:
        return identity_summary(self.package.inspect_package(root))


def _finish(result: ScenarioResult, ctx: Context, root: Path, component: Path) -> ScenarioResult:
    result.identity = ctx.inspect(root)
    result.facts["root"] = path_facts(root)
    result.facts["component"] = path_facts(component)
    return result


def scenario_baseline(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    root = ctx.clone(ctx.work / "pkg")
    return _finish(result, ctx, root, root / APPLICATION)


def scenario_modified_component(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    root = ctx.clone(ctx.work / "pkg")
    component = root / PYTHON_DLL
    with component.open("ab") as stream:
        stream.write(b"\x00")
    result.extras["component_name"] = PYTHON_DLL
    return _finish(result, ctx, root, component)


def scenario_missing_component(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    root = ctx.clone(ctx.work / "pkg")
    component = root / OCR_WORKER
    component.unlink()
    result.extras["component_name"] = OCR_WORKER
    return _finish(result, ctx, root, component)


def scenario_missing_manifest(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    root = ctx.clone(ctx.work / "pkg")
    manifest = root / ctx.package.MANIFEST_NAME
    manifest.unlink()
    result.extras["component_name"] = ctx.package.MANIFEST_NAME
    return _finish(result, ctx, root, manifest)


def scenario_provenance_mismatch(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    """Two-version mix: a provenance file of another build whose hash the manifest lists."""
    root = ctx.clone(ctx.work / "pkg")
    provenance = root / PROVENANCE
    value = json.loads(provenance.read_text(encoding="utf-8"))
    value["git_sha"] = MIXED_GIT_SHA
    provenance.write_text(json.dumps(value), encoding="utf-8")
    manifest = root / ctx.package.MANIFEST_NAME
    document = json.loads(manifest.read_text(encoding="utf-8"))
    # The mix is self-consistent on purpose: only the provenance SHA equality can reject it.
    document["components"][PROVENANCE] = hashlib.sha256(provenance.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")
    result.extras["component_name"] = PROVENANCE
    result.extras["manifest_git_sha"] = document["git_sha"]
    result.extras["provenance_git_sha"] = MIXED_GIT_SHA
    return _finish(result, ctx, root, provenance)


def synthetic_environment(work: Path, state: Path, temp: Path, scenario: str) -> dict[str, str]:
    """Same closed environment as ``qualify_windows_portable_onefile._run``."""
    windows = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not windows:
        raise Unsupported("windows_root_unavailable")
    environment = {key: os.environ[key] for key in (
        "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    ) if os.environ.get(key)}
    environment.update({
        "PATH": str(Path(windows) / "System32") + ";" + windows,
        "TEMP": str(temp), "TMP": str(temp),
        "LOCALAPPDATA": str(state), "APPDATA": str(state / "Roaming"),
        "METROLIZA_STARTUP_SMOKE": "1",
        "METROLIZA_DIAGNOSTIC_QUALIFICATION": scenario,
        "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT": str(work),
        "METROLIZA_LICENSE_VERIFICATION": "0",
        "QT_QPA_PLATFORM": "offscreen",
    })
    return environment


def run_supervised_smoke(executable: Path, work: Path, timeout: float) -> dict[str, Any]:
    """Launch ``executable`` in the closed synthetic "normal" scenario and wait.

    The qualification mode suppresses native notices, so a rejected package ends
    with exit code 1 instead of an interactive MessageBox.
    """
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise Unsupported("public_fixture_mismatch")
    work.mkdir(parents=True)
    state, temp = work / "state", work / "temp"
    (state / "Roaming").mkdir(parents=True)
    temp.mkdir()
    scenario_root = work / "scenario"
    scenario_root.mkdir()
    shutil.copyfile(FIXTURE, scenario_root / "fixture.pdf")
    environment = synthetic_environment(scenario_root, state, temp, "normal")
    started = time.monotonic()
    process = subprocess.Popen(
        [str(executable)], cwd=scenario_root, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    timed_out = False
    try:
        exit_code: int | None = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, check=False, timeout=60,
        )
        process.wait(timeout=60)
    complete = False
    try:
        payload = json.loads((scenario_root / "qualification-complete.json").read_text(encoding="utf-8"))
        complete = payload.get("stage") == "complete" and payload.get("scenario") == "normal"
    except (OSError, ValueError):
        pass
    return {
        "exit_code": exit_code, "timed_out": timed_out, "qualification_complete": complete,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def scenario_supervised_smoke(ctx: Context, result: ScenarioResult) -> ScenarioResult:
    if ctx.skip_smoke:
        raise Skipped("--skip-smoke")
    smoke = ctx.run_smoke or run_supervised_smoke
    root = ctx.clone(ctx.work / "pkg", full=True)
    outcome = smoke(root / LAUNCHER, ctx.work / "run", ctx.smoke_timeout)
    result.extras["smoke"] = outcome
    result.exit_code = outcome["exit_code"]
    result.elapsed_seconds = outcome["elapsed_seconds"]
    return _finish(result, ctx, root, root / APPLICATION)


SCENARIOS: tuple[tuple[int, str, str, Callable[[Context, ScenarioResult], ScenarioResult]], ...] = (
    (1, "baseline", "Untouched copy of the built onedir", scenario_baseline),
    (2, "modified_component", "One component modified (one byte appended)",
     scenario_modified_component),
    (3, "missing_component", "One component missing (OCR worker)", scenario_missing_component),
    (4, "missing_manifest", "supervision_manifest.json missing", scenario_missing_manifest),
    (5, "provenance_mismatch", "Two-version mix: other build SHA in build_provenance.json",
     scenario_provenance_mismatch),
    (6, "supervised_smoke", "Supervised startup smoke from an untouched full copy",
     scenario_supervised_smoke),
)


def _remove_tree(path: Path) -> None:
    def retry(function: Callable[..., Any], target: str, _error: object) -> None:
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda f, p, e: retry(f, p, e))
    else:
        shutil.rmtree(path, onerror=lambda f, p, e: retry(f, p, e))


def run_scenarios(ctx: Context, *, keep: bool = False,
                  selected: set[str] | None = None) -> list[ScenarioResult]:
    """Run every scenario on its own directory; a scenario failure never aborts the rest."""
    results: list[ScenarioResult] = []
    for number, key, title, function in SCENARIOS:
        if selected is not None and key not in selected:
            continue
        result = ScenarioResult(number, key, title)
        scenario_context = replace(ctx, work=ctx.work / f"s{number:02d}-{key}")
        scenario_context.work.mkdir(parents=True)
        started = time.monotonic()
        try:
            result = function(scenario_context, result)
        except Skipped as reason:
            result.status, result.detail = STATUS_SKIPPED, str(reason)
        except Unsupported as reason:
            result.status, result.detail = STATUS_UNSUPPORTED, str(reason)
        except Exception as error:
            result.status, result.detail = STATUS_ERROR, f"{type(error).__name__}: {error}"
        finally:
            if result.elapsed_seconds is None:
                result.elapsed_seconds = round(time.monotonic() - started, 2)
            if not keep:
                _remove_tree(scenario_context.work)
        results.append(result)
    return results


def receipt_metadata(source: Path, package: ModuleType, *, full_copies: bool) -> dict[str, Any]:
    manifest_sha = None
    try:
        manifest_sha = json.loads((source / package.MANIFEST_NAME).read_text(encoding="utf-8")).get("git_sha")
    except (OSError, ValueError):
        pass
    return {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "manifest_git_sha": manifest_sha,
        "onedir_name": source.name,
        "copy_mode": "full" if full_copies else "identity_files_only",
        "identity_files": sorted(set([package.MANIFEST_NAME, LAUNCHER, APPLICATION, *package.COMPONENTS])),
        "package_identity_has_component_field": "component" in getattr(
            package.PackageIdentity, "__dataclass_fields__", {}
        ),
        "platform": {
            "system": platform.system(), "release": platform.release(),
            "version": platform.version(), "python": platform.python_version(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("onedir", type=Path, help="built onedir containing metroliza.exe")
    parser.add_argument("--receipt", required=True, type=Path, help="JSON receipt to write")
    parser.add_argument("--work-dir", type=Path, help="parent for disposable scenario copies")
    parser.add_argument("--full-copies", action="store_true",
                        help="copy the whole onedir for every scenario (default: identity files only)")
    parser.add_argument("--only", action="append", metavar="KEY", help="run only these scenario keys")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--smoke-timeout", type=float, default=240.0)
    parser.add_argument("--keep", action="store_true", help="keep scenario directories")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("qualify_package_identity: Windows is required (reparse attributes, packaged executable)", file=sys.stderr)
        return 2
    source = args.onedir.resolve()
    if not (source / LAUNCHER).is_file():
        print(f"qualify_package_identity: {LAUNCHER} not found in the given onedir", file=sys.stderr)
        return 2
    package = load_package_module()
    parent = args.work_dir.resolve() if args.work_dir else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    # resolve(): the final, long path form (CI temp paths use 8.3 names).
    private = Path(tempfile.mkdtemp(prefix="metroliza-identity-", dir=parent)).resolve()
    try:
        context = Context(
            source=source, work=private, package=package, full_copies=args.full_copies,
            smoke_timeout=args.smoke_timeout, skip_smoke=args.skip_smoke,
        )
        selected = set(args.only) if args.only else None
        if selected is not None:
            selected.add("baseline")
        results = run_scenarios(context, keep=args.keep, selected=selected)
        receipt = build_receipt(results, metadata=receipt_metadata(
            source, package, full_copies=args.full_copies))
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(format_table(results))
        print(f"\nreceipt: {args.receipt}")
    finally:
        if args.keep:
            print(f"scenario directories kept under: {private}")
        else:
            _remove_tree(private)
    return 0 if receipt["baseline_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
