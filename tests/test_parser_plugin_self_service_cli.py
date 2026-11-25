from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from metroliza.parsing.declarative_parser_profiles import approved_profile_backups, rollback_profile
from metroliza.parsing.pdf_backend import require_pdf_backend


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_cli_module():
    script_path = REPO_ROOT / "scripts" / "parser_plugin_self_service.py"
    spec = importlib.util.spec_from_file_location("test_parser_plugin_self_service", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", ["validate", "install", "repair"])
@pytest.mark.parametrize("sample_paths", [(), ("first.pdf",), ("first.pdf", "second report.pdf")])
def test_sample_option_collects_explicit_paths_in_order(command, sample_paths):
    module = _load_cli_module()
    argv = [command, "profile.yaml"]
    for sample in sample_paths:
        argv.extend(("--sample", sample))

    assert module._sample_paths(module.build_parser().parse_args(argv)) == tuple(map(Path, sample_paths))


def _profile_yaml(*, version: str = "0.1.0", marker: str = "SUPPLIER TEMPLATE MARKER") -> str:
    return f"""
schema_version: 1
plugin:
  plugin_id: supplier_alpha
  display_name: Supplier Alpha
  version: {version}
  source_format: pdf
  supported_locales: ["*"]
  template_ids: ["alpha_template"]
  priority: 910
probe:
  required_markers:
    - "{marker}"
  reject_markers: []
  confidence: 91
extraction:
  report_fields:
    reference: "Reference:\\\\s*(?P<value>\\\\S+)"
    report_date: "Date:\\\\s*(?P<value>\\\\d{{4}}-\\\\d{{2}}-\\\\d{{2}})"
    sample_number: "Sample:\\\\s*(?P<value>\\\\S+)"
  blocks:
    - header: "MAIN FEATURE"
      pattern: "^DIM\\\\s+(?P<axis_code>\\\\w+)\\\\s+(?P<nominal>[-0-9.,]+)\\\\s+(?P<tol_plus>[-0-9.,]+)\\\\s+(?P<tol_minus>[-0-9.,]+)\\\\s+(?P<bonus>[-0-9.,]+|-)\\\\s+(?P<measured>[-0-9.,]+)\\\\s+(?P<deviation>[-0-9.,]+)\\\\s+(?P<out_of_tolerance>[-0-9.,]+)$"
normalization:
  decimal_separator: "."
"""


def _write_pdf_text(path: Path, text: str) -> None:
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()


def _write_fixture_workspace(tmp_path, *, version: str = "0.1.0", marker: str = "SUPPLIER TEMPLATE MARKER"):
    workspace = tmp_path / "workspace"
    samples = workspace / "samples"
    samples.mkdir(parents=True)
    profile = workspace / "profile.yaml"
    profile.write_text(_profile_yaml(version=version, marker=marker), encoding="utf-8")
    sample = samples / "sample_report_01.pdf"
    _write_pdf_text(
        sample,
        "\n".join(
            (
                "SUPPLIER TEMPLATE MARKER",
                "Reference: REF123",
                "Date: 2026-01-05",
                "Sample: 0001",
                "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
                "",
            )
        ),
    )
    expected = workspace / "expected_results.csv"
    expected.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )
    return workspace, profile, sample, expected


