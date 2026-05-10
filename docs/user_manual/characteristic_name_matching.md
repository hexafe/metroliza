# Characteristic Name Matching

## What name matching solves

Use **Characteristic Name Matching** when the same measured item appears under different report or export metric names.

This tool tells Metroliza that one metric name found in reports should be treated as another shared metric name during supported analysis outputs.

This is especially useful before export when inconsistent report naming would otherwise split the same measurement into separate Group Analysis rows.

A simple example:

- one report uses **TP GAP**,
- another report uses **AA-C11 - TP**.

If they mean the same measured item, create a match so Group Analysis uses one shared metric name.

## What changes, and what does not

Matches are stored in the selected Metroliza report database. They are lookup rules, not data-cleaning edits.

That means:

- the original parsed and stored report values are not rewritten,
- the broader workbook raw/measurement sheets keep the original stored values,
- currently, **Group Analysis** uses these matches when it builds metric identities,
- other export sheets only use these matches if a separate code change explicitly connects them to this mapping table.

## Main dialog overview

The main dialog contains:

- a **Database file** field showing the report database whose matches you are editing,
- **Browse DB** to choose a different Metroliza database,
- a searchable **Report/export names in this database** table,
- a **Saved name matches** table,
- action buttons:
  - **Add from selected**
  - **Add manually**
  - **Edit selected**
  - **Delete selected**
  - **Import CSV**
  - **Export CSV**
  - **Close**

The report/export names table shows names already found in the selected database, with counts for references, reports, and measurement rows. Select a row there when you want to avoid typing the original name manually.

The saved matches table shows:

- **Original export name** - the report/export metric name found in imported data,
- **Use this common name** - the shared metric name to use in supported analysis outputs,
- **Apply to**
- **Reference**

The list is database-backed. If you switch the database file, you are viewing and editing the matches stored in that database only.

## Creating a match

Use **Add from selected** after selecting a report/export name from the database-backed list.

Use **Add manually** only when you need to type a mapping that is not currently visible in the selected database.

The editor includes these fields:

- **Original report/export name**
- **Use this common name**
- **All references / One reference only**
- **Reference**
- an impact preview showing how many rows, reports, and references the match would affect.

### Original report/export name

Select the report/export metric name exactly as it appears in the imported report data.

Use the specific name that needs replacement, for example `TP GAP`.

### Use this common name

Enter the shared metric name that should be used for supported analysis outputs, for example `AA-C11 - TP`.

### All references / One reference only

Choose whether the match applies across the database or only when the report belongs to one reference.

### Reference

This field is used when the match is limited to **One reference only**.

Use the exact reference value used in the database/export context.

## Global vs single-reference scope

### All references

Use **All references** when the report metric name should always resolve to the same shared metric name.

Example:

If **TP GAP** should always be treated as **AA-C11 - TP** no matter which reference the report comes from, use **All references**.

### One reference only

Use **One reference only** when the same report metric name can mean different things for different references.

Example:

If **TP GAP** means **AA-C11 - TP** only for one reference, but means something else in another context, create a one-reference-only match and specify that reference.

Reference-specific matches are the safer choice when a short report name is reused in different contexts.

## Editing and deleting

### Edit selected

1. Select a row in the saved matches table.
2. Click **Edit selected**.
3. Update the fields.
4. Save the match.

### Delete selected

1. Select a row in the saved matches table.
2. Click **Delete selected**.
3. Confirm deletion.

Deleting a match stops Metroliza from using that replacement rule in future work.

## Import/export CSV

CSV import/export is for moving the mapping rules, not the report measurements themselves.

### Export CSV

Use **Export CSV** to save the current saved matches to a CSV file.

This is useful for:

- backup,
- reuse on another machine,
- reviewing/editing matches outside the app.

The exported CSV uses these columns:

```text
alias_name,canonical_name,scope_type,scope_value
```

### Import CSV

Use **Import CSV** to load name matches from a CSV file.

This is useful when you already maintain a mapping list externally or want to load many matches at once.

Use:

- `alias_name` for the original report/export metric name,
- `canonical_name` for the shared metric name,
- `scope_type` as `global` or `reference`,
- `scope_value` for the reference value when `scope_type` is `reference`.

## Validation and remediation reports

CSV import includes validation.

That means Metroliza checks the CSV data before importing it.

Possible validation issues include:

- wrong header/schema,
- missing original or shared metric names,
- invalid `scope_type`,
- missing `scope_value` for reference-scoped rows,
- duplicate collisions for the same alias/scope combination.

### If the CSV header is wrong

The app shows an import error explaining the expected header:

```text
alias_name,canonical_name,scope_type,scope_value
```

### If row validation fails

The app shows a validation summary and lets you inspect more detail.

If row-level issues exist, the app can also offer to save a **remediation CSV report**.

Use that remediation file as a to-do list for fixing the import data and retrying.

## Example scenarios

### Example 1: Global metric normalization

You have reports where the same feature appears as:

- **TP GAP**
- **AA-C11 - TP**

Create a match:

- **Original report/export name:** `TP GAP`
- **Use this common name:** `AA-C11 - TP`
- **Apply to:** `All references`

### Example 2: Reference-specific normalization

A short name is only safe for one reference.

Create a match:

- **Original report/export name:** the short/local report metric name
- **Use this common name:** the shared standard metric name
- **Apply to:** `One reference only`
- **Reference:** the exact reference where the rule should apply

## When to use this relative to export

If characteristic names need normalization, it is usually best to set up **Characteristic Name Matching** before running [Export overview](export_overview.md).

That helps the **Group Analysis worksheet** combine and label metrics using the common names you intended, while the raw stored report values remain unchanged.
