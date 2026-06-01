from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import (
    benchmark_comparison_stats,
    benchmark_distribution_fit_batch,
    benchmark_openvino_tuning_matrix,
    build_pdf_corpus_manifest,
    check_release_hygiene,
    compare_header_ocr_crop_results,
    compare_ocr_metadata_benchmarks,
    diagnose_header_ocr_metadata,
    fetch_rapidocr_models,
    inspect_ocr_benchmark_results,
    release_only_google_conversion_smoke,
    validate_qt_runtime,
    windows_ocr_runtime_diagnostics,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_pdf_corpus_manifest_deduplicates_and_groups_pdfs(tmp_path: Path) -> None:
    alpha_dir = tmp_path / "alpha"
    nested_dir = tmp_path / "nested"
    alpha_dir.mkdir()
    nested_dir.mkdir()
    first_pdf = alpha_dir / "first.pdf"
    duplicate_pdf = alpha_dir / "duplicate.pdf"
    nested_pdf = nested_dir / "second.pdf"
    ignored_txt = nested_dir / "notes.txt"
    first_pdf.write_bytes(b"same")
    duplicate_pdf.write_bytes(b"same")
    nested_pdf.write_bytes(b"different")
    ignored_txt.write_text("not a pdf", encoding="utf-8")

    manifest = build_pdf_corpus_manifest.build_manifest([str(alpha_dir), str(nested_pdf)])

    assert manifest["pdf_count"] == 3
    assert manifest["unique_sha256_count"] == 2
    assert manifest["duplicate_sha256_count"] == 1
    assert manifest["group_counts"] == {"alpha": 2, "nested": 1}
    assert [entry["index"] for entry in manifest["entries"]] == [0, 1, 2]
    assert {entry["relative_path"] for entry in manifest["entries"]} == {
        "duplicate.pdf",
        "first.pdf",
        ".",
    }


def test_build_pdf_corpus_manifest_main_writes_json(tmp_path: Path) -> None:
    pdf_path = tmp_path / "report.pdf"
    output_path = tmp_path / "out" / "manifest.json"
    pdf_path.write_bytes(b"%PDF fixture")

    result = build_pdf_corpus_manifest.main([str(pdf_path), "--output", str(output_path)])

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["pdf_count"] == 1
    assert payload["entries"][0]["path"] == str(pdf_path.resolve())


def test_compare_header_ocr_crop_results_reports_text_and_speed_diffs(tmp_path: Path) -> None:
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    _write_json(
        left_path,
        {
            "rows": [
                {
                    "ok": True,
                    "image_path": "a.png",
                    "pdf_path": "a.pdf",
                    "ocr_s": 4.0,
                    "records": [{"text": "REF123"}, {"text": "DATE"}],
                },
                {"ok": True, "image_path": "left-only.png", "ocr_s": 1.0, "records": []},
                {"ok": False, "image_path": "ignored.png"},
            ]
        },
    )
    _write_json(
        right_path,
        {
            "rows": [
                {
                    "ok": True,
                    "image_path": "a.png",
                    "pdf_path": "a.pdf",
                    "ocr_s": 2.0,
                    "records": [{"text": "REF123"}, {"text": "TIME"}],
                },
                {"ok": True, "image_path": "right-only.png", "ocr_s": 3.0, "records": []},
            ]
        },
    )

    comparison = compare_header_ocr_crop_results.compare(str(left_path), str(right_path))

    assert comparison["common_count"] == 1
    assert comparison["left_only_count"] == 1
    assert comparison["right_only_count"] == 1
    assert comparison["speedup_ratio"] == 2.0
    assert comparison["text_diff_files"] == 1
    assert comparison["diff_examples"][0]["left_texts"] == ["REF123", "DATE"]


def test_compare_header_ocr_crop_results_main_writes_output(tmp_path: Path) -> None:
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    output_path = tmp_path / "comparison.json"
    _write_json(left_path, {"rows": [{"ok": True, "image_path": "a.png", "records": []}]})
    _write_json(right_path, {"rows": [{"ok": True, "image_path": "a.png", "records": []}]})

    result = compare_header_ocr_crop_results.main(
        ["--left", str(left_path), "--right", str(right_path), "--output", str(output_path)]
    )

    assert result == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["common_count"] == 1


def test_inspect_ocr_benchmark_results_summarizes_modes(tmp_path: Path) -> None:
    payload = {
        "input": "manifest.json",
        "environment": {"engine": "openvino"},
        "summary": {"pdfs_selected": 2},
        "results": [
            {
                "mode": "complete",
                "ok": True,
                "wall_s": 1.25,
                "header_diagnostics": {
                    "header_ocr_runtime_s": 0.5,
                    "header_extraction_mode": "ocr",
                    "header_ocr_error": "",
                },
                "metadata": {
                    "reference": "REF123",
                    "report_date": "",
                    "warnings": ["weak_reference"],
                },
            },
            {
                "mode": "complete",
                "ok": False,
                "wall_s": 0.75,
                "header_diagnostics": {
                    "header_ocr_runtime_s": 0.25,
                    "header_extraction_mode": "filename",
                    "header_ocr_error": "header_ocr_disabled",
                },
                "metadata": {},
            },
            {"mode": "light", "ok": True, "wall_s": 0.5, "header_diagnostics": {}},
        ],
    }

    summary = inspect_ocr_benchmark_results.summarize(payload)

    complete = summary["by_mode"]["complete"]
    assert complete["count"] == 2
    assert complete["ok_count"] == 1
    assert complete["error_count"] == 1
    assert complete["avg_header_ocr_runtime_s"] == 0.375
    assert complete["header_ocr_errors"]["header_ocr_disabled"] == 1
    assert complete["field_null_counts"]["report_date"] == 2
    assert complete["warning_counts"] == {"weak_reference": 1}


def test_inspect_ocr_benchmark_results_main_writes_output(tmp_path: Path) -> None:
    input_path = tmp_path / "benchmark.json"
    output_path = tmp_path / "summary.json"
    _write_json(input_path, {"results": [{"mode": "light", "ok": True, "wall_s": 1.0}]})

    result = inspect_ocr_benchmark_results.main([str(input_path), "--output", str(output_path)])

    assert result == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["by_mode"]["light"]["count"] == 1


def test_compare_ocr_metadata_benchmarks_counts_field_differences(tmp_path: Path) -> None:
    left_path = tmp_path / "light.json"
    right_path = tmp_path / "complete.json"
    _write_json(
        left_path,
        {
            "results": [
                {
                    "ok": True,
                    "pdf_path": "a.pdf",
                    "metadata": {
                        "reference": "",
                        "report_date": "2026-01-01",
                        "field_sources": {"reference": "filename", "report_date": "text"},
                    },
                },
                {"ok": True, "pdf_path": "left-only.pdf", "metadata": {}},
            ]
        },
    )
    _write_json(
        right_path,
        {
            "results": [
                {
                    "ok": True,
                    "pdf_path": "a.pdf",
                    "metadata": {
                        "reference": "REF123",
                        "report_date": "",
                        "field_sources": {"reference": "ocr", "report_date": "text"},
                    },
                },
                {"ok": True, "pdf_path": "right-only.pdf", "metadata": {}},
            ]
        },
    )

    comparison = compare_ocr_metadata_benchmarks.compare(str(left_path), str(right_path))

    reference = comparison["field_summary"]["reference"]
    report_date = comparison["field_summary"]["report_date"]
    assert comparison["common_count"] == 1
    assert comparison["left_only"] == ["left-only.pdf"]
    assert comparison["right_only"] == ["right-only.pdf"]
    assert reference["different"] == 1
    assert reference["left_empty_right_filled"] == 1
    assert reference["source_changed"] == 1
    assert report_date["left_filled_right_empty"] == 1
    assert comparison["examples"]["reference"][0]["right"] == "REF123"


def test_compare_ocr_metadata_benchmarks_main_prints_json(tmp_path: Path, capsys) -> None:
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    _write_json(left_path, {"results": [{"ok": True, "pdf_path": "a.pdf", "metadata": {}}]})
    _write_json(right_path, {"results": [{"ok": True, "pdf_path": "a.pdf", "metadata": {}}]})

    result = compare_ocr_metadata_benchmarks.main(
        ["--left", str(left_path), "--right", str(right_path)]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["common_count"] == 1


def test_openvino_tuning_matrix_summarizes_variant_payload(tmp_path: Path) -> None:
    payload_path = tmp_path / "variant.json"
    _write_json(
        payload_path,
        {
            "summary": {
                "error_count": 0,
                "pdfs_selected": 3,
                "completed_mode_pdf_runs": 3,
                "by_mode": {"complete": {"total_wall_s": 9.0, "avg_wall_s": 3.0}},
            },
            "environment": {"header_ocr_runtime_config": {"engine": "openvino"}},
            "results": [
                {"header_diagnostics": {"header_ocr_runtime_s": 1.0}},
                {"header_diagnostics": {"header_ocr_runtime_s": 2.0}},
            ],
        },
    )

    row = benchmark_openvino_tuning_matrix._variant_summary("openvino_t4_default", payload_path, 0)

    assert row["ok"] is True
    assert row["pdfs_selected"] == 3
    assert row["sum_header_ocr_runtime_s"] == 3.0
    assert row["avg_header_ocr_runtime_s"] == 1.5
    assert row["runtime_config"] == {"engine": "openvino"}


def test_openvino_tuning_matrix_main_uses_selected_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def fake_run_variant(*, variant, manifest, limit, output_dir, progress_every):
        assert manifest == "manifest.json"
        assert limit == 7
        assert progress_every == 2
        assert output_dir == tmp_path
        return {
            "variant": variant["name"],
            "ok": True,
            "total_wall_s": 4.0,
            "sum_header_ocr_runtime_s": 3.0,
        }

    monkeypatch.setattr(benchmark_openvino_tuning_matrix, "run_variant", fake_run_variant)

    result = benchmark_openvino_tuning_matrix.main(
        [
            "--manifest",
            "manifest.json",
            "--limit",
            "7",
            "--progress-every",
            "2",
            "--output-dir",
            str(tmp_path),
            "--variant",
            "openvino_t4_default",
        ]
    )

    summary = json.loads((tmp_path / "matrix_summary.json").read_text(encoding="utf-8"))
    assert result == 0
    assert summary["variant_count"] == 1
    assert summary["ok_count"] == 1
    assert summary["fastest_wall_variant"] == "openvino_t4_default"
    assert json.loads(capsys.readouterr().out)["fastest_ocr_variant"] == "openvino_t4_default"


def test_release_hygiene_collects_only_existing_blocked_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "coverage.xml"
    missing = tmp_path / "missing.pdf"
    allowed = tmp_path / "README.md"
    blocked.write_text("<coverage />", encoding="utf-8")
    allowed.write_text("ok", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    violations = check_release_hygiene._collect_violations(
        [blocked.name, missing.name, allowed.name],
        label="tracked",
    )

    assert violations == ["tracked: coverage.xml (generated release report)"]


def test_release_hygiene_main_reports_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "coverage.xml").write_text("<coverage />", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        check_release_hygiene,
        "_git_lines",
        lambda *args: ["coverage.xml"] if args == ("ls-files",) else [],
    )

    result = check_release_hygiene.main()

    output = capsys.readouterr().out
    assert result == 1
    assert "Release hygiene check failed:" in output
    assert "tracked: coverage.xml" in output


def test_validate_qt_runtime_success_payload_includes_library_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LibraryPath:
        PrefixPath = object()
        BinariesPath = object()
        LibrariesPath = object()
        PluginsPath = object()

    class QLibraryInfo:
        @staticmethod
        def path(enum_value):
            return {
                LibraryPath.PrefixPath: "/qt",
                LibraryPath.BinariesPath: "/qt/bin",
                LibraryPath.LibrariesPath: "/qt/lib",
                LibraryPath.PluginsPath: "/qt/plugins",
            }[enum_value]

    QLibraryInfo.LibraryPath = LibraryPath

    class QtCoreStub:
        QT_VERSION_STR = "6.6.1"
        PYQT_VERSION_STR = "6.6.1"

        @staticmethod
        def qVersion():
            return "6.6.1"

    QtCoreStub.QLibraryInfo = QLibraryInfo

    monkeypatch.setattr(validate_qt_runtime, "_import_pyqt_modules", lambda: (QtCoreStub, object()))
    monkeypatch.setattr(
        validate_qt_runtime,
        "_distribution_version",
        lambda name: {
            "PyQt6": "6.6.1",
            "PyQt6-Qt6": "6.6.1",
            "PyQt6-sip": "13.6.0",
        }.get(name),
    )

    payload = validate_qt_runtime.build_payload()

    assert payload["ok"] is True
    assert payload["pyqt"]["import_ok"] is True
    assert payload["pyqt"]["library_paths"]["PluginsPath"] == "/qt/plugins"


def test_validate_qt_runtime_main_writes_compact_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate_qt_runtime, "build_payload", lambda: {"ok": False, "pyqt": {}})
    output_path = tmp_path / "qt.json"

    result = validate_qt_runtime.main(["--compact", "--output", str(output_path)])

    assert result == 1
    assert output_path.read_text(encoding="utf-8") == '{"ok": false, "pyqt": {}}\n'


def test_benchmark_comparison_stats_main_writes_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    output_path = tmp_path / "comparison.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_comparison_stats.py",
            "--groups",
            "2",
            "--samples",
            "3",
            "--ci-iterations",
            "1",
            "--marshal-repeats",
            "1",
            "--output-json",
            str(output_path),
        ],
    )
    monkeypatch.setattr(
        benchmark_comparison_stats,
        "_build_fixture",
        lambda *, group_count, samples_per_group, seed: {"A": [1.0, 2.0], "B": [2.0, 3.0]},
    )
    monkeypatch.setattr(benchmark_comparison_stats, "_run_ci_path", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(
        benchmark_comparison_stats,
        "_run_pairwise_path",
        lambda *_args, **_kwargs: 2.0,
    )
    monkeypatch.setattr(benchmark_comparison_stats, "native_backend_available", lambda: False)
    monkeypatch.setattr(
        benchmark_comparison_stats,
        "_run_marshaling_benchmark",
        lambda **_kwargs: {
            "list_input_seconds": 3.0,
            "ndarray_input_seconds": 1.0,
            "ndarray_vs_list_speedup_ratio": 3.0,
        },
    )

    result = benchmark_comparison_stats.main()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["config"]["groups"] == 2
    assert payload["results"][0]["stage_timings_s"]["python_ci_seconds"] == 1.0
    assert "comparison_stats_ci_python_seconds=1.000000" in capsys.readouterr().out


def test_benchmark_distribution_fit_main_covers_optional_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    output_path = tmp_path / "distribution.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_distribution_fit_batch.py",
            "--metrics",
            "1",
            "--groups",
            "2",
            "--samples",
            "3",
            "--marshal-repeats",
            "1",
            "--candidate-kernel-benchmark",
            "--batch-native-benchmark",
            "--output-json",
            str(output_path),
        ],
    )
    monkeypatch.setattr(
        benchmark_distribution_fit_batch,
        "_build_fixture",
        lambda metrics, groups, samples, seed: {"M": {"G": [1.0, 2.0]}},
    )
    monkeypatch.setattr(
        benchmark_distribution_fit_batch,
        "_run_marshaling_benchmark",
        lambda **_kwargs: {
            "list_input_seconds": 2.0,
            "ndarray_input_seconds": 1.0,
            "ndarray_vs_list_speedup_ratio": 2.0,
        },
    )
    monkeypatch.setattr(
        benchmark_distribution_fit_batch,
        "_run_legacy_per_group",
        lambda fixture: (4.0, {"baseline": True}),
    )
    monkeypatch.setattr(
        benchmark_distribution_fit_batch,
        "_run_batch",
        lambda fixture, **_kwargs: (2.0, {"candidate": True}),
    )
    monkeypatch.setattr(benchmark_distribution_fit_batch, "_validate_parity", lambda *a, **k: [])
    monkeypatch.setattr(
        benchmark_distribution_fit_batch,
        "native_candidate_metrics_backend_available",
        lambda: False,
    )

    benchmark_distribution_fit_batch.main()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert result["candidate_kernel"]["ranking_parity_mismatches"] == 0
    assert result["batch_native"]["ranking_parity_mismatches"] == 0
    assert "candidate_kernel_ranking_parity_mismatches=0" in capsys.readouterr().out


