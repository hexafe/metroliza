# #981 — bounded local XLSX/HTML output-safety audit

## Wynik i granica dowodów

**STOP — potwierdzono P1: importowany nagłówek pomiaru staje się odwołaniem
formułowym w tytule i nazwie serii wykresu XLSX.** Rzeczywisty eksporter zwrócił
`completed`, a cache obu nazw zawiera inny tekst niż importowany nagłówek.
Ochrona literalnych komórek nie obejmuje użytego API nazw wykresów.
Minimalny dowód zawiera wyłącznie nieszkodliwe odwołanie lokalne; nie uruchamiano
Excela, kodu ani odwołań zewnętrznych. Nie wykazano wykonania niebezpiecznej
formuły, wycieku danych ani konkretnego zachowania interfejsu Excela.

Pozostałe próby wykonane przed STOP: generator XLSX zachował tekst komórek i nagłówków; generator
HTML nie wykazał przełamania badanych granic elementów, atrybutów JSON i osadzonej
konfiguracji JS. Powtarzane znaczniki potwierdzają tylko obecność zbiorczą; nie
potwierdzają zachowania każdego pola. Tekstu URL w referencji i metadanych nie sprawdzono.
Poprzedni kompletny plik i zasoby HTML przetrwały wszystkie sprawdzone błędy.
Kontrole negatywne potrafiły odrzucić celowo błędne, nieszkodliwe artefakty.

To dowód struktury wygenerowanych plików na Linuksie, **nie uruchomienia w Excelu
ani przeglądarce**. Interpretacja tekstu przez Plotly po otwarciu pliku, rzeczywiste
blokady plików Windows, przerwanie procesu i pełny przepływ Qt/DB pozostają otwarte.
Nie ma podstaw do ogłoszenia całego systemu eksportu bezpiecznym ani zamknięcia #981.
To checkpoint przerwanego audytu, nie zakończenie całego packetu.

## Identity, authority and ownership

- Agent: `AUDIT-981-OUTPUT-SAFETY`; parent: `ORCH-METROLIZA`.
- STOP recorded `2026-09-10 14:27:19 UTC` after structural corroboration of
  a supported chart-name formula boundary. Adjacent runtime probing stopped;
  subsequent work only preserves/reviews the minimal finding and checkpoint.
- Session: `ORCH-981-OUTPUT-SAFETY-20260910-1`; manual START
  `2026-09-10 14:07:24 UTC`, maximum stop `2026-09-10 17:07:24 UTC`.
