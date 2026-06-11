import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_cli_module():
    script_path = REPO_ROOT / "scripts" / "parser_plugin_self_service.py"
    spec = importlib.util.spec_from_file_location("test_parser_plugin_self_service", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def _write_fixture_workspace(tmp_path, *, version: str = "0.1.0", marker: str = "SUPPLIER TEMPLATE MARKER"):
    workspace = tmp_path / "workspace"
    samples = workspace / "samples"
    samples.mkdir(parents=True)
    profile = workspace / "profile.yaml"
    profile.write_text(_profile_yaml(version=version, marker=marker), encoding="utf-8")
    sample = samples / "sample_report_01.pdf"
    sample.write_text(
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
        encoding="utf-8",
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


def test_validate_and_diagnose_plain_text_pdf_profile(tmp_path, capsys):
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


def test_install_requires_expected_results_and_samples(tmp_path, capsys):
    module = _load_cli_module()
    _workspace, profile, _sample, _expected = _write_fixture_workspace(tmp_path)

    result = module.main(["--home", str(tmp_path / "home"), "install", str(profile)])
    output = capsys.readouterr().out

    assert result == 1
    assert "expected-results CSV" in output
    assert "[PASS]" not in output


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
