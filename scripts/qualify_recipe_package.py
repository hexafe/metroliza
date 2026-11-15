"""Qualify real packaged recipe GUI journeys in an owned native Windows Job."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import sys
import time
import zipfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
CASES = ("main", "html", "larger")
TIMEOUT_SECONDS = 960
RECEIPT_KEYS = {"schema_version", "status", "reason", "packaged", "native_windows",
                "source_sha", "source_dirty", "qpa", "scale", "cases", "cleanup", "stage"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_receipt(payload: object, expected_sha: str, scale: float) -> None:
    if type(payload) is not dict or set(payload) != RECEIPT_KEYS:
        raise ValueError("receipt_schema")
    required = {"schema_version": 1, "status": "passed", "reason": "none", "packaged": True,
        "native_windows": True, "source_sha": expected_sha, "source_dirty": False,
        "qpa": "windows", "cleanup": "complete", "stage": "complete"}
    if any(type(payload[key]) is not type(value) or payload[key] != value for key, value in required.items()):
        raise ValueError("runtime_not_qualified")
    observed = payload["scale"]
    if type(observed) not in (int, float) or not math.isfinite(observed) or abs(observed - scale) > 0.02:
        raise ValueError("scale_mismatch")
    cases = payload["cases"]
    if type(cases) is not list or len(cases) != 3:
        raise ValueError("cases_missing")
    for case, record in zip(CASES, cases):
        _validate_case(case, record)


def _validate_case(case: str, record: object) -> None:
    if type(record) is not dict or set(record) != {"case", "state", "prompt_fields", "start_clicks"}:
        raise ValueError("case_schema")
    expected = 4 if case == "larger" else 2
    if record["case"] != case or record["state"] not in {"completed", "completed_with_warnings"}:
        raise ValueError("case_not_complete")
    if type(record["prompt_fields"]) is not int or record["prompt_fields"] != expected:
        raise ValueError("prompt_fields_mismatch")
    if type(record["start_clicks"]) is not int or record["start_clicks"] != 1:
        raise ValueError("one_start_required")


def verify_database(path: Path) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("database_integrity")
        if connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() != (5,):
            raise ValueError("report_count")
        values = connection.execute("SELECT meas FROM report_measurements").fetchall()
        if len(values) != 5 or any(not math.isfinite(row[0]) or abs(row[0] - 10.02) > 1e-9 for row in values):
            raise ValueError("literal_measurement_oracle")


def verify_workbook(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if archive.testzip() is not None or "xl/workbook.xml" not in names:
            raise ValueError("workbook_invalid")
        if not any(name.startswith("xl/charts/chart") for name in names):
            raise ValueError("workbook_charts_missing")


class _Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"script", "img", "link"}:
            return
        for key, value in attrs:
            if key in {"src", "href"} and value and not value.startswith("data:"):
                self.references.append(value)


def _verify_html_assets(path: Path, text: str) -> None:
    parsed = _Assets()
    parsed.feed(text)
    if not parsed.references or len(parsed.references) > 512:
        raise ValueError("html_assets_invalid")
    for reference in parsed.references:
        url = urlsplit(reference)
        target = path.parent / unquote(url.path)
        if url.scheme or url.netloc or target.is_symlink():
            raise ValueError("html_assets_invalid")
        if path.parent.resolve() not in target.resolve().parents:
            raise ValueError("html_assets_invalid")
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError("html_assets_invalid")


def verify_html(path: Path) -> None:
    if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("html_size")
    text = path.read_text(encoding="utf-8")
    if "<html" not in text.lower() or "plotly" not in text.lower():
        raise ValueError("html_invalid")
    _verify_html_assets(path, text)


def verify_png(path: Path) -> None:
    from PIL import Image
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError("screenshot_invalid")
        image.verify()
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("screenshot_invalid")
    if any(size < 200 or size > 10000 for size in struct.unpack(">II", header[16:24])):
        raise ValueError("screenshot_geometry")


def verify_artifacts(root: Path) -> list[str]:
    retained = []
    for case in CASES:
        verify_database(root / (case + ".db"))
        retained.append(case + ".db")
        if case != "html":
            verify_workbook(root / (case + ".xlsx"))
            retained.append(case + ".xlsx")
        if case != "main":
            verify_html(root / (case + ".html"))
            retained.append(case + ".html")
        for stage in ("form", "result"):
            name = case + "-" + stage + ".png"
            verify_png(root / name)
            retained.append(name)
    if (root / "html.xlsx").exists():
        raise ValueError("html_flow_created_workbook")
    return retained


def _environment(output: Path, scale: float) -> dict[str, str]:
    from scripts.measure_windows_startup_routes import build_environment
    state, temp = output / "state", output / "extract"
    (state / "Roaming").mkdir(parents=True)
    temp.mkdir()
    environment = build_environment(state, temp, output / "startup.jsonl", offscreen=False)
    environment.pop("METROLIZA_STARTUP_UI_SMOKE", None)
    environment.update(METROLIZA_RECIPE_QUALIFICATION_ROOT=str(output / "runtime"),
        QT_SCALE_FACTOR=str(scale), XDG_CONFIG_HOME=str(state / "config"),
        XDG_DATA_HOME=str(state / "data"), XDG_CACHE_HOME=str(state / "cache"))
    return environment


def _launch(exe: Path, output: Path, environment: dict[str, str]) -> None:
    from scripts.qualify_windows_diagnostics import _WindowsApi
    process = _WindowsApi().launch(exe, environment, output)
    try:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None and process.active_processes() == 0:
                if process.poll() != 0:
                    raise ValueError("application_failed")
                return
            time.sleep(0.1)
        raise ValueError("owned_job_timeout")
    finally:
        # Existing helper terminates/drains this exact Job and closes its native handles.
        process.close(terminate=True)


def qualify(exe: Path, output: Path, expected_sha: str, scale: float) -> dict:
    if sys.platform != "win32":
        raise ValueError("native_windows_required")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("source_sha_required")
    if scale not in (1.0, 1.25, 1.5) or not exe.is_file() or exe.is_symlink():
        raise ValueError("qualification_input_invalid")
    output.mkdir(parents=True, exist_ok=False)
    (output / "runtime").mkdir()
    before = sha256(exe)
    _launch(exe, output, _environment(output, scale))
    receipt_path = output / "runtime" / "recipe-qualification.json"
    if receipt_path.stat().st_size > 16384:
        raise ValueError("receipt_size")
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    validate_receipt(payload, expected_sha, scale)
    artifacts = verify_artifacts(output / "runtime")
    if sha256(exe) != before:
        raise ValueError("executable_changed")
    if any(path.name.startswith("_MEI") for path in (output / "extract").iterdir()):
        raise ValueError("extraction_remained")
    return {"schema_version": 1, "status": "passed", "source_sha": expected_sha,
        "exe_sha256": before, "native_windows": True, "scale": scale,
        "artifacts": ["runtime/" + name for name in artifacts], "cleanup": "complete",
        "scope": "synthetic_recipe_gui_journeys_build_host"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--scale", type=float, choices=(1.0, 1.25, 1.5), required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output directory must be new")
    try:
        result = qualify(args.exe.absolute(), args.output.resolve(), args.expected_sha, args.scale)
    except Exception as error:
        # No exception text, raw runtime output, paths, or arbitrary child data is published.
        allowed = {"native_windows_required", "source_sha_required", "qualification_input_invalid",
            "receipt_size", "receipt_schema", "runtime_not_qualified", "scale_mismatch",
            "cases_missing", "case_schema", "case_not_complete", "prompt_fields_mismatch",
            "one_start_required", "database_integrity", "report_count", "literal_measurement_oracle",
            "workbook_invalid", "workbook_charts_missing", "html_size", "html_invalid", "html_assets_invalid",
            "screenshot_invalid", "screenshot_geometry", "html_flow_created_workbook",
            "application_failed", "owned_job_timeout", "executable_changed", "extraction_remained"}
        reason = error.args[0] if error.args else None
        result = {"schema_version": 1, "status": "failed", "native_windows": sys.platform == "win32",
                  "reason": reason if type(reason) is str and reason in allowed else "qualification_failed"}
        if not args.output.exists():
            args.output.mkdir(parents=True)
    with (args.output / "qualification.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, allow_nan=False)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