- [Authority](https://github.com/hexafe/metroliza/issues/981#issuecomment-5619574205),
  Issue body and later activity read before worktree creation. At that read there
  was no later #981 amendment. [Canonical checkpoint](https://github.com/hexafe/metroliza/issues/981#issuecomment-5620071004)
  owns delivery head/tree, review, CI and subsequent session receipts.
- Audited immutable source and verified live `develop` at START:
  `b645164e83898df69335713f808189de6cc1fc31`.
  Tree: `46fd6819d23fbabe19fda7b90ba9ac24e5bd6110`.
- Separate worktree and branch: `research/981-output-publication-audit`; target
  `develop`. Existing OCR worktree remained clean at `337128c310f9b64281f12011f704304754c738dd`.
  Numerical and left-lane work were neither reused nor changed.
- Whole-PR class CRITICAL / MILESTONE. Requested coordinator Sol/Ultra;
  observed model/reasoning **not visible**. One read-only reviewer explicitly
  routed `gpt-5.6-sol` / `high`; actual runtime model/reasoning **not visible**.
  Selection parameters are observable, runtime identity is not.
- Frozen four-path write set: this report, [JSON evidence](../evidence/981-output-safety.json),
  [explicit driver](../../../../tests/audit_981_output_safety.py), and
  [assertion controls](../../../../tests/test_audit_981_output_safety.py).
  Added probes are justified by existing lifecycle tests' substituted writers and
  helper-only string checks. Source, existing tests, shared ledger, dependencies,
  workflows and release files remain read-only. The driver is not default pytest
  discovery; its small assertion test invokes it explicitly in private fixtures.

## Existing contracts and prior work

[#936](https://github.com/hexafe/metroliza/issues/936) requires imported text to
stay literal, while deliberately authored Metroliza formulas/navigation remain
valid. Source commit `808d802d00f6af023742c4cb9dfdbc867d7847a4` already introduced
the shared XLSX policy. This audit does not propose another sanitizer.
Dashboard generation staging already exists (`40ee797`, `9c30be8`, ancestors of
the audited source). [#937](https://github.com/hexafe/metroliza/issues/937) owns
offline dashboard acceptance; [#938](https://github.com/hexafe/metroliza/issues/938)
owns Google conversion/local fallback, which is outside this local-only slice.

The [#983 stop](https://github.com/hexafe/metroliza/issues/983#issuecomment-5451052780)
concerned persistent raw exception logging (#990), followed by #1011's structured
logging boundary. This audit does not resume that broad reconnaissance or claim
new global logging evidence. The selected lower-level generators propagate
exceptions to their caller; that is distinct from public/persistent diagnostics.

Open and closed Issues were searched for formula, injection, atomic publication,
dashboard and workbook symptoms; #981/#983/#936/#938 and relevant source history
were read. Follow-up searches for `insert_measurement_chart`, chart names/titles/
series and formula symptoms found feature/audit coverage, but no focused duplicate
for the supported measurement-chart defect below. A focused finding is reported
only after independent corroboration and safe-publication review. Feature
acceptance checklists are not treated as proof of safety.

## Real source → transformations → artifact

The source review follows production entry points; execution starts at the
non-Qt serialization seam with synthetic row/section contracts. It does not run
the parser, SQL selection, analytics computation, Qt thread or UI completion code.

**XLSX route.** `ExportDataThread.export_filtered_data` (5804+) obtains a filtered
`RowTable`, then `write_data_to_excel` (5884+) applies `unique_sheet_name` and calls
`ExcelExportBackend.write_dataframe`. The probe uses the real
`build_export_dataframe` → `RowTable` transformation, followed by real
`ExcelExportBackend.run` → `_extract_table_columns_and_rows` →
`write_untrusted_xlsx_cell` → XlsxWriter → ZIP publication. The inert callback
supplies seven synthetic rows; no writer is substituted on the normal path.
Production formula helper `write_measurement_summary_rows` and the worksheet
navigation adapter supply explicitly authored positive controls. The probe's
fixed `Data` sheet does not exercise production sheet-name collision logic.

**HTML route.** `ExportDataThread._begin_html_dashboard_section` and
`_attach_html_dashboard_chart` assemble section text and chart payloads.
`run` (4838, 4927) checks backend planning outcome before
`_write_html_dashboard_if_requested` (3737+) calls the real
`write_export_html_dashboard`. The inert planning callback preserves this
ordering; the real publisher generates a distribution and histogram from
synthetic three-value payloads. Valid 2×2 PNGs are supplied as snapshot inputs:
snapshot rendering itself was not executed. The publisher normalizes metadata,
builds Plotly specifications and preview labels, escapes output contexts, copies
the bundled runtime, writes a private generation and promotes the HTML.

| Input / boundary | Transformation and actual sink | Existing protection | Executed disposition |
| --- | --- | --- | --- |
| XLSX header and string cells: formula-like text, URL, quotes, Unicode, HTML delimiters | `RowTable.iter_rows` → backend header/cell writes → shared strings + sheet cells | `write_string`; `strings_to_formulas=False`; `strings_to_urls=False` | ACCEPTED CONTRACT: 8 exact literal cells, native synthetic numeric cells retained |
| Deliberately authored XLSX formula and navigation | real summary-row helper → `write_formula`; adapter → `write_url` | explicit writer APIs, separate from imported values | ACCEPTED CONTRACT: exactly `D2=SUM(B2:B8)`, one internal E2 link; no external relationship |
| Imported measurement header/axis → chart title and series name | real `build_measurement_export_dataframe` → `insert_measurement_chart` → XlsxWriter name processing → chart `strRef/f` | workbook string policy does not govern chart `name` interpretation | CONFIRMED DEFECT F981-01: two imported name formulas; completed export; wrong cached label |
| HTML header, subtitle, reference, metadata and annotation | normalization → `_render_section`, detail cards, attributes/text | `html.escape`; fixed section IDs; image-name slugification | TEST GAP for per-field text parity: repeated sentinels only establish aggregate presence; URL reference/metadata value unasserted. No fixture-created element or event attribute observed |
| Distribution group/series label and chart title/axes | chart spec → `_render_plotly_shell` → `data-plotly-spec-*` | JSON encoding followed by attribute escaping | ACCEPTED CONTRACT only for parseable serialized attributes and aggregate sentinel presence. Each title/axis/group/annotation's exact value NOT TESTED; browser interpretation NOT TESTED |
| Derived preview label | `_dashboard_visual_preview_labels_from_manifest` → inline configuration | JSON encoding plus `</` escaping in `dashboard_visual_runtime_config_json` | ACCEPTED CONTRACT only for parseable embedded JSON containing a reused sentinel; exact source-field-to-preview mapping NOT TESTED; no extra script element |
| Synthetic non-export dictionary keys and unused context credential | ignored section/payload `credentials`, inert workbook context attribute | explicit selected fields, no generic object dump | ACCEPTED CONTRACT for these schema-negative fixtures only; real credential-loading flow NOT TESTED |
| Synthetic workbook parent path | `excel_file` → basename-only manifest | `Path(...).name` | ACCEPTED CONTRACT: parent marker absent. Per-field metadata preservation NOT TESTED |
| Hidden/package metadata and resources | every XLSX member; HTML and referenced assets | structural inspection independent of serializer | ACCEPTED CONTRACT for fixture: one visible sheet, no comments/external relations; forbidden markers absent |
| Exception output | injected exception → lower API caller; captured stdout/stderr | caller owns error handling | ACCEPTED CONTRACT: marker propagates in internal exception; no captured stream/artifact marker. Rollback-builder runs captured zero characters; default-enabled run captured 414 stderr characters whose content was not retained. Persistent logging/UI NOT TESTED |
| Offline resources | emitted non-anchor `src`/`href` → relative files | bundled local Plotly, generated PNGs | ACCEPTED CONTRACT for static references: assets exist, PNGs decode, no automatic external resource attribute |

The last row does **not** establish zero browser network requests. Source search
found no `fetch`, XHR, WebSocket or CSS `url(...)` in the four inspected project
shell/control/publisher/navigation modules. Bundled Plotly contains capabilities
outside the selected chart types; its runtime network behavior and user actions
were not executed. No automatic URL-valued resource attribute was observed. The selected URL's
literal value was not asserted, so its preservation as data is NOT TESTED. The explicit internal workbook link remains a legitimate positive control.

## Publication and failure evidence

Each row below ran with a missing target and with a previously generated,
structurally checked target on task-owned paths containing spaces and Unicode.
Initial local receipts hashed files (including HTML generation assets), excluding
publication lock metadata; they did not detect empty generation-directory residue.
The corrected driver also records every directory with a trailing-slash marker.
Execution of that stronger oracle is a fresh hosted-CI gate, not a retroactive
claim about the initial 22 cases. New XLSX numeric fixture values differ from the
old generation, so replacement cannot pass by silently retaining the old file.
Returned path/outcome, target existence and staging residue are checked.

| Format / seam | Actual execution and injected fault | Observed result in both target states |
| --- | --- | --- |
| XLSX success | real table writes, workbook close, `os.replace` | completed; new valid workbook; no temporary files |
| XLSX cancel | real table writes and close, callback returns canceled | canceled; prior bytes preserved or target remains absent; temporary files removed |
| XLSX writer | exception after real row/formula/link writes | exception propagates; close notification runs; previous target preserved; temporary files removed |
| XLSX flush entry | real `Workbook.close` with `_store_workbook` entry raising `OSError` | real close wraps `FileCreateError`; no success; prior target preserved; temporary files removed |
| XLSX post-close | real close finishes, injected error immediately afterward | exception propagates; complete staging is not promoted; prior target preserved |
| XLSX promotion | real serialized/closed staging; replace seam raises | exception propagates; prior target preserved; temporary files removed |
| HTML success | real specs, PNG writes, runtime copy, HTML write and replace | new valid HTML + one asset generation; actual final path returned |
| HTML planning cancel | backend returns canceled; subsequent publisher not called | canceled planning; no publication; prior complete generation unchanged |
| HTML renderer | actual render completes in memory after asset writes, then seam raises | exception; old HTML and all referenced assets unchanged; new temporary files removed |
| HTML post-write finalization | actual `Path.write_text` writes/closes complete temp HTML, then raises | exception; no promotion; old generation unchanged; new temporary files removed |
| HTML promotion | real complete temp HTML/assets; replace seam raises | exception; old generation unchanged; new temporary files removed |

There are **22 cases per explicit driver run**. The in-repository supported
rollback builder (`METROLIZA_PLOTSTATS_EXPORT_CHARTS=0`) ran twice with byte-identical
normalized `facts.json`. A further run requested the default enabled Plotstats
route (`=1`) and passed the same 22 cases. Both use the real HTML publisher; this
does not assert every external adapter branch was selected or test PNG rendering.

Injected failures are simulated seams, not Windows file locks, actual disk
exhaustion, mid-write OS failure or power loss. HTML has no cancellation token at
this publisher entry; the planning-cancel test is not renderer cancellation.
XLSX `begin_workbook_close` callback failure and cleanup failure are unexecuted
boundaries, not corroborated product defects. No fsync/durability claim follows.

## Falsification, findings and next work

### F981-01 — imported measurement labels become chart formulas

**CONFIRMED DEFECT; provisional severity P1; high confidence in the structural
contract violation.** Execution/exfiltration consequences remain NOT TESTED,
not confirmed P0 claims. Authoritative focused Issue: [#1035](https://github.com/hexafe/metroliza/issues/1035).

- Exact source: `b645164e83898df69335713f808189de6cc1fc31`.
- Supported reachability: `export_query_service.build_measurement_export_dataframe`
  (71–87) derives `HEADER - AX` from imported `HEADER`/`AX`;
  `ExportDataThread.add_measurements_horizontal_sheet` groups that column
  (5078+) and passes the resulting header to `insert_measurement_chart` (5118+).
- Actual sink: [export_chart_writer.py](../../../../src/metroliza/charts/export_chart_writer.py),
  `build_measurement_chart_series_specs` (`name: header`),
  `build_measurement_chart_format_policy` (title name), and
  `insert_measurement_chart` (`add_series`, `set_title`). XlsxWriter 3.2.9's
  `Chart._process_names` treats sheet/cell-looking strings as name formulas;
  the workbook's string-cell options do not control this code.
- Minimal safe fixture: two synthetic HEADER/AX/MEAS rows; a local `Data!A1`-like
  header, ordinary axis; real row transformation, writer, chart helper, close and
  publication. No Qt, database, external path, DDE, macro or Excel execution.
- Expected: derived imported text remains a literal title/series name; only
  deliberately generated chart data ranges become formulas.
- Observed: outcome `completed`, valid ZIP, one `c:title/.../c:strRef/c:f` and one
  `c:ser/c:tx/c:strRef/c:f` exactly carrying the transformed imported header
  without its initial `=`. Each has cached value `HEADER`, rather than the
  imported label. Eight total chart formulas comprise those two name references
  plus six intended data-range references. Captured stderr: 0.
- The explicit `--chart-label-probe` returns **exit 1**, reports the finding and
  preserves safe facts. It is not xfailed/skipped or included among passing
  ordinary publication cases. Initial private corroboration observed the same
  two name references through the same real production helpers.
- Preconditions/impact: supported measurement chart export containing a
  reference-looking imported header. The persisted chart name is interpreted
  as a reference and has incorrect cached text. This compromises measurement
  identity and is serialized into formula-bearing chart XML; actual Excel rendering/
  evaluation and external-reference impact have not been established.
- Narrow future repair: secure imported names at the existing chart helper
  boundary, preserving intentionally authored data-range references. Add real
  package tests for both title and series names and innocent reference-looking
  strings. No algorithm, sheet schema or global sanitizer rewrite is needed.

The packet's potentially unsafe active-formula STOP clause applies to this
corroborated boundary crossing. Broad auditing stopped after minimal evidence;
the source remains unchanged. The external orchestrator owns a separate focused
fix/validation authority and any later manual audit resumption. No risk acceptance
or automatic restart is implied by preserving a Draft PR.

The separate assertion tests demonstrate rejection of: a benign `1+1` formula
inserted into an imported cell; a synthetic forbidden workbook property; a
truncated XLSX; an inert `application/json` script-boundary breakout; a forbidden
HTML comment; truncated HTML; missing offline assets; changed last-good hashes;
and a synthetic forbidden error-output marker. These artifacts deliberately
violate the oracle and are **not product findings**. No script, macro, DDE or
spreadsheet formula was executed. Additional chart-name controls reject title
and series name references while accepting deliberately authored data ranges.
Product source was not patched to create them.

| Item | Classification | Severity / confidence | Disposition and next gate |
| --- | --- | --- | --- |
| F981-01 supported measurement chart names | CONFIRMED DEFECT | provisional P1 / high structural confidence | STOP; focused Issue and separate repair authority before resumption |
| The 22 pre-STOP cases, excluding F981-01 | ACCEPTED CONTRACT only for the exact assertions described above | no defect severity / high for those exercised boundaries | File-only historical publication oracle; aggregate HTML text checks do not establish per-field parity |
| HTML field identity, URL reference/metadata value and preview mapping | TEST GAP | P3 evidence gap / high confidence that assertions are missing | Reused sentinels can mask one field's loss; require distinct sentinels and expected parsed contexts under later manual audit authority |
| Plotly rich-text/DOM interpretation after JSON decoding | TEST GAP | P3 evidence gap / high confidence that execution is missing | #937/#981 owner: isolated network-blocked browser run before runtime literal/offline acceptance; serializer unchanged |
| Actual Windows locks, mid-flush failure, close callbacks, cleanup failure and process interruption | TEST GAP | P3 evidence gap / high | #936/#981 owner: narrow native fault/cancellation evidence before platform publication acceptance; staging seam preserved |
| Non-export keys versus real credential sources and persistent error handling | TEST GAP | P3 evidence gap / high | #983 owner: connect actual configuration/error sources under separate authority; no invented privacy policy |
| Legacy Group Comparison chart-name candidate | HYPOTHESIS, unsupported path | severity unassigned / low exploitability confidence | Source can pass a name to XlsxWriter's chart API; module declares legacy/internal and live caller is commented out. Not reproduced, not a supported-path defect, no new Issue |

Independent review rejected the initial supported-path attribution of the legacy
candidate after checking reachability, then found the distinct supported
measurement-chart sink corroborated as F981-01. The first future repair is that
existing chart-name boundary. Browser execution, native publication faults and
remaining writer families follow under refreshed audit authority.

Unexercised families: full measurement-sheet/chart layout beyond the minimal name
reproduction, canonical Group Analysis
workbook and plot sheets, industrial exporters, industrial analytics workbook,
tabular analytics workbook, legacy Group Comparison, Google conversion, packaged
resource discovery, large limits and cross-renderer numerical parity. Source
inventory confirms shared XLSX options at the industrial/tabular workbook entry
points; a common option is not proof for their callers. Full #981/#917, #983,
#901/#1000 and coverage-ledger terminalization remain with their existing owners.

## Reproduction and validation receipts

Environment: existing read-only Linux Python 3.11.16 environment; XlsxWriter 3.2.9,
pytest 9.1.1, Ruff 0.15.10, Pillow 12.3.0, NumPy 2.4.6,
hexafe-plotstats 0.1.0a1, hexafe-groupstats 0.1.0rc3. No install or shared setting
change. Exact commands/exits and normalized facts are in the [JSON evidence](../evidence/981-output-safety.json).

From the audit checkout, with a compatible existing environment:

```bash
export PYTHONPATH=src:.
export PYTHONDONTWRITEBYTECODE=1
# Use a new task-owned directory; the driver refuses an existing output directory.
METROLIZA_PLOTSTATS_EXPORT_CHARTS=0 python tests/audit_981_output_safety.py --output-dir /tmp/audit981-new
# Minimal corroborated finding: expected exit 1 at the audited source.
python tests/audit_981_output_safety.py --chart-label-probe --output-dir /tmp/audit981-chart-new
python -m pytest -q -p no:cacheprovider tests/test_export_backends.py tests/test_audit_981_output_safety.py
python -m ruff check tests/audit_981_output_safety.py tests/test_audit_981_output_safety.py
python scripts/quality/validate_bug_sweep_coverage.py
python scripts/security_audit.py --secret-scan-only --base-ref b645164e83898df69335713f808189de6cc1fc31
git diff --check
```

Initial driver attempt rejected a wrongly specified assets directory with the
documented publisher validation; the harness was corrected to call
`resolve_html_dashboard_assets_dir`. This was not classified as a product defect
or a successful audit run. Later complete runs and their final-byte validation
are recorded separately.

Observed local receipts: 7 existing backend tests; 17 combined tests before the
chart finding was added; then 4 chart assertion controls passed (10 deselected)
during minimal STOP preservation. The current chart reproducer exits 1 and records
both incorrect cached labels. Ruff/compile/JSON, 5 documentation-link tests,
release hygiene, secret scan and diff checks passed. Ownership validation covers
953/953 paths with zero uncovered/duplicate owners; no shared ledger edit or
terminalization was needed. The prior 17-test result is historical, not a claim
that the final commit's entire test suite ran locally after STOP.

Final report/probe commit/tree, independent exact-candidate review, configured
GitHub review, exact-head CI and unresolved-thread count are recorded in the
canonical checkpoint and Draft PR; they cannot be self-referentially embedded in
the commit that they identify. A later changed head invalidates those receipts.
This delivery authorizes **Draft only**, never Ready, merge or Issue closure.
The shared coverage ledger remains nonterminal and unchanged.

## Artifact-only CI correction after initial checkpoint

Initial candidate `44daa6693a50c906db008d21d6d458cc9f9414ac` received clean
independent review, but its CI Security audit rejected the test helper's bare
module import. The test now uses the existing first-party `tests` namespace.
Scanner policy, workflow and product source are unchanged. The JSON retains
initial Python SHA-256 fingerprints under their initial commit identity and
records the corrected test's Git blob identity separately.

The local execution tool stopped creating processes before this correction,
including attempts outside the worktree with an explicit shell. The correction
was preserved as a normal child commit with a non-force GitHub Git API update
of the owned branch. The last locally verified checkout remains the initial
checkpoint; no reset or cleanup was attempted. Local execution of the changed
import is NOT TESTED. Fresh hosted CI and exact-candidate reviews are recorded
externally; old green results are not relabelled as current-head evidence.

## Audit-assertion correction from configured review

Configured review [P2](https://github.com/hexafe/metroliza/pull/1036#discussion_r3980316159)
identified that the initial file-only snapshot missed an empty abandoned HTML
generation directory. The driver now includes directory entries, and a synthetic
empty-generation negative control checks that the preservation assertion rejects
that state. Existing/missing-target comparisons consequently cover files and directory
residue. This corrects an audit false-negative; it is not evidence of a product
cleanup defect. Historical 22-case receipts retain their original hashes and
weaker oracle qualification. Local execution remains unavailable; current-byte
execution and review receipts belong to normal hosted CI and the canonical
checkpoint. No additional runtime audit or product repair was started.

## HTML evidence qualification from configured review

Configured review [P2](https://github.com/hexafe/metroliza/pull/1036#discussion_r3980374501)
showed that repeated `TEXT`/`BREAKOUT` sentinels can hide loss or corruption of an
individual HTML field, while `URL_TEXT` in reference/metadata is not asserted.
The prior per-field ACCEPTED CONTRACT wording was unsupported. The matrix, probe
receipt labels and JSON now classify field-level parity as **TEST GAP / NOT
TESTED**, and retain only the actual aggregate-presence, parseability and boundary
checks. This is a correction of an audit overclaim, not an HTML product defect.
The assertions have not been strengthened and the missing proof remains open.
A later manually authorized audit should use distinct field sentinels and exact
parsed-context assertions with field-removal negative controls. No new runtime
campaign is started after STOP to close this gap; old receipts are not relabelled
as field-level proof.
