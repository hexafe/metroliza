from pathlib import Path


def test_onefile_spec_includes_builtin_cmm_parser_hiddenimport():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "modules.cmm_report_parser" in spec_text
    assert "modules.native_chart_compositor" in spec_text
    assert "_metroliza_cmm_native" in spec_text
    assert "_metroliza_chart_native" in spec_text


def test_onefile_spec_collects_hexafe_groupstats_hiddenimports():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "_collect_optional_runtime_assets('hexafe_groupstats')" in spec_text
    assert "'hexafe_groupstats'" in spec_text
    assert "*hexafe_groupstats_hiddenimports" in spec_text


def test_onefile_spec_uses_release_metadata_pyinstaller_output_name():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert 'OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"' in spec_text
    assert "name=OUTPUT_NAME" in spec_text
