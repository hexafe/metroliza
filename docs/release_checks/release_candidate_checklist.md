# Release candidate checklist

Use this as the single source of truth for RC readiness and sign-off.

## 1) Version bump and metadata sync

- [ ] `VersionDate.py` version/build/date values are updated for this RC.
- [ ] `CHANGELOG.md` includes the user-facing notes for this RC.
- [ ] `README.md` **Release highlights** section reflects the current RC/release line.
- [ ] Version/build/date text is consistent across all three files.

## 2) Mandatory automated checks

Run and record the results of all baseline checks:

```bash
python -m compileall .
ruff check .
PYTHONPATH=. python -m unittest discover -s tests -v
```

- [ ] Compile check passed.
- [ ] Lint check passed.
- [ ] Unit test suite passed.

## 3) Google conversion smoke policy + evidence location

- [ ] Run the release-gated Google conversion smoke check according to the runbook:
  [`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md).
- [ ] Follow the required release policy (`warnings=()` on success, `.xlsx` fallback preserved and documented).
- [ ] Record evidence for each RC run in:
  [`docs/release_checks/google_conversion_smoke.md`](google_conversion_smoke.md).

## 4) Packaging validation

### Build commands

```bash
pyinstaller metroliza_onefile.spec
```

```powershell
python -m nuitka metroliza.py `
  --onefile `
  --windows-console-mode=disable `
  --enable-plugin=pyqt6 `
  --windows-icon-from-ico=metroliza_icon2.ico `
  --output-filename=metroliza.exe `
  --assume-yes-for-downloads `
  --remove-output `
  --jobs=%NUMBER_OF_PROCESSORS%
```

### Artifact sanity checks

- [ ] PyInstaller output exists under `dist/` and launches.
- [ ] Nuitka output executable exists and launches on a clean/sandbox target environment.
- [ ] Basic startup flow works (open app, load a representative input, generate an export).
- [ ] Produced artifacts are named/versioned as expected for RC distribution.

## 5) RC sign-off

| Item | Value |
| --- | --- |
| RC owner |  |
| Sign-off date |  |
| Decision | Go / No-Go |
| Notes |  |

