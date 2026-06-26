# Export Filtering

## What filtering does

The **Data filtering** dialog lets you narrow which rows the Export workflow will use.

Open it from the Export dialog by clicking **Edit...** next to **Filters**.

After filters are applied, the Export dialog shows a compact summary next to **Filters**. For example:

- `Reference: 2 selected`
- `Header: 8 selected`
- `Date: 2026-01-01 to 2026-05-08`
- `NOK only`

Hover over the summary to see the full selected values when the label only shows counts.

The dialog uses tabs so the available choices stay readable on smaller screens:

- **Measurement** tab: AX, REFERENCE, HEADER, SELECTED HEADERS, and STATUS CODE.
- **Report metadata** tab: PART NAME, REVISION, TEMPLATE VARIANT, SAMPLE NUMBER, OPERATOR NAME, and SAMPLE NUMBER KIND.
- **Source** tab: FILENAME, PARSER ID, and TEMPLATE FAMILY.
- The combined filter expression, date range, and **HAS NOK ONLY** controls stay at the bottom with the apply action.

It filters across the main report and measurement metadata dimensions:

- **AX**,
- **REFERENCE**,
- **HEADER**, and
- **PART NAME**,
- **REVISION**,
- **TEMPLATE VARIANT**,
- **SAMPLE NUMBER**,
- **OPERATOR NAME**,
- **SAMPLE NUMBER KIND**,
- **STATUS CODE**,
- **FILENAME**,
- **PARSER ID**,
- **TEMPLATE FAMILY**, and
- measurement date range.

Filtering changes the scope of the export. It does not permanently edit the database.

## Combined filter expression

Use **Filter expression** when one list is not enough to describe the exact rows you want.

Example:

`Reference=REF1 AND Dimension=VAL1`

This keeps only rows where the same measurement row belongs to `REF1` and has header/dimension `VAL1`.
It is useful when the same dimension name appears under several references and you need just one reference/dimension combination.

The expression can be combined with the list selections. Metroliza applies both:

- selected list values, and
- the expression text.

Common expression fields:

- `Reference` or `Ref`
- `Dimension` or `Header`
- `Characteristic`
- `Axis` or `AX`
- `Status`
- `Part`
- `Revision`
- `Sample`
- `Operator`
- `File`

The expression supports `=`, `!=`, `<`, `<=`, `>`, `>=`, `IN`, `NOT IN`, `AND`, `OR`, parentheses, and `*` wildcards.
Field names and operators are not case-sensitive, so `Meas`, `meas`, `AND`, `and`, `IN`, and `in` are interpreted the same way. Text values are also matched without case sensitivity by default.

When you repeat a comparison after `AND`, Metroliza reuses the previous field name. For example, `Meas > 200 and < 150.2` is accepted as `Meas > 200 AND Meas < 150.2`. Because those two limits conflict, the filter is valid but matches zero rows.

Examples:

- `Reference=REF1 AND Dimension=VAL1`
- `Reference IN (REF1, REF2) AND Dimension=VAL1`
- `Header IN (VAL1, VAL2) AND Status=NOK`
- `Reference=REF1 AND Axis=X*`
- `meas > 200 and < 150.2`

If the expression is invalid, the dialog keeps the filter open and shows the error in the summary line.

## Each list and search box

The dialog has search boxes and selection lists for the main filtering dimensions.

The lists are arranged in tabs, not in one long horizontal row. Switch tabs to move between measurement fields, report metadata, and source-file filters while keeping the date, NOK-only, and apply controls visible.

### AX

Use the **AX** list to limit export to specific AX values.

- Use the search box to quickly narrow the list.
- The list includes **SELECT ALL**.

If **SELECT ALL** is selected, AX is not narrowed.

### REFERENCE

Use the **REFERENCE** list to limit export to specific references.

- Use the search box to find references quickly.
- The list includes **SELECT ALL**.

If **SELECT ALL** is selected, REFERENCE is not narrowed.

### HEADER

Use the **HEADER** list to limit export to specific measurement headers.

- Use the search box to find headers quickly.
- The list includes **SELECT ALL**.

If **SELECT ALL** is selected, HEADER is not narrowed.

### SELECTED HEADERS

The **SELECTED HEADERS** list mirrors the headers currently selected in the **HEADER** list.

This is a convenience view. It helps you confirm the active header selection in one place.

It is especially useful when the header list is long.