def test_init_writes_profile_template(tmp_path, capsys):
    module = _load_cli_module()
    output = tmp_path / "supplier_beta.yaml"

    result = module.main(
        [
            "init",
            "--plugin-id",
            "supplier_beta",
            "--display-name",
            "Supplier Beta",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr().out
    assert result == 0
    assert output.exists()
    assert "plugin_id: supplier_beta" in output.read_text(encoding="utf-8")
    assert "Wrote profile template" in captured


def test_handoff_and_integrity_commands_create_self_contained_package(tmp_path, capsys):
    module = _load_cli_module()
    output_dir = tmp_path / "handoff"

    result = module.main(
        [
            "handoff",
            "--plugin-id",
            "supplier_beta",
            "--display-name",
            "Supplier Beta",
            "--source-format",
            "csv",
            "--output-dir",
            str(output_dir),
        ]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "Handoff folder:" in output
    assert (output_dir / "NON_TECHNICAL_STEPS.md").exists()
    assert (output_dir / "handoff_manifest.json").exists()
    assert (output_dir / "contracts" / "07_privacy_redaction_checklist.md").exists()
    operator_steps = (output_dir / "NON_TECHNICAL_STEPS.md").read_text(encoding="utf-8")
    step_six = (output_dir / "prompts" / "06_fix_validation_failures.md").read_text(encoding="utf-8")
    assert "artifacts/profile_repair_prompt.md" in operator_steps
    assert "keep the raw validation report local" in operator_steps.lower()
    assert "artifacts/profile_repair_prompt.md" in step_six
    assert "without the raw validation report" in step_six.lower()

    integrity_result = module.main(["integrity", str(output_dir)])
    integrity_output = capsys.readouterr().out
    assert integrity_result == 0
    assert "[PASS] supplier_beta" in integrity_output

    alias_result = module.main(["check-handoff", str(output_dir)])
    alias_output = capsys.readouterr().out
    assert alias_result == 0
    assert "manifest_declarative_installation_path" in alias_output


def test_repair_command_writes_profile_only_prompt_on_validation_failure(tmp_path, capsys):
    module = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(
        tmp_path,
        marker="MISSING SUPPLIER MARKER",
    )
    repair_prompt = workspace / "artifacts" / "repair.md"

    result = module.main(
        [
            "repair",
            str(profile),
            "--expected-results",
            str(expected),
            "--workspace",
            str(workspace),
            "--output",
            str(repair_prompt),
        ]
    )
    output = capsys.readouterr().out

    assert result == 1
    assert "[FAIL] supplier_alpha" in output
    assert "Repair prompt:" in output
    prompt_text = repair_prompt.read_text(encoding="utf-8")
    assert "Return complete corrected `profile.yaml` only" in prompt_text
    assert "Do not return Python code" in prompt_text


def test_record_generation_attaches_only_declared_identifiers_and_input_hashes(tmp_path, capsys):
    cli = _load_cli_module()
    workspace = tmp_path / "workspace"
    assert cli.main(["handoff", "--plugin-id", "receipt_profile", "--output-dir", str(workspace)]) == 0
    expected = workspace / "expected_results.csv"
    input_hash = sha256(expected.read_bytes()).hexdigest()
    profile_hash = sha256((workspace / "profile.yaml").read_bytes()).hexdigest()
    args = ["record-generation", str(workspace), "--provider", "synthetic-provider", "--model", "model-test",
            "--model-version", "2026-11", "--input-sha256", input_hash.upper()]

    assert cli.main(args) == 0
    initial, = (workspace / "artifacts").glob("profile_generation-*.json")
    assert json.loads(initial.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "evidence": "operator_declared_external_authoring",
        "operation": "generate",
        "provider": "synthetic-provider",
        "model": "model-test",
        "model_version": "2026-11",
        "input_sha256": [input_hash],
        "profile_sha256": profile_hash,
    }
    first = initial.read_bytes()
    assert str(workspace).encode() not in first
    assert expected.name.encode() not in first
    assert cli.main([*args, "--operation", "repair", "--input-sha256", input_hash]) == 0
    followup, = set((workspace / "artifacts").glob("profile_generation-*.json")) - {initial}
    assert json.loads(followup.read_text(encoding="utf-8"))["operation"] == "repair"
    assert initial.read_bytes() == first

    capsys.readouterr()
    assert cli.main([*args, "--input-sha256", "PRIVATE_SAMPLE_VALUE"]) == 2
    assert "PRIVATE_SAMPLE_VALUE" not in capsys.readouterr().err
    assert len(list((workspace / "artifacts").glob("profile_generation-*.json"))) == 2


@pytest.mark.parametrize("entry", ["workspace", "profile.yaml", "artifacts"])
def test_record_generation_rejects_redirected_workspace_entries(tmp_path, capsys, entry):
    cli = _load_cli_module()
    workspace = tmp_path / "workspace"
    assert cli.main(["handoff", "--plugin-id", "receipt_profile", "--output-dir", str(workspace)]) == 0
    original = workspace if entry == "workspace" else workspace / entry
    outside = tmp_path / "outside"
    original.replace(outside)
    try:
        original.symlink_to(outside, target_is_directory=outside.is_dir())
    except OSError:
        pytest.skip("Creating symlinks requires host support")
    capsys.readouterr()
    assert cli.main(["record-generation", str(workspace), "--provider", "synthetic-provider", "--model", "model-test",
                     "--input-sha256", "a" * 64]) == 2
    assert "ordinary profile workspace" in capsys.readouterr().err
    assert not list(tmp_path.rglob("profile_generation-*.json"))


@pytest.mark.parametrize("entry_point", ["cli", "wizard_artifact"])
def test_profile_repair_artifact_contains_only_shareable_validation_evidence(tmp_path, capsys, entry_point):
    from metroliza.parsing.parser_profile_handoff import workspace_from_root, write_profile_repair_prompt

    workspace, profile, sample, expected = _write_fixture_workspace(tmp_path)
    renamed = sample.with_name("SYNTHETIC_PRIVATE_SAMPLE_950.pdf")
    sample.rename(renamed)
    content = expected.read_text(encoding="utf-8")
    content = content.replace(sample.name, renamed.name).replace("REF123", "SYNTHETIC_PRIVATE_REF_950")
    expected.write_text(content.replace("10.02", "1234.567"), encoding="utf-8")
    snippets = workspace / "reference" / "contract_snippets.md"
    snippets.parent.mkdir()
    snippets.write_text("SYNTHETIC_PRIVATE_WORKSPACE_SNIPPET_950", encoding="utf-8")

    if entry_point == "cli":
        output = workspace / "artifacts" / "repair.md"
        cli = _load_cli_module()
        assert cli.main(["repair", str(profile), "--workspace", str(workspace),
                         "--expected-results", str(expected), "--output", str(output)]) == 1
        private_validation = capsys.readouterr().out
    else:
        output = write_profile_repair_prompt(workspace_from_root(workspace))
        private_validation = (workspace / "artifacts" / "profile_validation.txt").read_text(encoding="utf-8")

    assert "SYNTHETIC_PRIVATE_REF_950" in private_validation
    assert "1234.567" in private_validation
    shared = output.read_text(encoding="utf-8")
    for private in (str(tmp_path), renamed.name, "supplier_alpha", "SYNTHETIC_PRIVATE_REF_950", "REF123",
                    "1234.567", "MAIN FEATURE", "SYNTHETIC_PRIVATE_WORKSPACE_SNIPPET_950"):
        assert private not in shared
    assert "expected_results_report_reference_matches" in shared
    assert "expected_results_row_2_measured_matches" in shared
    assert "ParseResultV2" in shared and "Metroliza owns persistence" in shared
    assert "sample_file,reference,report_date,sample_number,block_index,header_normalized" in shared
    assert "tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance" in shared


def test_validate_and_diagnose_real_pdf_profile(tmp_path, capsys):
    module = _load_cli_module()
    workspace, profile, sample, expected = _write_fixture_workspace(tmp_path)

    validate_result = module.main(
        [
            "validate",
            str(profile),
            "--expected-results",
            str(expected),
            "--workspace",
            str(workspace),
        ]
    )
    validate_output = capsys.readouterr().out
    diagnose_result = module.main(["diagnose", str(profile), str(sample)])
    diagnose_output = capsys.readouterr().out

    assert validate_result == 0
    assert "[PASS] supplier_alpha" in validate_output
    assert "sample_report_01.pdf_profile_probe_selected" in validate_output
    assert diagnose_result == 0
    assert "Can parse: True" in diagnose_output
    assert "Reference: REF123" in diagnose_output
    assert "Rows: 1" in diagnose_output


def test_install_list_disable_enable_and_evidence_use_tmp_home(tmp_path, capsys):
    module = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)
    home = tmp_path / "home"

    install_result = module.main(
        [
            "--home",
            str(home),
            "install",
            str(profile),
            "--expected-results",
            str(expected),
            "--workspace",
            str(workspace),
            "--approved-by",
            "pytest",
        ]
    )
    install_output = capsys.readouterr().out
    assert install_result == 0
    assert "Installed: supplier_alpha" in install_output
    assert (home / ".metroliza" / "parser_plugins" / "profiles" / "approved" / "supplier_alpha" / "profile.yaml").exists()

    list_result = module.main(["--home", str(home), "list"])
    list_output = capsys.readouterr().out
    assert list_result == 0
    assert "supplier_alpha\tenabled\tapproved" in list_output

    assert module.main(["--home", str(home), "disable", "supplier_alpha"]) == 0
    capsys.readouterr()
    disabled_result = module.main(["--home", str(home), "list"])
    disabled_output = capsys.readouterr().out
    assert disabled_result == 0
    assert "supplier_alpha\tdisabled\tapproved" in disabled_output

    assert module.main(["--home", str(home), "enable", "supplier_alpha"]) == 0
    capsys.readouterr()
    evidence_result = module.main(["--home", str(home), "evidence", "supplier_alpha"])
    evidence = json.loads(capsys.readouterr().out)
    assert evidence_result == 0
    assert evidence["plugin_id"] == "supplier_alpha"
    assert evidence["enabled"] is True
    assert evidence["approval"]["approved_by"] == "pytest"
    assert str(home / ".metroliza") in evidence["profile_path"]


def test_uninstall_can_archive_a_disabled_generation_without_replacing_it(tmp_path, capsys):
    from metroliza.parsing.declarative_parser_profiles import (
        approved_profiles_dir, disabled_profiles_dir, profile_backups_dir,
    )

    cli = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)
    home = tmp_path / "home"
    args = ["--home", str(home)]
    assert cli.main([*args, "install", str(profile), "--expected-results", str(expected),
                     "--workspace", str(workspace)]) == 0
    assert cli.main([*args, "disable", "supplier_alpha"]) == 0
    generation = disabled_profiles_dir(home=home) / "supplier_alpha"
    contents = {path.name: path.read_bytes() for path in generation.iterdir()}
    profile.write_text(_profile_yaml(version="0.2.0"), encoding="utf-8")
    assert cli.main([*args, "install", str(profile), "--expected-results", str(expected),
                     "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    assert cli.main([*args, "uninstall", "supplier_alpha"]) == 1
    assert "Both approved and disabled generations exist" in capsys.readouterr().out
    assert not list(profile_backups_dir(home=home).glob("supplier_alpha-removed-*"))
    assert cli.main([*args, "uninstall", "supplier_alpha", "--state", "disabled"]) == 0
    assert (approved_profiles_dir(home=home) / "supplier_alpha" / "profile.yaml").exists()
    archive, = profile_backups_dir(home=home).glob("supplier_alpha-removed-*")
    assert archive.name in capsys.readouterr().out
    assert not generation.exists()
    assert {path.name: path.read_bytes() for path in archive.iterdir()} == contents
    assert cli.main([*args, "uninstall", "supplier_alpha", "--state", "disabled"]) == 1
    assert {path.name: path.read_bytes() for path in archive.iterdir()} == contents


def test_uninstall_cannot_remove_an_approved_generation_with_a_different_embedded_id(tmp_path, capsys):
    from metroliza.parsing.declarative_parser_profiles import (
        approved_profiles_dir, load_approved_profile_parsers, profile_backups_dir,
    )

    cli = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)
    home = tmp_path / "home"
    args = ["--home", str(home)]
    assert cli.main([*args, "install", str(profile), "--expected-results", str(expected),
                     "--workspace", str(workspace)]) == 0
    root = approved_profiles_dir(home=home)
    renamed = (root / "supplier_alpha").rename(root / "supplier_beta")
    loaded, errors = load_approved_profile_parsers(home=home)
    assert [plugin_id for plugin_id, _parser in loaded] == ["supplier_alpha"]
    assert errors == ()
    capsys.readouterr()

    assert cli.main([*args, "uninstall", "supplier_beta"]) == 1
    assert "declared plugin ID does not match" in capsys.readouterr().out
    assert renamed.is_dir()
    assert not list(profile_backups_dir(home=home).glob("*-removed-*"))
    loaded_after, errors = load_approved_profile_parsers(home=home)
    assert [plugin_id for plugin_id, _parser in loaded_after] == ["supplier_alpha"]
    assert errors == ()


def test_uninstall_refuses_a_redirected_generation(tmp_path, capsys):
    from metroliza.parsing.declarative_parser_profiles import approved_profiles_dir, profile_backups_dir

    cli = _load_cli_module()
    home = tmp_path / "home"
    target = tmp_path / "outside"
    target.mkdir()
    marker = target / "profile.yaml"
    marker.write_text("outside the profile store", encoding="utf-8")
    generation = approved_profiles_dir(home=home) / "supplier_alpha"
    generation.parent.mkdir(parents=True)
    try:
        generation.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a directory symlink requires host support")
    assert cli.main(["--home", str(home), "uninstall", "supplier_alpha"]) == 1
    assert "ordinary directories" in capsys.readouterr().out
    assert generation.is_symlink()
    assert marker.read_text(encoding="utf-8") == "outside the profile store"
    assert not list(profile_backups_dir(home=home).glob("supplier_alpha-removed-*"))


@pytest.mark.parametrize("unsupported_version", [0, 2])
def test_unsupported_profile_schema_cannot_replace_an_approved_generation(tmp_path, capsys, unsupported_version):
    from metroliza.parsing.declarative_parser_profiles import approved_profiles_dir, profile_store_signature

    cli = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)
    home = tmp_path / "home"
    store = ["--home", str(home)]
    candidate = [str(profile), "--expected-results", str(expected), "--workspace", str(workspace)]
    assert cli.main([*store, "install", *candidate]) == 0
    signature = profile_store_signature(home=home)
    capsys.readouterr()
    profile.write_text(_profile_yaml(version="0.2.0").replace("schema_version: 1", f"schema_version: {unsupported_version}"),
                       encoding="utf-8")
    assert cli.main([*store, "validate", *candidate]) == 1
    assert "schema_version_supported" in capsys.readouterr().out
    assert cli.main([*store, "install", *candidate]) == 1
    assert profile_store_signature(home=home) == signature
    assert "schema_version: 1" in (approved_profiles_dir(home=home) / "supplier_alpha" /
                                  "profile.yaml").read_text(encoding="utf-8")


def test_install_requires_expected_results_and_samples(tmp_path, capsys):
    module = _load_cli_module()
    _workspace, profile, _sample, _expected = _write_fixture_workspace(tmp_path)

    result = module.main(["--home", str(tmp_path / "home"), "install", str(profile)])
    output = capsys.readouterr().out

    assert result == 1
    assert "expected-results CSV" in output
    assert "[PASS]" not in output


def test_install_reports_atomic_store_failure_without_traceback(monkeypatch, tmp_path, capsys):
    module = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)

    def _fail_install(*args, **kwargs):
        raise OSError("injected profile promotion failure")

    monkeypatch.setattr(module, "install_profile", _fail_install)

    result = module.main(
        [
            "--home",
            str(tmp_path / "home"),
            "install",
            str(profile),
            "--expected-results",
            str(expected),
            "--workspace",
            str(workspace),
        ]
    )
    output = capsys.readouterr().out

    assert result == 1
    assert "injected profile promotion failure" in output


