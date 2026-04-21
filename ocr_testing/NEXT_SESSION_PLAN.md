# Next session plan: OCR packaging and parser verification

Last updated: 2026-04-21.

Full continuation handoff: `ocr_testing/HANDOFF_2026-04-21_OCR_PACKAGING.md`.
Start there for the exact repo status, verification already run, and next steps for
tests, docs review, GitHub upload, and CI status.

Goal: finish evidence for the RapidOCR LATIN header-OCR production path and prove that
the packaged Windows executable contains the OCR runtime and vendored model files.

## Current status

- Backend decision: RapidOCR LATIN is selected as the primary bundled OCR backend.
- Tesseract remains rejected for the bundled app unless a future fallback need appears.
- Production code now has:
  - lazy RapidOCR adapter: `modules/header_ocr_backend.py`
  - header crop and OCR box conversion: `modules/header_ocr_geometry.py`
  - deterministic correction layer: `modules/header_ocr_corrections.py`
  - parser fallback wiring and metadata diagnostics in `modules/cmm_report_parser.py`
- Vendored model files are present under `modules/ocr_models/rapidocr/`:
  - `ch_PP-OCRv4_det_mobile.onnx`
  - `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
  - `latin_PP-OCRv3_rec_mobile.onnx`
- Model SHA256s are tracked in `RAPIDOCR_MODEL_ASSET_MANIFEST` and verified by:
  - `python scripts/fetch_rapidocr_models.py`
  - `python -c "from scripts.validate_packaged_pdf_parser import validate_vendored_header_ocr_models; print(len(validate_vendored_header_ocr_models()))"`
- PyInstaller packaging collects RapidOCR, ONNX Runtime, OpenCV, NumPy, OCR modules, and
  `modules/ocr_models` data through `packaging/metroliza_onefile.spec`.
- `build_windows_exe.ps1` installs `requirements-ocr.txt` and validates OCR packaging
  inputs before running PyInstaller.
- Nuitka packaging now fails closed by default unless OCR dependencies and model files
  are present, includes RapidOCR/ONNX/OpenCV/NumPy packages and model data, and validates
  the generated report with `--require-header-ocr`.
- Licensing/checklist update: RapidOCR package metadata and repository identify
  Apache-2.0; the RapidOCR project page notes OCR model copyright is held by Baidu.
  `THIRD_PARTY_NOTICES.md` now records the RapidOCR/ONNX/OpenCV/NumPy notice set, is
  included by PyInstaller/Nuitka packaging, and is validated by the packaging checks.
- Release metadata is bumped to `2026.04rc6(260421)` / `2026.04 (build 260421)` for
  the OCR packaging and notice release slice.
- Disposable real-OCR probe succeeded with `uv`, CPython 3.12, RapidOCR 3.8.1, ONNX
  Runtime, PyMuPDF, and the vendored model files across all five extracted samples.
- Real parser extraction over all five extracted sample PDFs succeeded with
  `header_extraction_mode=ocr`, no `header_ocr_error`, expected dates/times/operators,
  and vendored model paths.
- Optional pytest coverage now includes `tests/test_header_ocr_real_integration.py`,
  gated behind `METROLIZA_RUN_REAL_OCR=1`, so local OCR runtime environments can prove
  the real RapidOCR/vendored-model parser path against `ocr_testing/expected_headers.json`.

## Verified in this session

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider \
  tests/test_header_ocr_backend.py \
  tests/test_header_ocr_geometry.py \
  tests/test_header_ocr_corrections.py \
  tests/test_report_metadata_extractor.py \
  tests/test_packaged_pdf_parser_validation.py \
  tests/test_packaging_spec_hiddenimports.py \
  tests/test_requirements_hygiene.py \
  -q
```

Result: `47 passed`.

Additional checks:

```bash
python -m py_compile scripts/fetch_rapidocr_models.py scripts/validate_packaged_pdf_parser.py modules/header_ocr_backend.py
python -c "from scripts.validate_packaged_pdf_parser import validate_vendored_header_ocr_models; print(len(validate_vendored_header_ocr_models()))"
sha256sum modules/ocr_models/rapidocr/*.onnx
```

Result: model validator returned `3`; ONNX hashes matched the manifest.

Real OCR probe:

```bash
uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-ocr.txt \
  --with PyMuPDF \
  python ocr_testing/header_ocr_probe.py --engine rapidocr \
  --output /tmp/metroliza_rapidocr_probe_all.json
```

Result: exit code `0`; all five `example_reports/extracted` PDFs returned `ok: true`
and RapidOCR logged the vendored model paths.

Real parser extraction smoke:

```bash
uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-ocr.txt \
  --with PyMuPDF --with pandas --with PyQt6 \
  python - <<'PY'
from pathlib import Path
from modules.cmm_report_parser import CMMReportParser
for pdf in sorted(Path('/home/hexaf/Projects/example_reports/extracted').glob('*.pdf')) + sorted(Path('/home/hexaf/Projects/example_reports/extracted').glob('*.PDF')):
    parser = CMMReportParser(str(pdf), ':memory:')
    parser.open_report()
    md = parser.extract_metadata().metadata
    print(pdf.name, md.reference, md.report_date, md.report_time, md.operator_name, md.metadata_json.get('header_extraction_mode'), md.metadata_json.get('header_ocr_error'))
PY
```

Result: all five samples extracted via OCR with `header_ocr_error=None`.

Optional real RapidOCR integration smoke:

```bash
METROLIZA_RUN_REAL_OCR=1 uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-ocr.txt \
  --with PyMuPDF --with pandas --with PyQt6 \
  pytest -p no:cacheprovider tests/test_header_ocr_real_integration.py -q
```

This test skips by default in normal CI unless explicitly enabled.

Documentation/versioning follow-up added:

```bash
python scripts/sync_release_metadata.py
```

Result: README and CHANGELOG release labels were synced to `2026.04 (build 260421)`;
`THIRD_PARTY_NOTICES.md` is now part of both packager data paths.

## Next tasks

1. Build PyInstaller on Windows:

   ```powershell
   .\build_windows_exe.ps1 -Clean
   ```

   Confirm the produced `.exe` can parse at least one sample PDF with
   `metadata_json.header_extraction_mode == "ocr"` or a successful structured-word mode.

2. Build Nuitka on Windows after installing `requirements-build.txt` and
   `requirements-ocr.txt`:

   ```powershell
   .\packaging\build_nuitka.ps1 -FastDev
   .\packaging\build_nuitka.ps1
   ```

   Do not use `-AllowMissingHeaderOcrBuild` for release artifacts.

3. Add a packaged-artifact smoke command if the app already has a non-interactive parser
   entry point. If not, add the smallest safe CLI/smoke hook that parses one PDF and
   exits with a useful status code.

## Known residual risks

- Real RapidOCR was run from a disposable CPython 3.12 `uv` environment, not from the
  active Python 3.14 shell.
- Nuitka/PyInstaller report checks prove inclusion intent and model files, but the final
  `.exe` still needs a clean-machine Windows launch and parse smoke.
- OCR currently runs over the selected header crop and binds by OCR boxes. The plan's
  stricter per-cell OCR can still be added if whole-crop OCR produces unstable field
  binding on the broader corpus.
