# Keyboard commands

The active window owns its commands. Primary keys appear beside the command or in
its search placeholder. Tooltips also keep any existing Alt mnemonic as a secondary
key. A key uses the same visible, enabled button and confirmation as a click; it
does not enable an unavailable operation. Close/Cancel keep existing dirty-work and
worker guards. Ctrl+Shift+S requests Stop only where a cancellable operation exists.

Ctrl+A/C/X/V/Z/Y keep normal text editing. Ordinary letters and Polish AltGr input
remain text in editors. The only bare E/R commands are in the explicitly focused
column/member lists described below. Holding a primary key does not repeat a
mutation. A modal child owns its keys; its Save, Apply or Close never invokes the
parent's identically bound Generate, Export or Close. Return focus to the parent
to use its commands again. Short file pickers keep their normal modality.

## Main window and Reports

| Action | Primary | Context, hint and availability |
| --- | --- | --- |
| Home / Reports / CSV Summary / Industrial Data / Realtime | Ctrl+1 / Ctrl+2 / Ctrl+3 / Ctrl+4 / Ctrl+5 | Navigation labels; resumes the existing owned window |
| Parser Profiles / Tools | Ctrl+Shift+F / Ctrl+Shift+T | Navigation labels |
| Database | Ctrl+D | Reports: exact Select/create database button, with its source/busy guards; elsewhere: Open existing database |
| Reports source | Ctrl+Shift+D | Exact Reports source chooser; disabled while busy |
| Review / Import selected / Export workbook | Ctrl+R / Ctrl+S / Ctrl+E | Actual enabled Reports command; fresh Review is required after import |
| Search / Cancel operation | Ctrl+F / Ctrl+Shift+S | Search belongs to visible Reports; Cancel uses the actual active operation |
| Manual | F1 | Manual for the active window |

Ctrl+O remains a secondary Open existing database route and Ctrl+I a secondary
Import selected route. Compact navigation arrows, typing and wheel movement only
preview a choice; Enter/keypad Enter or a mouse choice opens it. Reports selection
and source/database controls are unavailable while an import is queued for metadata.
The submitted selection remains fixed for that operation.

## CSV Summary and Export workbook

| Action | CSV Summary | Export workbook | Availability and visible hint |
| --- | --- | --- | --- |
| Source / database | Ctrl+D | Ctrl+D | Browse source / database; existing source and busy guards |
| Load metrics | Ctrl+R | — | Load/refresh caption follows the actual CSV source |
| Choose metrics / filter | Ctrl+F | Ctrl+F | CSV: Choose metrics; Export: Filter |
| Edit CSV filter | Ctrl+Shift+F | — | Filter button; only when source supports it |
| Groups | Ctrl+G | Ctrl+G | Edit groups / Group data |
| Metric limits | Ctrl+Shift+G | — | Edit limits; discovered metrics required |
| Dashboard path | Ctrl+Shift+D | — | Browse dashboard |
| Workbook path | Ctrl+Shift+E | Ctrl+Shift+E | Browse workbook |
| Clear filter / groups | Ctrl+Shift+R / Ctrl+Shift+Q | Ctrl+Shift+R / Ctrl+Shift+Q | Exact Clear buttons; current source state remains authoritative |
| Generate / Stop / Close | Ctrl+S / Ctrl+Shift+S / Ctrl+W | Ctrl+S / Ctrl+Shift+S / Ctrl+W | Generate requires valid output/readiness; Stop requests existing cancellation |
| Use metrics or limits / Cancel | Ctrl+S / Ctrl+W | — | Active metric/limit child only; limits still validate before acceptance |

In the metrics child Ctrl+F selects Search metrics. Select all/Clear remain ordinary
buttons reachable by Tab and Space. Existing Alt mnemonics stay secondary:
CSV B/M/O/F/E/L/T/G/R/W/Y/C for source/load/metrics/filter/groups/limits/clear filter/
clear groups/dashboard/workbook/generate/close; Export B/R/E/D/F/G/X/C for database/
workbook/filter/groups/clear filter/clear groups/generate/close. The visible Ctrl
caption is the primary reference when context changes a button's wording.

## Filter and grouping children

| Context and action | Primary | Hint, availability and secondary keys |
| --- | --- | --- |
| Reports/CSV filter: Search / Apply / Reset draft / Cancel | Ctrl+F / Ctrl+S / Ctrl+Shift+R / Ctrl+W | Search placeholder and buttons; validation/discard guards retained |
| CSV filter/grouping: Add / Remove selected column | Ctrl+E / Ctrl+Shift+E | Button below its list; E only in available list, R only in selected list |
| CSV grouping: Remove selected members | Ctrl+D | Member button; R only in member list; Delete/Backspace stay secondary where supported |
| CSV grouping: Assign all matching / Clear selection | Ctrl+R / Ctrl+Q | Actual matching-row buttons; Ctrl+Q has no MainWindow Quit binding |
| Reports grouping: Remove selected members | Ctrl+D | Actual selected-member button; existing Delete/Backspace retained |
| Reports/CSV grouping: Create or assign selected / Rename / Delete group | Ctrl+G / Ctrl+Shift+G / Ctrl+Shift+D | Selection and protected/default-group guards retained |
| Reports/CSV grouping: Use / Reset changes / Cancel | Ctrl+S / Ctrl+Shift+R / Ctrl+W | Actual draft acceptance/reset/discard guards |
| Reports/CSV grouping: Search | Ctrl+F | Focused pane's visible search |

