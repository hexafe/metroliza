# Third-party notices

This project bundles third-party runtime components for packaged executables.
Keep this file with every packaged release artifact and installed application
bundle. PyInstaller and Nuitka release builds include this file as
`THIRD_PARTY_NOTICES.md` next to the executable's bundled data.

The metadata-derived inventory for build `260711` is
[`docs/release_checks/third_party_inventory_260711.json`](docs/release_checks/third_party_inventory_260711.json).
It records 77 installed Python distributions and 83 resolved Rust packages from
the release environment. Packaging also emits this inventory and a SHA-256
manifest in a visible `.licenses` sidecar beside each distributable artifact.

This notice is a release compliance aid, not legal advice. Before public or
commercial distribution, verify the exact package versions in the build
environment and keep each dependency's license/metadata files when the packager
can preserve them.

## Header OCR runtime

Metroliza's packaged header OCR path uses RapidOCR with ONNX Runtime by default,
OpenVINO as a selectable CPU acceleration backend, and a small set of vendored
ONNX model files listed in `src/metroliza/resources/ocr_models/rapidocr/README.md`. The packaged
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

- `src/metroliza/resources/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx`
- `src/metroliza/resources/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- `src/metroliza/resources/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx`

## Hexafe runtime packages

Metroliza can bundle internal Hexafe runtime packages for grouped statistics,
statistical plots, and industrial database access.

| Component | License / notice | Project |
| --- | --- | --- |
| hexafe-groupstats | MIT | https://github.com/hexafe/hexafe-groupstats |
| hexafe-plotstats | MIT | https://github.com/hexafe/hexafe-plotstats |
| Oznak | MIT | https://github.com/hexafe/oznak |

## Excel parser profile readers

Declarative parser profiles can read Excel workbooks through pandas and the
runtime reader packages listed below.

| Component | License / notice | Project |
| --- | --- | --- |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| et-xmlfile | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| xlrd | BSD-3-Clause | https://xlrd.readthedocs.io/ |

## Desktop, PDF, security, cloud, analytics, and export runtime

| Component | License / notice | Project |
| --- | --- | --- |
| PyQt6 | GNU GPL v3 or Riverbank Commercial License; PyQt itself is not LGPL | https://www.riverbankcomputing.com/software/pyqt/intro/ |
| Qt libraries bundled by the PyQt6 wheel | The GPL PyQt wheel includes the corresponding LGPL Qt build; retain Qt license texts and relinking notices | https://www.riverbankcomputing.com/software/pyqt/intro/ |
| PyMuPDF / MuPDF | GNU AGPL or a commercial Artifex license | https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| google-auth and google-auth-oauthlib | Apache-2.0 | https://github.com/googleapis/google-auth-library-python |
| Matplotlib | Matplotlib/PSF-compatible license | https://matplotlib.org/stable/project/license.html |
| Pillow | HPND | https://python-pillow.github.io/ |
| SciPy | BSD-3-Clause | https://scipy.org/ |
| seaborn | BSD-3-Clause | https://seaborn.pydata.org/ |
| PyYAML | MIT | https://pyyaml.org/ |
| XlsxWriter | BSD-2-Clause | https://xlsxwriter.readthedocs.io/ |
| pandas (resolved through the pinned Oznak runtime) | BSD-3-Clause | https://pandas.pydata.org/ |
| SQLAlchemy | MIT | https://www.sqlalchemy.org/ |
| Plotly.js 2.27.0 vendored dashboard asset | MIT | https://github.com/plotly/plotly.js |

PyQt6 and PyMuPDF are dual-license components with material distribution
obligations. The release owner must record the applicable license basis and
legal/compliance approval for the exact artifact before promotion. This notice
does not select a license or waive those obligations.

## Native Rust extensions

Metroliza builds five Rust extensions for CMM parsing, chart rendering, grouped
statistics, comparison statistics, and distribution fitting. Their direct
dependencies include PyO3, numpy, rusqlite (bundled SQLite), rand, rand_distr,
statrs, and rayon. The exact resolved transitive crate versions, sources, and
declared license metadata are recorded in the build `260711` inventory linked
above. Preserve all license files emitted by Cargo/wheel tooling in the release
notice bundle.

## Release packaging obligations

- Ship or attach this notice with every distributed executable, installer, ZIP,
  or other release artifact.
- Preserve RapidOCR's Apache-2.0 license notice and the model copyright
  attribution above.
- Preserve ONNX Runtime, OpenVINO, OpenCV, NumPy, hexafe-plotstats, Oznak,
  PyQt6/Qt, PyMuPDF, cryptography, Google auth packages, Matplotlib, Pillow,
  SciPy, seaborn, PyYAML, XlsxWriter, pandas, SQLAlchemy, Plotly.js, openpyxl,
  et-xmlfile, and xlrd license/metadata files when the packaging tool can
  include distribution metadata.
- Ship the generated Python/Rust inventory and `NOTICE_MANIFEST.json` sidecar;
  do not distribute an executable/archive without its matching notice bundle.
- If RapidOCR, OCR model files, ONNX Runtime, OpenVINO, OpenCV, NumPy, Excel
  reader packages, or their pinned versions change, update this file and rerun
  the packaging validation tests.
- Do not publish a release artifact produced with an unsafe OCR packaging
  override such as `-AllowMissingHeaderOcrBuild`.

Commercial distribution note: permissive dependencies still require their
license and notice obligations. PyQt6/Qt and PyMuPDF require a separate,
explicit license-basis review for this application's distribution model.
