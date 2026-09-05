# Native prototype validation

## Preserved checkpoint

`01ec4e9214204b420bce0e364258ecc6472db901` was committed at
2026-09-04 19:52:59 UTC, roughly 15 minutes after the first pass began. It contains
the runnable native UI and 14 passing interaction tests. Later scoped corrections
add filtered keyboard, outcome-context and execute-time change regressions.

## Reproduce

Use the existing PyQt6 environment; no dependency files were changed or packages installed.
From `prototypes/ui_workbench/`:

```sh
python app.py
python -m unittest -v test_workbench
python -m ruff check --isolated --select E4,E7,E9,F,B .
python -m ruff format --check .
python -m compileall -q .
python capture_evidence.py
QT_SCALE_FACTOR=1.25 python capture_evidence.py
QT_SCALE_FACTOR=1.5 python capture_evidence.py
```

The verified interpreter on the development host is
`/tmp/metroliza-1019.6sg67g/venv/bin/python` (Python 3.14.7, PyQt6/Qt 6.6.1).
The test runner forces Qt offscreen and does not load the production pytest configuration.

## Observed evidence

- 19 prototype interaction tests passed, including real QTest keyboard events and Tab/Shift+Tab escape from the table,
  selecting exactly 2 of 5 reports, filtering/sorting, hidden-selection confirmation,
  all context invalidations, destination-only verification and explicit repair,
  immutable task navigation, close guard, source drift and disjoint partial cancellation.
- Native screenshots: Qt Fusion widgets rendered offscreen, not browser images.
  Both themes at 1024×700, 1280×800 and 1600×1000 logical pixels.
- Additional Qt renders at actual device pixel ratios 1.25 and 1.5. All primary
  controls' full rectangles were inside the window in all 18 theme/viewport/scale combinations.
  This is Qt layout/DPI evidence, not packaged Windows or physical monitor validation.
- Python socket creation and SQLite connection probes were rejected by the runtime
  audit guard **before connection**. Static AST checks reject production, database,
  networking and WebEngine imports in the runtime modules. No production modules loaded.
- Only generated synthetic fixtures and native images are used. No report scanning,
  real database, OCR, production credentials or runtime network is enabled.
- Production suite and production CI: **NOT RUN**. No workflow dispatch/rerun/cancel.

The guard and static import check are prototype safeguards, not an OS network sandbox.
GitHub access used to prepare this design branch is separate from the prototype runtime.

## Actual 10,000-row observations

Measured on Linux 7.1.9 Arch x86_64/glibc 2.44, Python 3.14.7, Qt 6.6.1 Fusion offscreen.
Ten fixed search queries per run. Timing includes synchronous UI updates and one event
drain; it does not include real scanning/parsing/persistence. No performance target is claimed.

| Scale | Synthetic review/display | Filter median / max | Descending name sort | Five scroll jumps |
| --- | ---: | ---: | ---: | ---: |
| 100% | 434.01 ms | 41.28 / 354.12 ms | 475.24 ms | 16.10 ms |
| 125% | 415.45 ms | 42.89 / 368.45 ms | 557.93 ms | 18.05 ms |
| 150% | 408.01 ms | 42.61 / 342.19 ms | 661.30 ms | 19.21 ms |

Source measurements with individual samples and timestamps:
[100%](evidence/observations.json), [125%](evidence/scale-125/observations.json),
[150%](evidence/scale-15/observations.json).
Filtering to narrow subsets is quick; expanding back to all rows and sorting still
pause noticeably. Background preparation/debounced filtering can be evaluated in #1015;
these measurements do not justify a production throughput claim.

## Visual inspection and corrections

Actual images were opened and inspected. Corrected: column widths lost after theme
switch, clipped compact navigation, misleading 100% cancellation, and wrong-context
task outcomes in a newly selected destination. Independent read-only review found
hidden-row Space selection and drift evidence contradictions; both received regressions.
Two read-only specialists were used, with one writer and no recursive delegation.

Screenshots:

- [Reports dark, 1280×800](evidence/reports-dark-1280x800.png)
- [Reports light, 1600×1000](evidence/reports-light-1600x1000.png)
- [Compact light, 1024×700](evidence/reports-light-1024x700.png)
- [125% compact dark](evidence/scale-125/reports-dark-1024x700.png)
- [150% compact light](evidence/scale-15/reports-light-1024x700.png)
- [Overview](evidence/overview-dark.png)
- [Destination matches only](evidence/destination-only.png)
- [Exact scope and repair confirmation](evidence/scope-confirmation.png)
- [Navigation during execution](evidence/task-survives-navigation.png)
- [Partial cancellation](evidence/partial-cancellation.png)
- [Separate failed/changed/cancelled results](evidence/partial-failure-changed-cancelled.png)
- [Successful selected subset](evidence/successful-subset.png)
- [Empty source](evidence/empty-source.png), [missing source](evidence/missing-source.png),
  [pending review](evidence/pending-review.png)
- [10,000-row model](evidence/reports-10000.png)

## Integration snapshot and remote boundary

The pinned develop baseline stayed `dd0f964cbcf8cd3382fd68dd528b22c1a3b5d7be`
when checked before handoff. PR #1021 advanced independently during this experiment;
its 20:01 UTC observed head was `0c62caf496bbfc4dfffa6f7421ce7b69c3a1e44e`, Draft/open.
This packet did not change it or import its code. PR #1017 was still Draft/open at
`cc734595d5965869bfd69c1cf897133445986832` and was not modified.
Future integration must refresh those backend contracts. This branch only references #1023.
