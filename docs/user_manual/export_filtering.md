# Export Filtering

## What filtering does

The **Data filtering** dialog lets you narrow which rows the Export workflow will use.

Open it from the Export dialog by clicking **Edit...** next to **Filters**.

It filters across four dimensions:

- **AX**,
- **REFERENCE**,
- **HEADER**, and
- measurement date range.

Filtering changes the scope of the export. It does not permanently edit the database.

## Each list and search box

The dialog has search boxes and selection lists for the main filtering dimensions.

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
- its filter label changes to show that filtering is applied.

There is no separate **clear** or **reset** button inside this dialog.

If you want to revise filters, reopen the dialog, change the selections, and click **Apply filters** again.

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

### Example 3: Export only recent measurements

1. Set **MEASUREMENT DATE FROM** to your starting date.
2. Use **Select today** for the end date if needed.
3. Click **Apply filters**.

## Common confusion points

### What does SELECT ALL mean?

**SELECT ALL** means “do not narrow by this list.”

If you leave a list on **SELECT ALL**, that dimension stays broad.

### Why is there a SELECTED HEADERS list?

It is a confirmation list, not a separate second filter system.

It mirrors what you selected in **HEADER**.

### I cannot find a reset button

That is expected.

This dialog does not have a dedicated clear/reset button. To change filters, simply reopen it, adjust the selections, and apply again.
