"""Pure and scenario-flow tests for the #1111 Windows package-identity discriminator.

The executable launch is replaced by a recorder here; the real one is exercised by
the opt-in Windows CI job. These tests prove the table/receipt formatting, scenario
isolation and the "record, do not judge" policy.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from types import SimpleNamespace

import pytest

from metroliza.shared.diagnostic_package import COMPONENTS, MANIFEST_NAME
from scripts import qualify_package_identity as discriminator
from scripts.build_diagnostic_manifest import write_supervision_manifest


@pytest.fixture
def onedir(tmp_path):
    root = tmp_path / "metroliza_P_test_onedir"
    for name in (*COMPONENTS, "metroliza.exe"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-" + name.encode())
    (root / COMPONENTS[-1]).write_text(json.dumps({"git_sha": "a" * 40}), encoding="utf-8")
    write_supervision_manifest(root)
    return root


def _context(onedir, tmp_path, **overrides):
    import metroliza.shared.diagnostic_package as package

    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    options = dict(run_smoke=lambda *_a: pytest.fail("executable launched"))
    options.update(overrides)
    return discriminator.Context(source=onedir, work=work, package=package, **options)


@pytest.mark.parametrize("tag,expected", [
    (None, "-"), (0, "-"),
    (0xA000000C, "symlink"), (0xA0000003, "mount_point"),
    (0x9000001A, "cloud"), (0x9000601A, "cloud"), (0x9000F01A, "cloud"),
    (0x80000013, "dedup"), (0x12345678, "other"),
])
def test_reparse_tag_names(tag, expected):
    assert discriminator.describe_reparse_tag(tag) == expected


@pytest.mark.parametrize("tag,surrogate", [
    (0xA000000C, True), (0xA0000003, True), (0x9000001A, False), (0x80000013, False), (0, False),
])
def test_name_surrogate_bit(tag, surrogate):
    assert discriminator.is_name_surrogate_tag(tag) is surrogate


def _fake_stat(mode, *, nlink=1, attributes=None, tag=None):
    values = dict(st_mode=mode, st_nlink=nlink, st_size=7)
    if attributes is not None:
        values["st_file_attributes"] = attributes
    if tag is not None:
        values["st_reparse_tag"] = tag
    return SimpleNamespace(**values)


def test_stat_facts_report_reparse_attribute_tag_and_links():
    plain = discriminator.stat_facts(_fake_stat(stat.S_IFREG | 0o644, attributes=0x20, tag=0))
    assert plain["reparse_point"] is False and plain["name_surrogate"] is False
    assert plain["reparse_tag_name"] == "-"
    cloud = discriminator.stat_facts(
        _fake_stat(stat.S_IFREG | 0o644, nlink=2, attributes=0x420, tag=0x9000601A))
    assert cloud["reparse_point"] is True and cloud["reparse_tag"] == "0x9000601a"
    assert cloud["reparse_tag_name"] == "cloud" and cloud["name_surrogate"] is False
    assert cloud["nlink"] == 2
    junction = discriminator.stat_facts(
        _fake_stat(stat.S_IFDIR | 0o755, attributes=0x410, tag=0xA0000003))
    assert junction["kind"] == "directory" and junction["name_surrogate"] is True
    posix = discriminator.stat_facts(_fake_stat(stat.S_IFLNK | 0o777))
    assert posix["kind"] == "symlink" and posix["reparse_point"] is None


def test_identity_summary_tolerates_pre_fix_objects_without_component():
    summary = discriminator.identity_summary(SimpleNamespace(valid=False, reason="package_unavailable"))
    assert summary == {"valid": False, "reason": "package_unavailable", "component": None,
                       "git_sha": None}


def _sample_results():
    return [
        discriminator.ScenarioResult(
            1, "baseline", "Untouched", identity={
                "valid": True, "reason": "verified", "component": None, "git_sha": "a" * 40},
            facts={"root": {"reparse_point": False, "kind": "directory", "nlink": 1},
                   "component": {"reparse_point": False, "kind": "file", "nlink": 1}}),
        discriminator.ScenarioResult(
            2, "modified_component", "Modified", identity={
                "valid": False, "reason": "component_modified", "component": "_internal/python311.dll",
                "git_sha": "a" * 40},
            facts={"root": {"reparse_point": True, "reparse_tag_name": "cloud",
                            "kind": "directory", "nlink": 1},
                   "component": {"reparse_point": False, "kind": "file", "nlink": 2}}),
        discriminator.ScenarioResult(
            3, "missing_component", "Missing", identity={
                "valid": False, "reason": "package_unavailable", "component": None, "git_sha": None},
            facts={"component": {"error": "FileNotFoundError", "winerror": 2}}),
        discriminator.ScenarioResult(
            6, "supervised_smoke", "Smoke", identity={
                "valid": True, "reason": "verified", "component": None, "git_sha": "a" * 40},
            exit_code=0),
        discriminator.ScenarioResult(
            5, "provenance_mismatch", "Mix", status="skipped", detail="example"),
        discriminator.ScenarioResult(
            4, "missing_manifest", "Manifest", status="unsupported", detail="example reason"),
    ]


def test_table_lists_every_scenario_with_fixed_cells():
    table = discriminator.format_table(_sample_results())
    lines = table.splitlines()
    assert lines[0].split()[:3] == ["#", "scenario", "status"]
    assert len(lines) == 2 + 6
    by_key = {line.split()[1]: line for line in lines[2:]}
    assert "yes" in by_key["baseline"] and "verified" in by_key["baseline"]
    assert "NO" in by_key["modified_component"]
    assert "_internal/python311.dll" in by_key["modified_component"]
    assert "reparse:cloud" in by_key["modified_component"] and "nlink=2" in by_key["modified_component"]
    assert "err:FileNotFoundError" in by_key["missing_component"]
    assert by_key["supervised_smoke"].rstrip().endswith("0")
    assert "skipped: example" in by_key["provenance_mismatch"]
    assert "unsupported: example reason" in by_key["missing_manifest"]


def test_receipt_is_plain_json_and_records_without_judging():
    receipt = discriminator.build_receipt(_sample_results(), metadata={"onedir_name": "x"})
    decoded = json.loads(json.dumps(receipt))
    assert decoded["schema_version"] == 1 and decoded["issue"] == 1111
    assert decoded["baseline_valid"] is True
    assert [item["key"] for item in decoded["scenarios"]][:2] == ["baseline", "modified_component"]
    assert decoded["scenarios"][4]["status"] == "skipped"
    assert decoded["scenarios"][3]["exit_code"] == 0
    assert "judging" in decoded and decoded["onedir_name"] == "x"


def test_receipt_baseline_invalid_when_baseline_missing_or_rejected():
    assert discriminator.build_receipt([], metadata={})["baseline_valid"] is False
    rejected = discriminator.ScenarioResult(
        1, "baseline", "b", identity={"valid": False, "reason": "x", "component": None, "git_sha": None})
    assert discriminator.build_receipt([rejected], metadata={})["baseline_valid"] is False


def test_scenarios_run_on_isolated_copies_and_record_without_launching(onedir, tmp_path):
    context = _context(onedir, tmp_path, skip_smoke=True)
    before = {path: path.read_bytes() for path in onedir.rglob("*") if path.is_file()}
    results = discriminator.run_scenarios(context)
    by_key = {item.key: item for item in results}
    assert [item.number for item in results] == list(range(1, 7))
    assert by_key["baseline"].identity["valid"] is True
    for key in ("modified_component", "missing_component", "missing_manifest",
                "provenance_mismatch"):
        assert by_key[key].status == "recorded" and by_key[key].identity["valid"] is False, key
    assert by_key["supervised_smoke"].status == "skipped"
    assert by_key["supervised_smoke"].detail == "--skip-smoke"
    # The source onedir is never modified, and every scenario copy is removed.
    assert before == {path: path.read_bytes() for path in onedir.rglob("*") if path.is_file()}
    assert list(context.work.iterdir()) == []


def test_provenance_scenario_is_a_self_consistent_two_version_mix(onedir, tmp_path, monkeypatch):
    """Hashes in the mixed copy all match, so only the SHA equality can reject it."""
    from metroliza.shared.diagnostic_package import component_hash

    context = _context(onedir, tmp_path)
    kept = []
    original_finish = discriminator._finish

    def keep(result, ctx, root, component):
        kept.append(root)
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert all(component_hash(root, name) == manifest["components"][name] for name in COMPONENTS)
        provenance = json.loads((root / COMPONENTS[-1]).read_text(encoding="utf-8"))
        assert provenance["git_sha"] == "f" * 40 and manifest["git_sha"] == "a" * 40
        return original_finish(result, ctx, root, component)

    monkeypatch.setattr(discriminator, "_finish", keep)
    result, = discriminator.run_scenarios(context, selected={"provenance_mismatch"})
    assert kept and result.identity["valid"] is False
    assert result.extras["manifest_git_sha"] == "a" * 40
    assert result.extras["provenance_git_sha"] == "f" * 40
    # The unmodified source still verifies.
    assert discriminator.load_package_module().inspect_package(onedir).valid


def test_modified_missing_and_manifest_scenarios_damage_exactly_one_thing(onedir, tmp_path):
    context = _context(onedir, tmp_path)
    results = {item.key: item for item in discriminator.run_scenarios(
        context, selected={"modified_component", "missing_component", "missing_manifest"})}
    assert results["modified_component"].extras["component_name"] == "_internal/python311.dll"
    assert results["missing_component"].facts["component"]["error"] == "FileNotFoundError"
    assert results["missing_manifest"].facts["component"]["error"] == "FileNotFoundError"
    assert results["modified_component"].facts["component"]["size"] == len(
        (onedir / "_internal/python311.dll").read_bytes()) + 1


def test_smoke_runs_once_from_a_full_copy_and_records_the_exit_code(onedir, tmp_path):
    (onedir / "_internal" / "unrelated.bin").write_bytes(b"x")
    launched = []

    def smoke(executable, work, timeout):
        launched.append((executable.name, (executable.parent / "_internal/unrelated.bin").is_file(),
                         timeout))
        return {"exit_code": 0, "timed_out": False, "qualification_complete": True,
                "elapsed_seconds": 0.5}

    context = _context(onedir, tmp_path, run_smoke=smoke, smoke_timeout=33)
    result, = discriminator.run_scenarios(context, selected={"supervised_smoke"})
    assert launched == [("metroliza.exe", True, 33)]
    assert result.exit_code == 0 and result.extras["smoke"]["qualification_complete"] is True
    assert result.identity["valid"] is True


def test_unexpected_scenario_error_is_recorded_and_next_scenarios_still_run(onedir, tmp_path):
    def broken(*_args):
        raise OSError("smoke exploded")

    context = _context(onedir, tmp_path, run_smoke=broken)
    results = discriminator.run_scenarios(
        context, selected={"baseline", "supervised_smoke", "modified_component"})
    assert [(item.key, item.status) for item in results] == [
        ("baseline", "recorded"), ("modified_component", "recorded"), ("supervised_smoke", "error"),
    ]
    assert "smoke exploded" in results[2].detail


def test_clone_default_copies_only_identity_files_and_full_copies_everything(onedir, tmp_path):
    (onedir / "_internal" / "unrelated.bin").write_bytes(b"x")
    context = _context(onedir, tmp_path)
    light = context.clone(tmp_path / "light")
    assert not (light / "_internal" / "unrelated.bin").exists()
    assert (light / MANIFEST_NAME).is_file() and (light / "metroliza.exe").is_file()
    full = context.clone(tmp_path / "full", full=True)
    assert (full / "_internal" / "unrelated.bin").is_file()
    assert not os.path.samefile(full / "metroliza.exe", onedir / "metroliza.exe")


def test_main_requires_windows(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert discriminator.main([str(tmp_path), "--receipt", str(tmp_path / "r.json")]) == 2
    assert "Windows is required" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform != "win32", reason="reparse attributes exist only on Windows")
def test_real_lstat_facts_on_windows(tmp_path):
    target = tmp_path / "file.bin"
    target.write_bytes(b"x")
    facts = discriminator.path_facts(target)
    assert facts["kind"] == "file" and facts["reparse_point"] is False and facts["nlink"] == 1
