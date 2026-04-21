RapidOCR Latin model assets for packaged builds.

Production OCR packaging expects these ONNX files in this directory:

- ch_PP-OCRv4_det_mobile.onnx
- ch_ppocr_mobile_v2.0_cls_mobile.onnx
- latin_PP-OCRv3_rec_mobile.onnx

Fetch or refresh them with:

```bash
python scripts/fetch_rapidocr_models.py
```

The fetch script verifies SHA256 hashes from RapidOCR's `default_models.yaml`
manifest. PyInstaller and Nuitka include these local files in the executable so
header OCR does not depend on a user cache or network access.

Source manifest:

- https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml

License and attribution:

- RapidOCR is Apache-2.0 licensed.
- RapidOCR's project page notes that OCR model copyright is held by Baidu.
- Keep the root `THIRD_PARTY_NOTICES.md` file with commercial distributions of the executable.
- PyInstaller and Nuitka release builds bundle `THIRD_PARTY_NOTICES.md`; update that root
  notice if RapidOCR, model files, or OCR runtime dependencies change.
