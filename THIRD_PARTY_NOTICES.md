# Third-party notices

This project bundles third-party runtime components for packaged executables.
Keep this file with every packaged release artifact and installed application
bundle. PyInstaller and Nuitka release builds include this file as
`THIRD_PARTY_NOTICES.md` next to the executable's bundled data.

This notice is a release compliance aid, not legal advice. Before public or
commercial distribution, verify the exact package versions in the build
environment and keep each dependency's license/metadata files when the packager
can preserve them.

## Header OCR runtime

Metroliza's packaged header OCR path uses RapidOCR with ONNX Runtime by default,
OpenVINO as a selectable CPU acceleration backend, and a small set of vendored
ONNX model files listed in `modules/ocr_models/rapidocr/README.md`. The packaged
application uses local model files and does not download OCR models at runtime.

| Component | License / notice | Project |
| --- | --- | --- |
| RapidOCR | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| RapidOCR PyPI package | Apache-2.0 package metadata; pinned in `requirements-ocr.txt` | https://pypi.org/project/rapidocr/ |
| RapidOCR model assets | RapidOCR's project page states that OCR model copyright is held by Baidu | https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime |
| OpenVINO | Apache-2.0 | https://github.com/openvinotoolkit/openvino |
| OpenCV Python package | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause | https://numpy.org/ |

Vendored RapidOCR model files:

- `modules/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx`
- `modules/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- `modules/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx`

## Release packaging obligations

- Ship or attach this notice with every distributed executable, installer, ZIP,
  or other release artifact.
- Preserve RapidOCR's Apache-2.0 license notice and the model copyright
  attribution above.
- Preserve ONNX Runtime, OpenVINO, OpenCV, and NumPy license/metadata files when the
  packaging tool can include distribution metadata.
- If RapidOCR, OCR model files, ONNX Runtime, OpenVINO, OpenCV, NumPy, or their pinned
  versions change, update this file and rerun the packaging validation tests.
- Do not publish a release artifact produced with an unsafe OCR packaging
  override such as `-AllowMissingHeaderOcrBuild`.

Commercial distribution note: Apache-2.0, MIT, and BSD-3-Clause are permissive
licenses commonly used in commercial software distribution, provided their
license and notice obligations are followed.