def test_diagnose_header_ocr_metadata_classifies_runtime_issues() -> None:
    assert (
        diagnose_header_ocr_metadata._classify_runtime_issue(
            {"header_extraction_mode": "ocr"},
            {},
        )
        == "OCR ran in the app parser path."
    )
    assert "model files were missing" in diagnose_header_ocr_metadata._classify_runtime_issue(
        {"header_ocr_error": "header_ocr_models_missing:model.onnx"},
        {"reference": "filename_candidate"},
    )
    assert "disabled" in diagnose_header_ocr_metadata._classify_runtime_issue(
        {"header_ocr_error": "header_ocr_disabled"},
        {},
    )
    assert "Only filename metadata" in diagnose_header_ocr_metadata._classify_runtime_issue(
        {},
        {"reference": "filename_candidate", "report_date": None},
    )
    assert "inspect field_sources" in diagnose_header_ocr_metadata._classify_runtime_issue(
        {},
        {"reference": "structured_text"},
    )


def test_diagnose_header_ocr_metadata_loads_existing_database_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "reports.sqlite"
    import sqlite3

    connection = sqlite3.connect(db_file)
    try:
        connection.executescript(
            """
            CREATE TABLE source_files (
                id INTEGER PRIMARY KEY,
                absolute_path TEXT,
                sha256 TEXT,
                is_active INTEGER
            );
            CREATE TABLE parsed_reports (
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER,
                parser_id TEXT,
                parser_version TEXT,
                template_family TEXT,
                template_variant TEXT,
                parse_status TEXT
            );
            CREATE TABLE report_metadata (
                report_id INTEGER,
                reference TEXT,
                report_date TEXT,
                sample_number TEXT,
                metadata_json TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO source_files VALUES (1, '/tmp/report.pdf', 'abc123', 1)"
        )
        connection.execute(
            "INSERT INTO parsed_reports VALUES (2, 1, 'cmm', '1.0', 'family', 'v1', 'ok')"
        )
        connection.execute(
            "INSERT INTO report_metadata VALUES (2, 'REF123', '2026-01-01', 'S1', ?)",
            (json.dumps({"field_sources": {"reference": "ocr"}}),),
        )
        connection.commit()
    finally:
        connection.close()

    real_connect = sqlite3.connect

    class ClosingConnection:
        def __init__(self, path: Path, *args, **kwargs):
            self.connection = real_connect(path, *args, **kwargs)

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc, traceback):
            self.connection.close()
            return False

    monkeypatch.setattr(
        diagnose_header_ocr_metadata.sqlite3,
        "connect",
        lambda *args, **kwargs: ClosingConnection(*args, **kwargs),
    )
    rows = diagnose_header_ocr_metadata._source_rows_for_sha(db_file, "abc123")

    assert rows == [
        {
            "source_file_id": 1,
            "absolute_path": "/tmp/report.pdf",
            "sha256": "abc123",
            "is_active": 1,
            "report_id": 2,
            "parser_id": "cmm",
            "parser_version": "1.0",
            "template_family": "family",
            "template_variant": "v1",
            "parse_status": "ok",
            "reference": "REF123",
            "report_date": "2026-01-01",
            "sample_number": "S1",
            "metadata_json": {"field_sources": {"reference": "ocr"}},
        }
    ]
    assert diagnose_header_ocr_metadata._source_rows_for_sha(tmp_path / "missing.sqlite", "abc123") == []


def test_fetch_rapidocr_model_reuses_verified_existing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "models"
    output_dir.mkdir()
    model_path = output_dir / "model.onnx"
    model_path.write_bytes(b"model-bytes")
    expected_sha = fetch_rapidocr_models._sha256(model_path)

    result = fetch_rapidocr_models.fetch_model(
        "model.onnx",
        url="https://example.invalid/model.onnx",
        expected_sha256=expected_sha,
        output_dir=output_dir,
        force=False,
    )

    assert result == model_path
    assert "ok existing" in capsys.readouterr().out


def test_fetch_rapidocr_model_rejects_existing_hash_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "models"
    output_dir.mkdir()
    (output_dir / "model.onnx").write_bytes(b"wrong")

    with pytest.raises(SystemExit, match="exists but has SHA256"):
        fetch_rapidocr_models.fetch_model(
            "model.onnx",
            url="https://example.invalid/model.onnx",
            expected_sha256="0" * 64,
            output_dir=output_dir,
            force=False,
        )


def test_google_conversion_smoke_local_preconditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(release_only_google_conversion_smoke.SMOKE_OPT_IN_ENV, raising=False)
    with pytest.raises(release_only_google_conversion_smoke.SmokeConfigError):
        release_only_google_conversion_smoke._require_opt_in()

    monkeypatch.setenv(release_only_google_conversion_smoke.SMOKE_OPT_IN_ENV, "1")
    release_only_google_conversion_smoke._require_opt_in()

    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text("{}", encoding="utf-8")
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(
        release_only_google_conversion_smoke.SMOKE_CREDENTIALS_PATH_ENV,
        str(credentials),
    )
    monkeypatch.setenv(release_only_google_conversion_smoke.SMOKE_TOKEN_PATH_ENV, str(token))

    assert release_only_google_conversion_smoke._resolve_secret_file(
        release_only_google_conversion_smoke.SMOKE_CREDENTIALS_PATH_ENV,
        default_path="credentials.json",
        expected_name="credentials.json",
    ) == credentials.resolve()
    assert (
        release_only_google_conversion_smoke._extract_sheet_id(
            "https://docs.google.com/spreadsheets/d/sheet_123-ABC/edit"
        )
        == "sheet_123-ABC"
    )
    assert release_only_google_conversion_smoke._extract_sheet_id("https://example.com") is None


def test_google_conversion_smoke_creates_minimal_workbook(tmp_path: Path) -> None:
    workbook_path = tmp_path / "smoke.xlsx"

    sheet_names = release_only_google_conversion_smoke._create_minimal_workbook(workbook_path)

    assert sheet_names == ["MEASUREMENTS", "REF_A"]
    assert workbook_path.stat().st_size > 0


def test_windows_ocr_runtime_diagnostics_main_writes_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "diagnostics.json"
    monkeypatch.setattr(
        windows_ocr_runtime_diagnostics,
        "build_payload",
        lambda pdf_path=None, db_file=None: {
            "pdf_path": str(pdf_path) if pdf_path else None,
            "db_file": db_file,
            "smoke_tests": [],
        },
    )

    result = windows_ocr_runtime_diagnostics.main(
        [
            "--pdf",
            str(tmp_path / "report.pdf"),
            "--db-file",
            "reports.sqlite",
            "--compact",
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["pdf_path"].endswith("report.pdf")
    assert payload["db_file"] == "reports.sqlite"


def test_windows_ocr_runtime_diagnostics_non_windows_vc_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows_ocr_runtime_diagnostics.platform, "system", lambda: "Linux")

    assert windows_ocr_runtime_diagnostics._vc_redist_registry_status() == {
        "checked": False,
        "reason": "not_windows",
    }
