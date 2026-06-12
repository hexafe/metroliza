# Non-Technical Workflow: Create a New Parser Profile

This guide is for a user who is not a programmer but wants Metroliza to support
a new supplier report template.

The normal path is a **declarative YAML parser profile**. You prepare examples,
fill checked expected results, and complete `profile.yaml`. Metroliza then reads
that YAML with trusted in-app parser code.

Do not ask for Python code unless an operator confirms that the YAML route
cannot model the report.

## Glossary

- **Parser profile**: a data-only `profile.yaml` file for one report layout.
- **Handoff folder**: the local folder created by Metroliza for samples,
  expected results, prompts, contracts, and review artifacts.
- **Sample report**: a real supplier report from the layout you want Metroliza
  to parse.
- **Expected results**: the values you checked by hand in
  `expected_results.csv`.
- **Probe**: the quick template match that tells Metroliza whether a parser fits
  a report.
- **Validate**: the check that compares the profile output with
  `expected_results.csv`.
- **Diagnose**: the check that explains whether the intended parser is selected
  for one sample.
- **Repair prompt**: a focused prompt for fixing `profile.yaml` after validation
  fails.
- **Advanced Python plugin**: an operator-only parser file used when YAML is not
  expressive enough.

## What You Need Before You Start

- 3 to 5 sample reports from the same supplier and same visible template family.
- Expected-results rows for every measurement row that should be parsed from
  each approval sample.
- The supplier name, report language, date format, decimal separator, units, and
  any visible template/version labels.
- Permission to share samples with the selected reviewer or LLM workflow.

If the sample reports do not look like the same layout, stop and split them into
separate workspaces.

## Step 1: Create The Handoff Folder

In Metroliza, open:

```text
Tools > Parser profiles...
```

Enter:

- a short profile id, for example `supplier_alpha`,
- a clear display name, for example `Supplier Alpha`,
- the source type, such as `pdf`, `excel`, or `csv`.

Click **Create Handoff Folder**.

This creates a working folder under:

```text
~/.metroliza/parser_plugins/profiles/incoming/<profile-id>/
```

Use **Open Folder** to open that hidden folder. Use **Copy Path** if you need to
paste the folder location into a message, terminal, or file browser.

## Step 2: Add Samples And Checked Values

Inside the handoff folder:

- put the real sample reports into `samples/`,
- fill `expected_results.csv` with every parsed row you checked by hand,
- keep supplier notes next to the handoff files,
- keep `contracts/`, `reference/contract_snippets.md`,
  `handoff_manifest.json`, and `NON_TECHNICAL_STEPS.md` with any files you give
  to the reviewer or LLM,
- use `contracts/07_privacy_redaction_checklist.md` before sharing real reports
  outside your machine.

Do not skip `expected_results.csv`. Validation needs at least one checked row,
and every parsed row in the approval samples must be represented there.

## Step 3: Use The LLM Handoff Safely

Open `llm_handoff.md`.

Metroliza does not send reports to an LLM. The app only creates the local
handoff folder. You decide what to share through an approved external workflow
or with a human reviewer.

Give the reviewer:

- `profile.yaml`,
- `NON_TECHNICAL_STEPS.md`,
- `contracts/` or the shorter `reference/contract_snippets.md`,
- the sample reports from `samples/`,
- `expected_results.csv`,
- the visible supplier/template notes you collected.

Ask for a completed **declarative Metroliza parser profile YAML**.

Use this wording:

```text
Please complete profile.yaml only. Do not return Python code, network calls,
package installation, shell commands, installer changes, or database writes.
```

If the LLM is small, cheap, local, or often loses context, send one file from
`prompts/` at a time:

1. identify template markers,
2. extract report identity fields,
3. extract measurement row rules,
4. define normalization,
5. complete `profile.yaml`,
6. repair validation failures.

Save each answer in `responses/` so the next prompt can refer to it.

## Step 4: Check The Package

Before validation or review, click **Check Package** in the dialog.

This confirms that the handoff folder still contains the required files,
expected-results table, sample location, contract snippets, prompts, and
manifest. If it reports missing files, restore the generated files or add the
missing samples before continuing.

