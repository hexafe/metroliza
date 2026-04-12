from pathlib import Path

from scripts.generate_chart_parity_fixtures import _clean_output_dir


def test_clean_output_dir_preserves_root_readme(tmp_path: Path):
    output_dir = tmp_path / "chart_parity"
    output_dir.mkdir()
    readme = output_dir / "README.md"
    readme.write_text("fixture docs\n", encoding="utf-8")
    (output_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    histogram_dir = output_dir / "histogram"
    histogram_dir.mkdir()
    (histogram_dir / "payload.json").write_text("{}\n", encoding="utf-8")

    _clean_output_dir(output_dir)

    assert readme.exists()
    assert readme.read_text(encoding="utf-8") == "fixture docs\n"
    assert not (output_dir / "manifest.json").exists()
    assert not histogram_dir.exists()
