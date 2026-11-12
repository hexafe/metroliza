# Parser Profiles

Open **Parser Profiles (Ctrl+Shift+F)**, also available through **Tools > Parser
profiles...**. Choose one task:

- **Manage installed profiles**: inspect the observed enabled/approval/integrity state,
  refresh the store, and explicitly enable or disable a selected profile through the
  existing lifecycle service. Enable is unavailable for a profile needing integrity
  or approval review; review/reinstall it through the normal validated route.
- **Add a new format**: prepare local materials, check/validate, then explicitly
  install/enable. The current stage, last observed results and next action stay below
  the scrolling form. **Next (Ctrl+S)** invokes the named existing action; it never
  approves a profile automatically.

A last observed PASS describes that check, not the current contents after external
edits. Install always rechecks the current profile, samples and expected-results
rows. Creating a handoff folder is preparation, never profile approval.

For normal users, a parser profile is a YAML setup file. It tells trusted
Metroliza code how to recognize a report, read the report identity, and extract
measurement rows. You should not need Python code, installers, package changes,
network access, shell commands, or database changes for the normal route.

## Before You Start

Collect these items before opening the dialog:

- 3 to 5 sample reports from the same supplier and the same visible layout.
- The exact values Metroliza should find in those reports.
- Supplier/template notes: language, report date format, decimal separator,
  units, and visible labels that appear in every report.
- Approval to share samples outside your machine if you will use an external
  LLM or reviewer.

If one supplier sends several different layouts, create one handoff folder per
layout. Do not mix the layouts in one profile.

## Open The Dialog

From the main window, select:

```text
Tools > Parser profiles...
```

Select **Add a new format**, then enter:

- **Profile id**: a short lowercase id such as `supplier_alpha`.
- **Display name**: a readable name such as `Supplier Alpha`.
- **Source format**: `pdf`, `excel`, or `csv`.

## Create Handoff Folder

Click **Create Handoff Folder**.

Metroliza creates a local workspace under the parser profile store. The folder
contains:

- `profile.yaml`: the YAML profile draft to complete.
- `samples/`: the place for sample reports.
- `expected_results.csv`: the manually checked values Metroliza must match.
- `llm_handoff.md`: instructions for a reviewer or LLM.
- `NON_TECHNICAL_STEPS.md`: a checklist version of the workflow.
- `contracts/` and `reference/contract_snippets.md`: the rules the reviewer or
  LLM must follow.
- `prompts/`: small prompts for LLM-assisted completion or repair.
- `responses/` and `artifacts/`: places to save answers, validation output, and
  repair prompts.

Metroliza does not send any report to an LLM. The dialog only prepares local
files that you can review and share through an approved workflow.

## Open Folder

Click **Open Folder** to open the handoff workspace in your file manager.

Then:

1. Put sample reports into `samples/`.
2. Fill `expected_results.csv` with every measurement row you checked by hand.
3. Keep supplier notes in the workspace.
4. If you use an LLM, send the prompt, samples, expected results, and contract
   snippets. Ask for a completed `profile.yaml` only.

Do not accept LLM output that adds Python files, network calls, package
installation, shell commands, database writes, or installer changes.

## Copy Path

Click **Copy Path** when you need to paste the folder location into a message,
file picker, terminal, or support ticket.

This copies the current handoff folder path. It does not copy the folder
contents.

## Check Package

Click **Check Package** before validation or before asking someone else to
review the folder.

This checks that the handoff package is self-contained. It looks for the
required files, expected-results table, sample folder, prompts, contract
snippets, and manifest. Save the result from `artifacts/` if you need to share
evidence with an operator.

If the package check reports missing files, add the missing samples or restore
the generated handoff files before continuing.

## Validate

Click **Validate** after `profile.yaml` and `expected_results.csv` are filled.

Validate checks the data-only YAML policy and structural parser contract. When
`expected_results.csv` references sample reports, it also checks those samples:
profile selection/probing, the parser contract, and parsed row counts and values
against their checked expected results. Unreferenced files in `samples/` are not
covered by that sample validation.

If there are no referenced samples, Validate performs structural contract checks
only. A header-only expected-results CSV with no samples can therefore **PASS**.
That result does not prove sample coverage or the presence of checked data rows.

Do not install a profile that fails validation. Before installing, supply the
current samples and checked expected-result rows required by Install below.

## Diagnose

**Diagnose** and **Repair Prompt** become available for an observed package,
validation or installation problem. Diagnose inspects the current sample/profile;
a missing sample is reported rather than treated as a passing selection.

Diagnose explains whether the sample matches the profile markers and shows the
probe/parse evidence saved under `artifacts/`. Use it to investigate a reported
selection/validation problem. Review that evidence and correct the local materials
before validating again.