def test_store_commands_reject_path_like_plugin_ids(tmp_path, capsys):
    module = _load_cli_module()
    result = module.main(["--home", str(tmp_path / "home"), "disable", "../supplier_alpha"])
    output = capsys.readouterr().out

    assert result == 1
    assert "plugin_id must match" in output


def test_install_creates_backup_and_rollback_restores_previous_profile(tmp_path, capsys):
    module = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path, version="0.1.0")
    home = tmp_path / "home"
    install_args = [
        "--home",
        str(home),
        "install",
        str(profile),
        "--expected-results",
        str(expected),
        "--workspace",
        str(workspace),
    ]

    assert module.main(install_args) == 0
    capsys.readouterr()
    profile.write_text(_profile_yaml(version="0.2.0"), encoding="utf-8")
    assert module.main(install_args) == 0
    second_install_output = capsys.readouterr().out
    assert "Backup:" in second_install_output

    evidence_before_result = module.main(["--home", str(home), "evidence", "supplier_alpha"])
    evidence_before = json.loads(capsys.readouterr().out)
    assert evidence_before_result == 0
    assert evidence_before["approval"]["version"] == "0.2.0"

    rollback_result = module.main(["--home", str(home), "rollback", "supplier_alpha"])
    rollback_output = capsys.readouterr().out
    assert rollback_result == 0
    assert "Rolled back: supplier_alpha" in rollback_output

    evidence_after_result = module.main(["--home", str(home), "evidence", "supplier_alpha"])
    evidence_after = json.loads(capsys.readouterr().out)
    assert evidence_after_result == 0
    assert evidence_after["approval"]["version"] == "0.1.0"


