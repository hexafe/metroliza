# Non-Technical Workflow: Create a New Parser Profile

This guide is for a user who is not a programmer but wants Metroliza to support a new supplier report template.

The preferred path is a **declarative parser profile**. That means you prepare examples and a YAML profile that trusted Metroliza code can read. You do not need to create Python code.

## What you need before you start

- 3-5 sample reports from the same supplier and same template family
- expected-results rows for every measurement row that should be parsed from each approval sample
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
- fill `expected_results.csv` with every parsed row you checked by hand for each approval sample
- keep any supplier notes next to the handoff files
- keep `contracts/`, `reference/contract_snippets.md`, `handoff_manifest.json`, and `NON_TECHNICAL_STEPS.md` with the files you give to the reviewer or LLM
- use `contracts/07_privacy_redaction_checklist.md` before sharing real reports outside your machine

## Step 3: Prepare the template analysis

Open `llm_handoff.md`.

Use it with an approved external LLM workflow or with a human reviewer. Metroliza does not send reports to an LLM. The app only creates the local handoff folder.

Give the reviewer:

- `profile.yaml`
- `NON_TECHNICAL_STEPS.md`
- `contracts/` or the shorter `reference/contract_snippets.md`
- the sample reports from `samples/`
- `expected_results.csv`
- the visible supplier/template notes you collected

Ask for a completed **declarative Metroliza parser profile**, not Python code.

Before you share the folder, an operator can check that the package is complete:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py integrity <handoff-folder>
```

If the LLM is small, cheap, local, or often loses context, do not ask it for the whole profile at once. Use one file from `prompts/` at a time:

1. identify template markers,
2. extract report identity fields,
3. extract measurement row rules,
4. define normalization,
5. complete `profile.yaml`,
6. repair validation failures.

Save each answer in `responses/` so the next prompt can refer to it.

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
- matches every manually verified row in `expected_results.csv`
- does not parse extra measurement rows that are missing from `expected_results.csv`

The operator command is:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
```

## Step 6: Repair if validation fails

If validation fails, use the failure notes to update only `profile.yaml` and the expected-values file when the manually checked value was wrong.

Repeat validation until the reviewer approves the result.

The CLI can write a self-contained repair prompt:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py repair <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --output <handoff-folder>/artifacts/profile_repair_prompt.md
```

For an LLM-assisted repair, send:

- the validation output,
- the current `profile.yaml`,
- `expected_results.csv`,
- the relevant sample report,
- `reference/contract_snippets.md`,
- `prompts/06_fix_validation_failures.md`.

Ask for a complete corrected `profile.yaml` only. Do not approve Python code, package changes, network access, shell commands, or database writes.

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
- Non-technical checklist: `NON_TECHNICAL_STEPS.md`
- Self-contained contract snippets: `contracts/` and `reference/contract_snippets.md`
- Small LLM prompts: `prompts/`
- LLM answers and repair notes: `responses/` and `artifacts/`
- Final approved profile for Metroliza: `~/.metroliza/parser_plugins/profiles/approved/<profile-id>/profile.yaml`

## Troubleshooting

- If the wrong parser is selected, improve the required markers in `profile.yaml`.
- If dates or decimals are wrong, update the normalization section with explicit examples and repair the profile.
- If the report family has multiple visible layouts, prepare one workspace per template family.
- If validation passes but the business values are wrong, add those mismatches to `expected_results.csv`, then repair and validate again.
