from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest
import yaml

from scripts import windows_fault_events as faults


SINCE = "2026-10-29T10:00:00Z"
START = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
PRIVATE = r"C:\Users\fixture_private_user\private-reports\fixture.dll"
# Synthetic values only. Named fields/order checked against Windows 11 and
# Server 2025 Application Error XML examples, not copied event contents:
# https://github.com/microsoft/microsoft-ui-xaml/issues/6482
# https://techcommunity.microsoft.com/discussions/windowsserver/windows-server-2025-application-crashing-events/4525503
XML = r'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="Application Error"/><EventID>1000</EventID><Version>0</Version>
<TimeCreated SystemTime="2026-10-29T10:00:03.9363862Z"/><EventRecordID>42</EventRecordID>
<Execution ProcessID="123" ThreadID="456"/><Channel>Application</Channel>
<Computer>fixture_private_user</Computer><Security UserID="S-1-5-21-123-456-789-1001"/></System>
<EventData>
<Data Name="AppName">metroliza_application.exe</Data>
<Data Name="AppVersion">1.2.3.4</Data><Data Name="AppTimeStamp">12345678</Data>
<Data Name="ModuleName">Qt6Core.dll</Data><Data Name="ModuleVersion">6.10.0.0</Data>
<Data Name="ModuleTimeStamp">12345678</Data><Data Name="ExceptionCode">c0000005</Data>
<Data Name="FaultingOffset">000000000024177E</Data><Data Name="ProcessId">0x123</Data>
<Data Name="ProcessCreationTime">0x123456789</Data>
<Data Name="AppPath">C:\Users\fixture_private_user\metroliza_application.exe</Data>
<Data Name="ModulePath">C:\Users\fixture_private_user\private-reports\fixture.dll</Data>
<Data Name="IntegratorReportId">fixture_private_report_id</Data>
<Data Name="PackageFullName"/><Data Name="PackageRelativeAppId"/>
</EventData></Event>'''


def event(*, seconds=3, fields=None, event_id="1000", provider="Application Error", reverse=False):
    root = ET.fromstring(XML)
    root.find(f"{faults.NS}System/{faults.NS}TimeCreated").set(
        "SystemTime", f"2026-10-29T10:00:{seconds:02d}.9363862Z"
    )
    root.find(f"{faults.NS}System/{faults.NS}EventID").text = event_id
    root.find(f"{faults.NS}System/{faults.NS}Provider").set("Name", provider)
    for node in root.findall(f"{faults.NS}EventData/{faults.NS}Data"):
        if node.get("Name") in (fields or {}):
            node.text = fields[node.get("Name")]
    data = root.find(f"{faults.NS}EventData")
    if reverse:
        data[:] = list(reversed(data[:]))
    return ET.tostring(root, encoding="unicode")


def reduce(xml):
    return faults.reduce_events(xml.encode("utf-8"), START)


def test_named_windows_fields_and_public_privacy():
    receipt = reduce(XML)
    assert receipt == {
        "schema_version": 1, "status": "available", "truncated": False,
        "events": [{"app": "metroliza_application.exe", "module": "Qt6Core.dll",
                    "module_version": "6.10.0.0", "exception_code": "0xc0000005",
                    "fault_offset": "0x000000000024177e", "seconds_after_since": 3}],
    }
    assert faults.validate_receipt(receipt)
    encoded = json.dumps(receipt)
    for private in (PRIVATE, "fixture_private_user", "fixture_private_report_id", "S-1-5-21", "AppPath"):
        assert private not in encoded
    assert reduce(event(reverse=True)) == receipt


@pytest.mark.parametrize("app", sorted(faults.allowed_apps()))
def test_exact_packaged_basenames(app):
    assert reduce(event(fields={"AppName": app.upper()}))["events"][0]["app"] == app


def test_allowlist_tracks_spec_names_and_version_metadata():
    root = Path(__file__).resolve().parents[1]
    onedir = (root / "packaging/metroliza_onedir.spec").read_text()
    for stem in ("metroliza", "metroliza_application", "metroliza_ocr_worker", "metroliza_compute_worker"):
        assert f'"{stem}"' in onedir
        assert stem + ".exe" in faults.allowed_apps()
    assert 'OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"' in (root / "packaging/metroliza_onefile.spec").read_text()
    assert 'OUTPUT_NAME = f"metroliza_{match[1]}_{match[2]}"' in (root / "packaging/metroliza_portable_onefile.spec").read_text()


@pytest.mark.parametrize("app", ["foreign.exe", PRIVATE, "../metroliza.exe", "metroliza_evil.exe", "metroliza.exe\n", "metroliza_compute_worKer.exe"])
def test_foreign_or_path_application_dropped(app):
    assert reduce(event(fields={"AppName": app}))["events"] == []


@pytest.mark.parametrize("fields, expected", [
    ({"ModuleName": PRIVATE}, {"module": "other"}),
    ({"ModuleName": "x" * 65 + ".dll"}, {"module": "other"}),
    ({"ModuleName": "user name.dll"}, {"module": "other"}),
    ({"ModuleName": "evil.dll\n"}, {"module": "other"}),
    ({"ModuleName": "ſecret.dll"}, {"module": "other"}),
    ({"ModuleVersion": PRIVATE}, {"module_version": "unavailable"}),
    ({"ModuleVersion": "123456.1"}, {"module_version": "unavailable"}),
    ({"ModuleVersion": "1.2.3.4.5"}, {"module_version": "unavailable"}),
    ({"ExceptionCode": "not-hex", "FaultingOffset": PRIVATE},
     {"exception_code": "unavailable", "fault_offset": "unavailable"}),
    ({"ExceptionCode": "1" * 17, "FaultingOffset": "-1"},
     {"exception_code": "unavailable", "fault_offset": "unavailable"}),
    ({"ExceptionCode": "0XC0000005", "FaultingOffset": "0xABC"},
     {"exception_code": "0xc0000005", "fault_offset": "0xabc"}),
    ({"ModuleName": "x" * 64 + ".PYD", "ModuleVersion": "99999.0.1.2"},
     {"module": "x" * 64 + ".PYD", "module_version": "99999.0.1.2"}),
])
def test_hostile_and_boundary_fields(fields, expected):
    receipt = reduce(event(fields=fields))
    assert faults.validate_receipt(receipt)
    assert receipt["events"][0].items() >= expected.items()
    assert "fixture_private_user" not in json.dumps(receipt)


def test_newest_eight_and_query_cap_are_explicit():
    receipt = reduce("".join(event(seconds=i) for i in range(10)))
    assert [item["seconds_after_since"] for item in receipt["events"]] == list(range(9, 1, -1))
    assert receipt["truncated"] is True
    assert reduce("".join(event() for _ in range(8)))["truncated"] is False
    assert reduce(event(fields={"AppName": "foreign.exe"}) * 64)["truncated"] is True


def test_scope_filters_and_pre_since_events():
    assert reduce(event(event_id="1001") + event(provider="foreign"))["events"] == []
    assert reduce(XML.replace("10:00:03", "09:59:59"))["events"] == []
    assert reduce(XML.replace("2026-10-29T10:00:03.9363862Z", "bad-time"))["events"] == []
    assert reduce(XML.replace('<Data Name="AppName">', '<Data Name="AppName">foreign.exe</Data><Data Name="AppName">'))["events"] == []


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-le"])
def test_byte_encodings_fragments_and_xml_document(encoding):
    for xml in (event() + event(), '<?xml version="1.0"?><Events>' + event() + "</Events>"):
        expected = 2 if "<Events>" not in xml else 1
        assert len(faults.reduce_events(xml.encode(encoding), START)["events"]) == expected


def test_non_utf8_byte_in_foreign_event_keeps_allowlisted_evidence():
    raw = event().encode("utf-8") + b'<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><EventID>1000</EventID></System><EventData><Data Name="AppName">caf\xe9.exe</Data></EventData></Event>'
    reduced = faults.reduce_events(raw, START)
    assert reduced["status"] == "available"
    assert len(reduced["events"]) == 1
    assert faults.reduce_events(b"\xff", START) == {
        "schema_version": 1, "status": "available", "events": [], "truncated": False}


@pytest.mark.parametrize("raw, reason", [
    (b"broken <", "invalid_xml"),
    (b'<!DOCTYPE x [<!ENTITY x "private">]><x>&x;</x>', "invalid_xml"),
    (b"x" * (faults.MAX_XML_BYTES + 1), "query_too_large"),
])
def test_bad_or_oversized_xml_is_unavailable(raw, reason):
    assert faults.reduce_events(raw, START) == faults._unavailable(reason)


def test_query_argv_timeout_and_closed_output(monkeypatch):
    def run(argv, **kwargs):
        assert argv == ["wevtutil", "qe", "Application",
                        "/q:*[System[(EventID=1000) and TimeCreated[@SystemTime>='2026-10-29T10:00:00Z']]]",
                        "/f:xml", "/rd:true", "/c:64"]
        assert kwargs == {"capture_output": True, "timeout": faults.QUERY_TIMEOUT, "check": False}
        return subprocess.CompletedProcess(argv, 0, XML.encode(), PRIVATE.encode())
    monkeypatch.setattr(faults.subprocess, "run", run)
    assert faults.collect(SINCE) == reduce(XML)


@pytest.mark.parametrize("failure, reason", [
    (OSError(PRIVATE), "query_failed"),
    (subprocess.TimeoutExpired("wevtutil", 10, output=PRIVATE.encode()), "query_timeout"),
    (RuntimeError(PRIVATE), "collector_error"),
    (None, "query_failed"),
])
def test_query_failures_never_raise_or_retain_messages(monkeypatch, tmp_path, failure, reason):
    def run(*args, **kwargs):
        if failure is not None:
            raise failure
        return subprocess.CompletedProcess([], 1, PRIVATE.encode(), PRIVATE.encode())
    monkeypatch.setattr(faults.subprocess, "run", run)
    output = tmp_path / "fault-events.json"
    assert faults.main(["--since", SINCE, "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == faults._unavailable(reason)


def test_invalid_since_does_not_query(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("must not query for invalid since")
    monkeypatch.setattr(faults.subprocess, "run", forbidden)
    for since in ("bad", "2026-10-29T10:00:00", "2026-10-29T10:00:00+01:00", SINCE + "' or true()"):
        assert faults.collect(since) == faults._unavailable("invalid_since")


@pytest.mark.parametrize("change", [
    {"app": "foreign.exe"}, {"module": PRIVATE}, {"module_version": PRIVATE},
    {"fault_offset": "0xGG"}, {"exception_code": "0xABC"}, {"user": "fixture_private_user"},
    {"seconds_after_since": True}, {"seconds_after_since": -1},
])
def test_writer_refuses_invalid_fields(tmp_path, change):
    receipt = reduce(XML)
    receipt["events"][0].update(change)
    output = tmp_path / "fault-events.json"
    assert not faults.validate_receipt(receipt)
    assert not faults.write_receipt(output, receipt)
    assert not output.exists()


def test_envelope_validator_and_write_failures(tmp_path, monkeypatch):
    good = reduce(event(seconds=4) + event(seconds=3))
    invalid = [None, {}, {**good, "schema_version": True}, {**good, "extra": PRIVATE},
               {**good, "truncated": 1}, {**good, "events": good["events"] * 5},
               {**good, "events": list(reversed(good["events"]))},
               faults._unavailable(PRIVATE)]
    assert all(not faults.validate_receipt(value) for value in invalid)
    receipt = copy.deepcopy(good)
    output = tmp_path / "fault-events.json"
    assert faults.write_receipt(output, receipt)
    assert json.loads(output.read_text()) == good
    assert not faults.write_receipt(tmp_path, receipt)
    monkeypatch.setattr(faults, "collect", lambda since: (_ for _ in ()).throw(RuntimeError(PRIVATE)))
    assert faults.main(["--since", SINCE, "--output", str(output)]) == 0


def test_fault_event_workflow_step_is_advisory_always_and_before_upload():
    workflow = yaml.load(Path(".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["windows-candidate-acceptance"]["steps"]
    index = next(i for i, step in enumerate(steps) if "scripts/windows_fault_events.py" in step.get("run", ""))
    step = steps[index]
    assert step["if"] == "always()"
    assert step["shell"] == "pwsh"
    assert step.get("continue-on-error") == "true" or step["run"].rstrip().endswith("exit 0")
    assert r".\.venv-build\Scripts\python.exe scripts/windows_fault_events.py" in step["run"]
    assert "--since $env:CANDIDATE_JOB_START_UTC" in step["run"]
    assert "Join-Path $env:CANDIDATE_RECEIPTS 'fault-events/fault-events.json'" in step["run"]
    start = next(i for i, value in enumerate(steps) if "CANDIDATE_JOB_START_UTC=" in value.get("run", ""))
    assert start < next(i for i, value in enumerate(steps) if "build_windows_exe.ps1" in value.get("run", ""))
    assert "GITHUB_ENV" in steps[start]["run"] and "UtcNow" in steps[start]["run"]
    core = [i for i, value in enumerate(steps) if "scripts/qualify_windows_candidate_core.py" in value.get("run", "")]
    upload = next(i for i, value in enumerate(steps) if value["name"] == "Retain bounded synthetic candidate receipts")
    assert max(core) < index < upload
    assert any(path.endswith("/**/*.json") for path in steps[upload]["with"]["path"].splitlines())
