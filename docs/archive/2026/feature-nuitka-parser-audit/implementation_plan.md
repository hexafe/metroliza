# Implementation plan

## Goal
Restore fail-closed packaged PDF parsing guarantees so refactors cannot silently produce a broken packaged app.

## Plan
1. Add a shared PDF backend/runtime validation helper for backend detection and packaged smoke assertions.
2. Refactor parser/backend loading and legacy shim behavior to reduce bundler blind spots.
3. Harden Nuitka gating with explicit unsafe override naming and post-build validation.
4. Add PyInstaller parity preservation for PyMuPDF modules, data, and native libraries.
5. Add packaged parser smoke execution in CI using a real PDF fixture and a non-interactive app smoke entrypoint.
6. Add regression tests for backend resolution, packaging validation helpers, CI/workflow semantics, and runtime smoke helpers.
7. Update audit docs/checklist to reflect final state.

## Risks
- Packaging metadata/report formats can vary across tool versions, so report validation must be resilient.
- Packaged parser smoke must avoid interactive UI paths.
- Changes must preserve legacy import compatibility and native parser fallback behavior.