To remove headers from this list, select them in **SELECTED HEADERS** and press
**Delete** or **Backspace**. Metroliza clears those same headers in the main
**HEADER** list and refreshes the confirmation list.

### PART NAME, REVISION, TEMPLATE VARIANT, SAMPLE NUMBER

These lists narrow the export to specific report metadata values.

Use them when you want to focus on a particular part definition or sample grouping.

Each list includes **SELECT ALL**.

### OPERATOR NAME

Use **OPERATOR NAME** to limit export to reports associated with a specific operator.

This is useful when the source data includes per-report operator metadata.

### SAMPLE NUMBER KIND

Use **SAMPLE NUMBER KIND** to narrow export to the sample number classification stored with the report metadata.

### STATUS CODE

Use **STATUS CODE** to filter by the measurement status stored in the export rows, such as `ok`, `nok`, or `unknown`.

### FILENAME

Use **FILENAME** to limit export to one or more source file names.

### PARSER ID and TEMPLATE FAMILY

Use **PARSER ID** and **TEMPLATE FAMILY** when you need to isolate reports extracted by a particular parser or template family.

## Startup and existing databases

When the filtering dialog opens, it refreshes the report metadata schema views before loading list choices. This keeps older databases aligned with the current metadata/export view shape and avoids stale-view errors such as missing measurement identifiers.

## How REFERENCE affects HEADER choices

REFERENCE selection can change which headers are available in the **HEADER** list.

In plain language:

- if you select one or more specific references, the dialog rebuilds the **HEADER** list to show headers available for those references,
- if you leave REFERENCE on **SELECT ALL**, the full header list is available.

This means the header choices are not completely independent from reference choices.

If a header seems to disappear, check the selected references first.

## Date filtering

The dialog includes two date controls:

- **MEASUREMENT DATE FROM**
- **MEASUREMENT DATE TO**

These let you limit the export to a date range.

### Select today

The **Select today** button sets the **date TO** field to today.

### Select beginning of time

The **Select beginning of time** button sets the **date FROM** field to the beginning date used by the dialog.

## Applying filters

Click **Apply filters** to send the current filter state back to the Export dialog.

When applied:

- the parent Export dialog stores the new filter query, and
- its filter label changes to summarize the active filters.

Use **Clear filters** in the Export dialog to reset the export back to the default unfiltered state in one click.

If you want to revise filters instead, reopen the dialog, change the selections, and click **Apply filters** again.

## Practical examples

### Example 1: Export only one reference

1. In Export, click **Edit...** next to **Filters**.
2. In **REFERENCE**, choose the reference you want.
3. Leave other lists on **SELECT ALL** if you do not want extra restrictions.
4. Click **Apply filters**.

### Example 2: Export only a few headers for one reference

1. Select the reference in **REFERENCE**.
2. Wait for **HEADER** to refresh.
3. Select the needed headers.
4. Check **SELECTED HEADERS** to confirm the list.
5. Click **Apply filters**.

### Example 3: Export one repeated dimension from one reference

1. In **Filter expression**, type `Reference=REF1 AND Dimension=VAL1`.
2. Leave the list filters on **SELECT ALL**, unless you want extra restrictions.
3. Click **Apply filters**.

Use this when `VAL1` exists in multiple references but only the `REF1` measurement rows should be exported.

### Example 4: Export only recent measurements

1. Set **MEASUREMENT DATE FROM** to your starting date.
2. Use **Select today** for the end date if needed.
3. Click **Apply filters**.

### Example 5: Review NOK rows from one operator and source file

1. In Export, click **Edit...** next to **Filters**.
2. In **STATUS CODE**, choose `nok`, or use **HAS NOK ONLY** if you simply want rows with
   NOK results.
3. On the **Source** tab, choose the source file in **FILENAME**.
4. On the **Report metadata** tab, choose the person in **OPERATOR NAME**.
5. Leave other lists on **SELECT ALL** unless you need more restrictions.
6. Click **Apply filters**.

## Common confusion points

### What does SELECT ALL mean?

**SELECT ALL** means “do not narrow by this list.”

If you leave a list on **SELECT ALL**, that dimension stays broad.

### Why is there a SELECTED HEADERS list?

It is a confirmation list, not a separate second filter system.

It mirrors what you selected in **HEADER**.

### How do I clear filters?

Use **Clear filters** next to **Edit...** in the Export dialog.

This clears the stored filter query and changes the summary back to **Not applied**.