Search hides choices only; hidden selections and draft conditions remain. In filters,
Apply commits the draft and Cancel discards it only after the existing confirmation.
Grouping Reset changes retains its existing meaning; it does not silently accept a
draft or delete source rows. Legacy Alt remains secondary: CSV grouping F/A/R/D/L/U/S/C
for assign all/create/rename/delete/clear selection/use/reset/cancel; Reports grouping
A/R/D/M/U/S/C for create/rename/delete/remove members/use/reset/cancel. Filter apply/
reset/cancel keep Alt+A/S/C, CSV filter Alt+A/R/C. Date Today/Beginning and NOK shortcuts,
CSV Clear columns/Clear selection, and clear-search/value/expression conveniences
remain Tab/Space controls with their existing optional mnemonics. These less frequent
controls have no new window-wide letter binding.

## Modify database and Characteristic Name Matching

| Action | Modify database | Name Matching | Hint and guard |
| --- | --- | --- | --- |
| Search | Ctrl+F | Ctrl+F | Visible pane's search |
| Apply pending edits / Export CSV | Ctrl+S | Ctrl+S | Distinct visible labels: Apply versus Export CSV |
| Close | Ctrl+W | Ctrl+W | Existing dirty-work/CSV-operation guard; Esc also retains its existing meaning |
| Add manually / Edit selected | — | Ctrl+E / Ctrl+Shift+E | Actual selected match and validation guards |
| Browse database | Ctrl+D | Ctrl+D | Mapping database transition guards retained |
| Add from selected / Delete | — | Ctrl+R / Ctrl+Shift+D | Actual selection and confirmation |
| Import CSV | — | Ctrl+Shift+R | Existing review/atomic import path |
| Save match / Cancel | — | Ctrl+S / Ctrl+W | Active Add/Edit child only |

Name Matching writes successful edits immediately. Export CSV does not mean Save a
draft. No Stop is offered for its atomic CSV commit; guarded Close can wait for the
operation. Modify database retains Alt+B/A/C as secondary browse/apply/close keys.

## Industrial Data and its children

| Active window and action | Primary | Hint and availability |
| --- | --- | --- |
| Industrial Data: Configure / Fetch / Analyze / Export / Close | Ctrl+D / Ctrl+R / Ctrl+S / Ctrl+E / Ctrl+W | Existing stage and cache/readiness buttons; remote failure does not discard cached rows |
| Fetch: Configure / Check access / Fetch / Fetch to CSV | Ctrl+D / Ctrl+R / Ctrl+S / Ctrl+Shift+E | Existing source/scope/access guards |
| Fetch: Stop / Close | Ctrl+Shift+S / Ctrl+W | Existing cancellation and worker ownership |
| Production sources: New / Browse YAML / Reload | Ctrl+D / Ctrl+Shift+D / Ctrl+R | Actual source form/file controls |
| Production sources: Save / Close | Ctrl+S / Ctrl+W | Save source is immediate; dirty form/close guard retained |
| SQL recipe: Open / Save / Preview / Close | Ctrl+D / Ctrl+S / Ctrl+R / Ctrl+W | Actual bounded preview and recipe handlers |
| Industrial filter: Add / Apply / Reset / Cancel | Ctrl+E / Ctrl+S / Ctrl+Shift+R / Ctrl+W | Actual row and validation/discard guards |
| Industrial grouping: Search / Use / Reset / Cancel | Ctrl+F / Ctrl+S / Ctrl+Shift+R / Ctrl+W | Search fields placeholder; draft selection/discard guards |
| Industrial export: Workbook / Filter / Groups | Ctrl+Shift+E / Ctrl+F / Ctrl+G | Actual output/filter/group controls |
| Industrial export: Clear filter / Clear groups | Ctrl+Shift+R / Ctrl+Shift+Q | Existing Clear buttons |
| Industrial export: Generate / Stop / Close | Ctrl+S / Ctrl+Shift+S / Ctrl+W | Existing export admission; progress child owns Stop while modal, requests cancellation and waits for writer |

The progress title also shows Ctrl+Shift+S. A completed or idle operation is not
cancelled again. These nested source/SQL/filter/group/export commands have no new
Alt-only primary; any existing menu/navigation mnemonics remain secondary.

## Parser Profiles, Realtime and generated HTML

The already accepted maps remain in their modules. [Parser Profiles](parser_profiles.md)
uses Ctrl+D Prepare, Ctrl+R Check, Ctrl+Shift+R Validate, Ctrl+E Install/Enable,
Ctrl+Shift+E Disable, Ctrl+Shift+D Manage, Ctrl+Shift+A Add, Ctrl+S the named next
Add/Manage action, Ctrl+W Close, Ctrl+Shift+F Folder, Ctrl+Shift+C Copy path,
Ctrl+Shift+Q Diagnose and Ctrl+Shift+S Repair prompt. Each follows its visible tab,
selection, validation and ownership guard; Repair prompt is not Stop.

[Realtime](realtime_industrial_monitoring.md) keeps Ctrl+D Configure, Ctrl+R Monitor,
Ctrl+E Events, Ctrl+Shift+S Stop, Ctrl+Shift+R Poll, Ctrl+Shift+F Dashboard,
Ctrl+Shift+D Production sources, Ctrl+Shift+A Acknowledge, Ctrl+Shift+E Resolve,
Ctrl+Shift+Q False positive, Ctrl+W Close and contextual Ctrl+S Start/Save/Refresh.
Tab/selection/busy guards remain authoritative. These files are owned and reviewed
separately from this command completion.

Generated HTML keeps the browser's Ctrl+F/W/R/T. Its existing focused-component
keys do not introduce global letter commands. Advanced panels and visual presets
remain Tab/Space controls with secondary Alt+A/Alt+N where already provided; no
claim is made that every legacy mnemonic has been replaced.
