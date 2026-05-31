# Non-Technical Workflow: Create a New Parser Profile

This guide is for a user who is not a programmer but wants Metroliza to support a new supplier report template.

The preferred path is a **declarative parser profile**. That means you prepare examples and a YAML profile that trusted Metroliza code can read. You do not need to create Python code.

## What you need before you start

- 3-5 sample reports from the same supplier and same template family
- a short list of expected values you can verify manually
- the supplier name, report language, date format, decimal separator, and any visible template/version labels

## Step 1: Create a workspace

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

`~/.metroliza/parser_plugins/profiles/incoming/<profile-id>/`

Use **Open Folder** to open that hidden folder, or **Copy Path** if you need to paste the folder location into a message or file browser.

## Step 2: Place the input files

Inside that workspace:

- put the real sample reports into `samples/`
- fill `expected_results.csv` with the values you checked by hand
- keep any supplier notes next to the handoff files

## Step 3: Prepare the template analysis

Open `llm_handoff.md`.

Use it with an approved external LLM workflow or with a human reviewer. Metroliza does not send reports to an LLM. The app only creates the local handoff folder.

Give the reviewer:

- `profile.yaml`
- the sample reports from `samples/`
- `expected_results.csv`
- the visible supplier/template notes you collected

Ask for a completed **declarative Metroliza parser profile**, not Python code.

## Step 4: Complete the profile

The completed `profile.yaml` should describe:

- profile identity and source type,
- reliable text markers that identify the template,
- report fields such as reference, date, and sample number,
- measurement row patterns,
- decimal and date normalization.

Do not add scripts, installers, network access, or package changes to the handoff folder.

## Step 5: Validate and approve the profile

Validation and approval are operator steps. The profile is not active until it is validated, approved, and moved into the approved profile store.

Validation should confirm that the profile:

- follows the required Metroliza contract
- returns a valid `ParseResultV2`
- keeps the requested plugin identity
- matches the manually verified values in `expected_results.csv`

The operator command is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
```

## Step 6: Repair if validation fails

If validation fails, use the failure notes to update only `profile.yaml` and the expected-values file when the manually checked value was wrong.

Repeat validation until the reviewer approves the result.

## Step 7: Install the approved profile

Approved profiles are installed under:

`~/.metroliza/parser_plugins/profiles/approved/<profile-id>/profile.yaml`

with an approval sidecar:

`~/.metroliza/parser_plugins/profiles/approved/<profile-id>/approval.json`

The operator install command is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --approved-by <approver>
```

Install will fail if `expected_results.csv` is missing or no sample report is referenced.

## Step 8: Restart Metroliza and parse the new report

After restart, Metroliza automatically scans approved parser profiles.

When you load a report:

- Metroliza identifies the source format
- the parser factory asks only plugins whose manifest supports that format to `probe(...)`
- the best matching plugin is selected automatically by confidence, then priority, then plugin id
- the selected parser should be the one that wins for the specific sample you are using, not just any parser for the same file type

You do not need to edit Metroliza source code to register the new parser.

## What goes where

- Sample reports: inside the workspace `samples/`
- Expected values: `expected_results.csv`
- Profile draft: workspace `profile.yaml`
- Handoff instructions: `llm_handoff.md`
- Final approved profile for Metroliza: `~/.metroliza/parser_plugins/profiles/approved/<profile-id>/profile.yaml`

## Troubleshooting

- If the wrong parser is selected, improve the required markers in `profile.yaml`.
- If dates or decimals are wrong, update the normalization section with explicit examples and repair the profile.
- If the report family has multiple visible layouts, prepare one workspace per template family.
- If validation passes but the business values are wrong, add those mismatches to `expected_results.csv`, then repair and validate again.
