from pathlib import Path


def test_onefile_spec_includes_builtin_cmm_parser_hiddenimport():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "modules.cmm_report_parser" in spec_text
    assert "_metroliza_cmm_native" in spec_text
    assert "_metroliza_chart_native" in spec_text
