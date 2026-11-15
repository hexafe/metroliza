"""Independent fixture, negative receipt, literal oracle and owned-exit controls."""
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from metroliza.app.recipe_qualification import GATE, install_recipe_qualification, write_reports
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.report_ports import ReportsRecipeService
from metroliza.recipes.ports import StepContext
from scripts import qualify_recipe_package as driver


def receipt():
    return {"schema_version": 1, "status": "passed", "reason": "none", "packaged": True,
        "native_windows": True, "source_sha": "a" * 40, "source_dirty": False,
        "qpa": "windows", "scale": 1.25, "cleanup": "complete", "stage": "complete", "cases": [
            {"case": case, "state": "completed", "prompt_fields": 4 if case == "larger" else 2,
             "start_clicks": 1} for case in driver.CASES]}


def test_authored_fixture_preflight_is_complete_without_decision(tmp_path):
    source = tmp_path / "reports"
    write_reports(source)
    plan = resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(source), str(tmp_path / "main.xlsx")))
    context = StepContext(plan.flow_id, plan.run_id, "unused", lambda: False, lambda *_: None)
    service = ReportsRecipeService(lambda *_: None, lambda *_: None)
    result = service.preflight(plan, context)
    try:
        assert result.ready and not result.requires_decision
        assert len(result.review.rows) == 5
    finally:
        service.finish(plan)


@pytest.mark.parametrize("key,value", [("packaged", False), ("native_windows", False),
    ("source_dirty", True), ("source_sha", "b" * 40), ("scale", float("nan")),
    ("qpa", "offscreen"), ("schema_version", True), ("cleanup", "pending")])
def test_source_stale_offscreen_partial_and_wrong_scale_are_rejected(key, value):
    value_map = receipt()
    value_map[key] = value
    with pytest.raises(ValueError):
        driver.validate_receipt(value_map, "a" * 40, 1.25)


def test_receipt_has_no_extra_private_fields_and_requires_one_start():
    payload = receipt()
    driver.validate_receipt(payload, "a" * 40, 1.25)
    payload["private_path"] = "PRIVATE_SENTINEL"
    with pytest.raises(ValueError, match="receipt_schema"):
        driver.validate_receipt(payload, "a" * 40, 1.25)
    payload.pop("private_path")
    payload["cases"][0]["start_clicks"] = 2
    with pytest.raises(ValueError, match="one_start_required"):
        driver.validate_receipt(payload, "a" * 40, 1.25)


def test_literal_database_oracle_rejects_wrong_values_and_cardinality(tmp_path):
    database = tmp_path / "test.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript("CREATE TABLE parsed_reports(id INTEGER);"
                                 "CREATE TABLE report_measurements(meas REAL);")
        connection.executemany("INSERT INTO parsed_reports VALUES (?)", [(i,) for i in range(5)])
        connection.executemany("INSERT INTO report_measurements VALUES (?)", [(10.02,)] * 5)
        connection.commit()
    driver.verify_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE report_measurements SET meas=10.03 WHERE rowid=1")
        connection.commit()
    with pytest.raises(ValueError, match="literal_measurement_oracle"):
        driver.verify_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM parsed_reports WHERE rowid=1")
        connection.commit()
    with pytest.raises(ValueError, match="report_count"):
        driver.verify_database(database)


def test_unrequested_probe_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv(GATE, raising=False)
    with pytest.raises(ValueError, match="qualification_gate_required"):
        install_recipe_qualification(None, tmp_path)
    assert not tuple(tmp_path.iterdir())


def test_timeout_closes_only_the_owned_job(tmp_path, monkeypatch):
    from scripts import qualify_windows_diagnostics as ownership
    calls = []
    process = SimpleNamespace(poll=lambda: None, active_processes=lambda: 1,
                              close=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(ownership, "_WindowsApi", lambda: SimpleNamespace(launch=lambda *_: process))
    times = iter((0.0, 1000.0))
    monkeypatch.setattr(driver.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="owned_job_timeout"):
        driver._launch(tmp_path / "exact.exe", tmp_path, {})
    assert calls == [{"terminate": True}]


def test_linux_driver_never_labels_package_acceptance_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(driver.sys, "platform", "linux")
    output = tmp_path / "evidence"
    status = driver.main(["--exe", str(tmp_path / "unused.exe"), "--output", str(output),
                          "--expected-sha", "a" * 40, "--scale", "1"])
    assert status == 1
    result = json.loads((output / "qualification.json").read_text())
    assert result["status"] == "failed" and result["native_windows"] is False


def test_html_asset_oracle_rejects_missing_or_remote_dependencies(tmp_path):
    document = tmp_path / "dashboard.html"
    document.write_text('<html><script src="plotly.js"></script></html>')
    with pytest.raises(ValueError, match="html_assets_invalid"):
        driver.verify_html(document)
    (tmp_path / "plotly.js").write_text("synthetic offline plotly")
    driver.verify_html(document)
    document.write_text('<html><script src="https://example.invalid/plotly.js"></script></html>')
    with pytest.raises(ValueError, match="html_assets_invalid"):
        driver.verify_html(document)


def test_png_oracle_decodes_complete_screenshot_and_rejects_truncation(tmp_path):
    from PIL import Image
    path = tmp_path / "screenshot.png"
    Image.new("RGB", (640, 480), "white").save(path)
    driver.verify_png(path)
    path.write_bytes(path.read_bytes()[:30])
    with pytest.raises((OSError, ValueError, SyntaxError)):
        driver.verify_png(path)