def test_rollback_refuses_to_silently_skip_the_latest_damaged_backup(
    tmp_path, capsys, monkeypatch, qapplication_session,
):
    module = _load_cli_module()
    workspace, profile, _sample, expected = _write_fixture_workspace(tmp_path)
    home = tmp_path / "home"
    install_args = [
        "--home", str(home), "install", str(profile),
        "--expected-results", str(expected), "--workspace", str(workspace),
    ]
    for version in ("0.1.0", "0.2.0", "0.3.0"):
        profile.write_text(_profile_yaml(version=version), encoding="utf-8")
        assert module.main(install_args) == 0

    from metroliza.parsing.declarative_parser_profiles import profile_backups_dir

    newest, earlier = approved_profile_backups("supplier_alpha", home=home)
    latest_profile = profile_backups_dir(home=home) / newest / "profile.yaml"
    latest_profile.write_text("# damaged", encoding="utf-8")
    with pytest.raises(ValueError, match="latest backup.*cannot be verified"):
        rollback_profile("supplier_alpha", backup_name="", home=home)

    from PyQt6.QtWidgets import QMessageBox
    from metroliza.ui.parser_plugin_wizard import ParserPluginWizardDialog

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = ParserPluginWizardDialog(home=home)
    try:
        dialog.profile_list.setCurrentRow(0)
        assert dialog.rollback_button.isEnabled()
        dialog.rollback_button.click()
        assert "latest backup" in dialog.manage_status_label.text()
        assert "cannot be verified" in dialog.manage_status_label.text()
        assert dialog.manage_status_label.property("statusVariant") == "warning"
    finally:
        dialog.close()

    capsys.readouterr()
    assert module.main(["--home", str(home), "evidence", "supplier_alpha"]) == 0
    assert json.loads(capsys.readouterr().out)["approval"]["version"] == "0.3.0"
    rollback_profile("supplier_alpha", backup_name=earlier, home=home)
    assert module.main(["--home", str(home), "evidence", "supplier_alpha"]) == 0
    assert json.loads(capsys.readouterr().out)["approval"]["version"] == "0.1.0"