The operator CLI equivalent is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py integrity <handoff-folder>
```

## Step 5: Complete The Profile

The completed `profile.yaml` should describe:

- profile identity and source type,
- reliable text markers that identify the template,
- report fields such as reference, date, and sample number,
- measurement row patterns,
- decimal and date normalization.

Do not add scripts, installers, package files, network access, shell commands,
or database changes to the handoff folder.

## Tiny Copyable Example

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

## Step 6: Validate The Profile

Validation and approval are operator steps. The profile is not active until it
is validated, approved, and moved into the approved profile store.

Click **Validate** in the dialog after `profile.yaml`, samples, and
`expected_results.csv` are ready.

Validation should confirm that the profile:

- follows the required Metroliza contract,
- returns a valid parser result through trusted Metroliza code,
- keeps the requested plugin identity,
- matches every manually verified row in `expected_results.csv`,
- does not parse extra measurement rows that are missing from
  `expected_results.csv`.

The operator CLI equivalent is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
```

## Step 7: Diagnose Parser Selection

Click **Diagnose** when validation passes or when you suspect the wrong parser
will be chosen.

Diagnose checks one sample report against the profile and writes evidence under
`artifacts/`. The intended parser should win for the specific sample, not just
for the same file type.

The operator CLI equivalent is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose <handoff-folder>/profile.yaml <handoff-folder>/samples/sample_report_01.pdf
```

## Step 8: Repair If Validation Fails

If validation fails, update only `profile.yaml` and only those expected-values
cells that were manually checked and found wrong.

Click **Repair Prompt** to write a self-contained prompt for a reviewer or LLM.
Send the repair prompt with:

- the validation output,
- the current `profile.yaml`,
- `expected_results.csv`,
- the relevant sample report,
- `reference/contract_snippets.md`,
- `prompts/06_fix_validation_failures.md` if present.

Ask for a complete corrected `profile.yaml` only. Do not approve Python code,
package changes, network access, shell commands, installer changes, or database
writes.

The operator CLI equivalent is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py repair <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --output <handoff-folder>/artifacts/profile_repair_prompt.md
```

Repeat **Validate** and **Diagnose** after each repair.

## Step 9: Install The Approved Profile

Click **Install** only after validation passes and Diagnose shows that the
intended parser is selected.

Approved profiles are installed under:

```text
~/.metroliza/parser_plugins/profiles/approved/<profile-id>/profile.yaml
```

with an approval sidecar:

```text
~/.metroliza/parser_plugins/profiles/approved/<profile-id>/approval.json
```

The operator CLI equivalent is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --approved-by <approver>
```

Install will fail if `expected_results.csv` is missing or no sample report is
referenced.

## Step 10: Restart Metroliza And Parse Reports

Restart Metroliza after installing the profile.

After restart, Metroliza automatically scans approved parser profiles. Then use
the normal report parsing flow:

1. Open the report import/parse workflow.
2. Select the supplier report files.
3. Parse reports as usual.
4. Confirm report reference, date, sample number, and measurement values against
   the source report.

When you load a report:

- Metroliza identifies the source format,
- the parser factory asks only parsers whose manifest supports that format to
  `probe(...)`,
- the best matching parser is selected automatically by confidence, then
  priority, then plugin id.

You do not need to edit Metroliza source code to register the new parser.

## When To Ask For Help

Stop and ask an operator, release owner, or data owner when:

- privacy is uncertain or you are unsure whether samples may be shared,
- you do not have enough representative samples,
- validation fails repeatedly after repair,
- Diagnose shows that the wrong parser is selected,
- parsed values pass technically but do not match the report's business meaning,
- the supplier uses multiple visible layouts in the sample set,
- any LLM output adds Python, network access, package installation, shell
  commands, database-write behavior, or installer changes.

## Advanced Python Plugin Route

Use this only after an operator confirms the YAML profile route cannot model the
supplier template.

Advanced Python plugins may be needed for unusual decoding, custom
pre-processing, or multi-stage parsing. They must still return Metroliza parser
results through the existing parser architecture and must not write SQLite
directly, install packages, run shell commands, call networks, or change global
runtime behavior.

Advanced plugin validation uses the separate Python plugin tools described in
[`parser_plugin_specification.md`](./parser_plugin_specification.md).
