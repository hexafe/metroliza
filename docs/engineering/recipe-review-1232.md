# Recipe flow review disposition

The independent full review of `b4dd44a1` requested four P2 corrections and found
no P0/P1 or demonstrated data-loss/privacy defect. The source review did not
execute tests, Windows, CI or packaged journeys. The final delta and machine
receipts are separate evidence.

The first delta on `0310983e` closed F1–F4 and found no new P0/P1/P2. Its trusted
policy loading was not confirmed, so the source gate remains incomplete until
the bounded policy rebind described in the delivery packet. Final follow-up also
guards output paths when the input is a filesystem root and narrows retained
Windows artifacts to receipts, screenshots and synthetic business outputs.

Hosted validation found two further concrete blockers: an optional tabular XLSX
was absent from the output family and could alias its source; the new Help manual
was absent from the old immutable documentation commit. The final correction
uses one effective analytics output-family resolver before consent/effects and
repins documentation to a retained commit containing all linked manuals. These
changes require their own bounded delta and exact-head CI before merge.

Subsequent hosted checks require safe XML parsing of qualification workbooks and
current-revision favorite launches. The grouped correction uses pinned
`defusedxml` (including hostile-entity controls for every parsed workbook part)
and removes captured saved snapshots from favorite launch callbacks.

Later service findings cover nonempty analytics asset replacement and composite
group-label collisions. Corrections must allocate safe render generations without
discarding the prior complete dashboard, and preserve distinct normalized grouping
tuples in the native group assignment. Both require behavioral regression controls
and a bounded delta before the final hosted qualification.

## Required corrections

- **Group-analysis parity:** portable grouping resolves Standard analysis and an
  explicit HTML step, preserving the remaining native settings. The independent
  OOXML oracle checks filtered measurement values, excluded dates, group counts,
  group means and actual analysis/plot sheets.
- **Output family:** resolve the actual suffix before deriving the database and
  checking aliases/collisions. The same resolved targets are exported and verified.
- **New-copy preview:** release the old preview resources, publish the new family
  and pause for confirmation before scanning or writing. UI renders the resolved
  database, output and assets, including an explicit existing input database.
- **Large-import receipts:** operational counts retain their exact nonnegative
  values. Safe diagnostic projection bounds them with explicit truncation flags.

Grouped follow-up also addresses cancellation admission/record races, current
database ownership at every entry point, excluded-file warnings and actionable
source-change recovery. Whole-flow states now use the existing managed wire with
closed state codes, actual runtime UUIDs and no private configuration.

## Bounded remaining observations

These were non-blocking review advice, rather than demonstrated harmful triggers.
They retain their original owning issues and do not imply those issues are closed.

| Observation | Owner / disposition |
|---|---|
| One malformed/newer private JSON makes the current catalog fall back to built-ins | #1233: diagnosed safely; per-file catalog isolation remains a resilience improvement. Files are preserved. |
| Catalog searches reread a bounded private catalog on the GUI thread | #1236: at most 256 bounded definitions; caching is a responsiveness improvement, not a source-data scan. |
| Analytics diagnostic messages may include informational warnings | #1238: assess against actual module outcomes before changing partial semantics; no demonstrated false-success case was found. |
| Manual tabular row membership is private and tied to the source signature | #1238: incompatible/stale source is rejected; portable rules are required for another source. No implicit membership transfer. |

Actual packaged Windows identity, screenshots at three scales and owned-process
cleanup are checked by the qualification driver. User keyboard/AltGr judgement
and separate PO acceptance remain distinct from machine qualification. Merge into
`dev` was expressly requested by PO; release/tag and epic acceptance remain separate.
