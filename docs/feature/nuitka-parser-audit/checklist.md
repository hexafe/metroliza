# Checklist

## Mandatory release contract
- [x] Packaged PDF parsing is documented as mandatory.
- [x] Nuitka fails closed when PyMuPDF is absent from the environment or artifact.
- [x] PyInstaller explicitly preserves PyMuPDF runtime dependencies.
- [x] Packaged parser smoke uses a real PDF fixture.
- [x] CI fails packaged smoke when PDF parsing is broken.

## Audit output completeness
- [x] Root causes separated from contributing factors.
- [x] Missing safeguards identified.
- [x] False assumptions identified.
- [x] Fix order recorded and aligned with implementation.

## Validation
- [x] Targeted tests added/updated.
- [x] Relevant checks executed.
- [x] Docs updated to match implemented behavior.
