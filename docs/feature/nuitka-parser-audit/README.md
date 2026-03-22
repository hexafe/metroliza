# Nuitka parser audit

## Scope
- Audit packaged PDF parsing as a release-blocking core product capability.
- Focus on Nuitka and PyInstaller preservation of PyMuPDF and parser runtime dependencies.
- Cover parser refactor effects in `modules/cmm_report_parser.py` and `modules/report_parser_factory.py`.
- Cover CI/package smoke evidence for real PDF parsing, not startup-only checks.

## Owner / role
- Owner: Codex implementation audit workspace.
- Intended reviewers: release engineer, packaging maintainer, parser maintainer.

## Assumptions
- PDF report parsing is mandatory product functionality in packaged builds.
- PyMuPDF support in packaged builds is mandatory and non-optional.
- A packaged EXE that launches but cannot parse PDF reports is a broken release artifact.
- Native parser fallback behavior must remain intact, but it does not replace PyMuPDF for opening PDF reports.

## Mandatory packaged-PDF statement
Packaged PDF parsing is mandatory. Any build pipeline that can emit a packaged app without a usable PyMuPDF-backed PDF parser is defective and must fail closed by default.

## Exit criteria
- Nuitka build fails by default when PyMuPDF is missing or omitted from the packaged artifact.
- Parser backend loading remains compatible with both `pymupdf` and `fitz` while being explicit enough for bundler preservation.
- PyInstaller and Nuitka configuration explicitly preserve PDF parser dependencies.
- CI/package smoke coverage validates parsing of a real PDF fixture from a packaged artifact.
- Audit findings clearly separate root causes, contributing factors, missing safeguards, and false assumptions.

## Root-cause summary
### Direct root causes
1. Parser backend loading used alias discovery through `importlib` (`pymupdf` vs `fitz`) inside `modules/cmm_report_parser.py`, which weakens static dependency discovery for bundlers.
2. The legacy `modules/CMMReportParser.py` shim used `importlib.util.spec_from_file_location(...)` to load the canonical parser module dynamically, creating an additional non-standard import path before shim removal.
3. `packaging/metroliza_onefile.spec` preserved the optional native parser extension but did not explicitly preserve PyMuPDF hidden imports, package data, or dynamic libraries.
4. `packaging/build_nuitka.ps1` gated only on build-environment importability and did not validate the built artifact/report to ensure PyMuPDF actually made it into the package.

### Contributing factors
- The parser/plugin refactor increased indirection around parser module loading and backend alias resolution.
- Packaging smoke coverage in CI only validated startup and artifact existence, not parser execution against a real PDF.
- Documentation described PyMuPDF as required for packaged builds, but automation did not fully enforce that contract.

### Missing safeguards
- No automated packaged-PDF smoke path in CI.
- No post-build Nuitka report validation.
- No PyInstaller parity check for PyMuPDF preservation.

### False assumptions
- Successful executable generation was implicitly treated as sufficient release evidence.
- Build-environment importability was treated as equivalent to packaged-artifact usability.
- Startup-only smoke was treated as meaningful packaging validation for a parser-centric desktop app.

## Recommended fix order
1. Fail closed in the Nuitka build script when PyMuPDF is unavailable, unless an explicitly unsafe override is used.
2. Remove bundler-hostile parser/shim import patterns and centralize PDF backend resolution.
3. Add explicit PyMuPDF preservation to PyInstaller and post-build validation to Nuitka.
4. Add packaged parser smoke coverage using a real PDF fixture.
5. Keep docs/checklists aligned with the stricter packaged-parser contract.
