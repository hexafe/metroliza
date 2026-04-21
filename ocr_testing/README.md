# OCR testing workspace

This directory is for comparing two OCR paths for rasterized CMM report headers without
changing the production parser:

1. PyMuPDF header crop + Tesseract OCR
2. PyMuPDF header crop + RapidOCR / ONNX Runtime

The probe defaults to the sample PDFs in:

```text
/home/hexaf/Projects/example_reports/extracted
```

Run from the Metroliza repo root.

## Tesseract probe

Prerequisites:

- `tesseract --version` works in the shell.
- `TESSDATA_PREFIX` points to the tessdata directory when Tesseract cannot find it by
  itself.
- `eng.traineddata` is enough for structural testing. `pol.traineddata` is preferred for
  Polish month names and operator/comment fidelity.

Command:

```bash
python ocr_testing/header_ocr_probe.py --engine pymupdf-tesseract --language pol+eng
```

## RapidOCR probe

Install OCR runtime dependencies in a throwaway environment:

```bash
python -m pip install -r requirements-ocr.txt
```

Command:

```bash
python ocr_testing/header_ocr_probe.py --engine rapidocr
```

Production packaging uses the vendored RapidOCR model files in
`modules/ocr_models/rapidocr/` and should not depend on user-cache downloads at runtime.
If the local model files are missing or their hashes drift, refresh them with:

```bash
python scripts/fetch_rapidocr_models.py
```

Keep the root `THIRD_PARTY_NOTICES.md` file with every packaged release artifact. It
records the RapidOCR Apache-2.0 notice, Baidu model attribution, and OCR runtime
dependency notices used by the PyInstaller and Nuitka packaging paths.

## Compare both

```bash
python ocr_testing/header_ocr_probe.py --engine both --language pol+eng \
  --output ocr_testing/local_probe_results.json
```

`local_probe_results.json` is intentionally ignored by convention and should not be used
as a golden fixture. Promote only reviewed, stable expectations into tests.
