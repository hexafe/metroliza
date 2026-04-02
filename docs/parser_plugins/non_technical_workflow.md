# Non-Technical Workflow: Create a New Parser Plugin

This guide is for a user who is not a programmer but wants Metroliza to support a new supplier report template with LLM help.

## What you need before you start

- 3-5 sample reports from the same supplier and same template family
- a short list of expected values you can verify manually
- the supplier name, report language, date format, decimal separator, and any visible template/version labels

## Step 1: Create a workspace

Run:

```bash
python scripts/create_parser_plugin_workspace.py --plugin-id supplier_alpha --source-format pdf
```

This creates a working folder by default at:

`artifacts/parser_plugin_workspaces/supplier_alpha/`

## Step 2: Place the input files

Inside that workspace:

- put the real sample reports into `samples/`
- fill `supplier_intake.md`
- fill `expected_results_template.csv`

## Step 3: Ask the LLM for analysis

Upload these items to your LLM:

- all sample reports from `samples/`
- `supplier_intake.md`
- `expected_results_template.csv`
- `prompts/01_analysis_prompt.md`

Save the LLM answer into:

`responses/analysis_response.md`

## Step 4: Ask the LLM to write the parser

Upload these items to your LLM:

- `responses/analysis_response.md`
- `prompts/02_implementation_prompt.md`
- `generated_plugin.py`
- `tests/test_generated_plugin.py`

Paste the returned file contents back into:

- `generated_plugin.py`
- `tests/test_generated_plugin.py`

## Step 5: Validate the parser

Run:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf
```

Replace `sample_report_01.pdf` with one real sample from your workspace.

Validation should confirm that the plugin:

- follows the required Metroliza contract
- returns a valid `ParseResultV2`
- keeps the requested plugin identity

## Step 6: Repair if validation fails

Run:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --output artifacts/repair_prompt.md
```

Then upload `artifacts/repair_prompt.md` to the LLM, ask for a corrected version, paste the corrected files back into the workspace, and validate again.

## Step 7: Install the validated plugin

Copy the final `generated_plugin.py` file to:

`~/.metroliza/parser_plugins/supplier_alpha.py`

`~` means your home folder. On Windows this is typically:

`C:\Users\<your-user>\.metroliza\parser_plugins\`

## Step 8: Restart Metroliza and parse the new report

After restart, Metroliza automatically scans `~/.metroliza/parser_plugins/`.

When you load a report:

- Metroliza identifies the source format
- the parser factory asks matching plugins to `probe(...)`
- the best matching plugin is selected automatically

You do not need to edit Metroliza source code to register the new parser.

## What goes where

- Sample reports: inside the workspace `samples/`
- Supplier notes: `supplier_intake.md`
- Expected values: `expected_results_template.csv`
- LLM analysis answer: `responses/analysis_response.md`
- Generated parser before validation: workspace `generated_plugin.py`
- Final installed parser for Metroliza: `~/.metroliza/parser_plugins/<plugin-id>.py`

## Troubleshooting

- If the wrong parser is selected, improve the generated `probe(...)` logic so it uses stronger template markers.
- If dates or decimals are wrong, update `supplier_intake.md` with explicit locale examples and regenerate.
- If the report family has multiple visible layouts, prepare one workspace per template family.
- If validation passes but the business values are wrong, add those mismatches to the repair prompt and regenerate.
