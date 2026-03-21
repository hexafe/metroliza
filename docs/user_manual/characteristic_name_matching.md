# Characteristic Name Matching

## What name matching solves

Use **Characteristic Name Matching** when the same characteristic appears under different names in different reports or references.

This tool tells Metroliza that those different report names should be treated as the same characteristic.

This is especially useful before export when you want cleaner comparison, grouping, and grouped analysis across data that was named inconsistently.

A simple example:

- one report uses **TP GAP**,
- another report uses **AA-C11 - TP**.

If they really mean the same characteristic, you can create a match so Metroliza uses one shared common name.

## Main dialog overview

The main dialog contains:

- a **Database file** field,
- **Browse DB**,
- a table of **Saved name matches**,
- action buttons:
  - **Add match**
  - **Edit selected**
  - **Delete selected**
  - **Import CSV**
  - **Export CSV**
  - **Close**

The main table shows saved matches with these columns:

- **Original name**
- **Use this common name**
- **Apply to**
- **Reference**

## Creating a match

Click **Add match** to open the editor.

The editor includes these fields:

- **Name found in report**
- **Use this common name**
- **All references / One reference only**
- **Reference**

### Name found in report

Enter the characteristic name exactly as it appears in the report.

### Use this common name

Enter the shared/common name Metroliza should use instead.

### All references / One reference only

Choose whether the match should apply everywhere or only to one reference.

### Reference

This field is used when the match is limited to **One reference only**.

## Global vs single-reference scope

### All references

Use **All references** when the name match should always apply.

Example:

If **TP GAP** should always be treated as **AA-C11 - TP** no matter which reference the report comes from, use **All references**.

### One reference only

Use **One reference only** when the match is valid only for one specific reference.

Example:

If **TP GAP** means **AA-C11 - TP** only for one reference, but means something else in another context, create a one-reference-only match and specify that reference.

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

### Export CSV

Use **Export CSV** to save the current saved matches to a CSV file.

This is useful for:

- backup,
- reuse on another machine,
- reviewing/editing matches outside the app.

### Import CSV

Use **Import CSV** to load name matches from a CSV file.

This is useful when you already maintain a mapping list externally or want to load many matches at once.

## Validation and remediation reports

CSV import includes validation.

That means Metroliza checks the CSV data before importing it.

Possible validation issues include:

- wrong header/schema,
- missing or invalid field values,
- duplicate collisions for the same alias/scope combination.

### If the CSV header is wrong

The app shows an import error explaining the expected header schema.

### If row validation fails

The app shows a validation summary and lets you inspect more detail.

If row-level issues exist, the app can also offer to save a **remediation CSV report**.

Use that remediation file as a to-do list for fixing the import data and retrying.

## Example scenarios

### Example 1: Global normalization

You have reports where the same feature appears as:

- **TP GAP**
- **AA-C11 - TP**

Create a match:

- **Name found in report:** `TP GAP`
- **Use this common name:** `AA-C11 - TP`
- **Apply to:** `All references`

### Example 2: Reference-specific normalization

A short name is only safe for one reference.

Create a match:

- **Name found in report:** short/local name
- **Use this common name:** the shared standard name
- **Apply to:** `One reference only`
- **Reference:** the exact reference where the rule should apply

## When to use this relative to export

If characteristic names need normalization, it is usually best to set up **Characteristic Name Matching** before running [Export overview](export_overview.md).

That helps grouped reporting and the **Group Analysis worksheet** use the common names you intended.