## Repair Prompt

Click **Repair Prompt** when validation fails and you want a focused prompt for
a reviewer or LLM.

The repair prompt includes the validation failure, the current profile, the
expected-results contract, and the safety rules. Send that prompt with the
relevant sample and ask for a corrected `profile.yaml` only.

After repair, replace only the reviewed profile or expected-results values that
were wrong, then run **Validate** again.

## Install

Click **Install** only after **Check Package**, **Validate**, and any needed
**Diagnose** review pass.

Install requires an existing expected-results CSV and at least one existing
sample report referenced by that table under `samples/`. It freshly validates the
current profile and those samples. The expected-results checks require checked
data rows and compare the parsed rows and their count with the sample's expected
rows. An earlier structural PASS cannot bypass these requirements.

Only successful installation copies the profile into the local approved profile
store and writes approval evidence. Metroliza will only load approved profiles
whose approval checksum matches the installed `profile.yaml`.

## Restart

Restart Metroliza after installing a profile.

On startup, Metroliza scans approved parser profiles and makes them available to
normal report import. If the profile was installed while Metroliza was already
running, the old process may not see it until restart.

## Parse Reports

After restart, use the normal report parsing flow:

1. Open the report import/parse workflow.
2. Select the supplier report files.
3. Parse reports as usual.
4. Confirm that the report reference, date, sample number, and measurements
   match the source report.

The parser factory chooses the best matching parser by file type, template
markers, confidence, priority, and plugin id. You do not need to register the
profile in source code.

## When To Ask For Help

Stop and ask an operator, release owner, or data owner for help when:

- you are not sure whether report samples are private or may be shared,
- you have fewer than the required representative samples,
- validation fails repeatedly after repair,
- Diagnose shows that the wrong parser is selected,
- parsed values pass technically but do not match the business meaning of the
  report,
- the supplier uses multiple visible layouts in the sample set,
- an LLM output adds Python, network access, package installation, shell
  commands, database-write behavior, or installer changes.

## Tiny Example

Sample report text:

```text
SYNTHETIC SUPPLIER ALPHA
Reference: REF123
Date: 2026-01-05
Sample: 0001
DIM X 10.0 0.1 -0.1 - 10.02 0.02 0
```

One `expected_results.csv` row:

```csv
sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance
sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0
```

Minimal `profile.yaml` fragment:

```yaml
schema_version: 1
plugin:
  plugin_id: supplier_alpha
  display_name: Supplier Alpha
  version: 0.1.0
  source_format: pdf
  supported_locales: ["*"]
  template_ids: ["synthetic_fixture"]
  priority: 900
probe:
  required_markers:
    - "SYNTHETIC SUPPLIER ALPHA"
  confidence: 92
extraction:
  report_fields:
    reference: 'Reference:\s*(?P<value>\S+)'
    report_date: 'Date:\s*(?P<value>\d{4}-\d{2}-\d{2})'
    sample_number: 'Sample:\s*(?P<value>\S+)'
  blocks:
    - header: "MAIN FEATURE"
      pattern: '^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.,]+)\s+(?P<tol_plus>[-0-9.,]+)\s+(?P<tol_minus>[-0-9.,]+)\s+(?P<bonus>[-0-9.,]+|-)\s+(?P<measured>[-0-9.,]+)\s+(?P<deviation>[-0-9.,]+)\s+(?P<out_of_tolerance>[-0-9.,]+)$'
normalization:
  decimal_separator: "."
  date_formats: ["%Y-%m-%d"]
  missing_value_tokens: ["", "-", "NA", "N/A"]
```

## Visible keyboard commands

| Command | Shortcut | Context |
|---|---|---|
| Manage / Add task | Ctrl+Shift+D / Ctrl+Shift+A | Profiles window |
| Next named action / Refresh | Ctrl+S | Add / Manage tab |
| Prepare folder | Ctrl+D | Add |
| Check package / Validate | Ctrl+R / Ctrl+Shift+R | Add |
| Install / Enable selected | Ctrl+E | Add / Manage |
| Disable selected | Ctrl+Shift+E | Manage |
| Open folder / Copy path | Ctrl+Shift+F / Ctrl+Shift+C | Add |
| Diagnose / Repair prompt | Ctrl+Shift+Q / Ctrl+Shift+S | Observed problem in Add |
| Close | Ctrl+W or Esc | Existing close/validation ownership guards |

Keys act only in the current window and relevant task; disabled actions remain
inert. Standard text editing and Polish AltGr input are unchanged. A modal child
does not invoke its parent's commands. Closing during validation preserves the
existing worker cleanup; a result not adopted after close is labelled as such.
