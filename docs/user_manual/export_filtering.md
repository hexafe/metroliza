# Export Filtering

## What filtering does

The **Data filtering** dialog lets you narrow which rows the Export workflow will use.

Open it from the Export dialog by clicking **Edit...** next to **Filters**.

After filters are applied, the Export dialog shows a compact summary next to **Filters**. For example:

- `Reference: 2 selected`
- `Header: 8 selected`
- `Date: 2026-01-01 to 2026-05-08`
- `Reports with at least one NOK`
- `Only NOK measurements`

Hover over the summary to see the full selected values when the label only shows counts.

The dialog uses tabs so the available choices stay readable on smaller screens:

- **Measurement** tab: AX, REFERENCE, HEADER, SELECTED HEADERS, and STATUS CODE.
- **Report metadata** tab: PART NAME, REVISION, TEMPLATE VARIANT, SAMPLE NUMBER, OPERATOR NAME, and SAMPLE NUMBER KIND.
- **Source** tab: FILENAME, PARSER ID, and TEMPLATE FAMILY.
- The combined filter expression, date range, and NOK controls stay at the bottom with the apply action.

**Reports with at least one NOK** includes matching measurements from any report that contains a NOK reading.
For example, a HEIGHT filter can include an OK height from a report with a NOK width.
**Only NOK measurements** selects NOK under **Measurement status** and applies to each measurement row.

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

Numeric comparisons and numeric `IN` accept complete finite numbers, including
`+1.2`, `.5`, `1.`, `+1e2`, signed zero and surrounding spaces, tabs or line breaks.
Blank, missing, malformed (for example `1x`), infinite and overflowing values do
not match positive numeric comparisons. Numeric `!=` and `NOT IN` include those
invalid values; numeric blank filters include them as well. Text and date filters
retain their own rules. Integer sources retain their 64-bit precision; decimal
and exponent forms use floating-point precision.

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

Selected headers stay in the filter when references change. Headers unavailable for the
current references are retained and named in a visible notice. Searching changes only
which choices are visible; it does not clear conditions.

## Date filtering

Use **Date range** to choose an inclusive range based on your local calendar date:

- **All dates** includes reports with missing dates, historical dates and future dates.
  The From and To fields become available when you choose a date range.
- **Today**: today only.
- **Yesterday**: yesterday only.
- **Last 7 days**: today and the six preceding days.
- **This month**: the first day of this month through today.
- **Custom**: edit **Measurement date from** and **Measurement date to**.

Choosing a preset fills both fields. Editing either field switches to **Custom**.
From must be on or before To; equal dates are valid. A reversed range blocks Apply and
shows a message beside the dates while preserving both entries.

Use the arrow keys to choose a preset. Tab then reaches From and To.
**Cancel** restores the previously applied dates and preset. Reopening keeps those
concrete dates; if a relative preset no longer matches the current day, it is shown as
**Custom**. Choose the preset again to update its dates. **Reset draft** selects
**All dates**. Presets are not remembered across app sessions.

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

Use **Saved filters… → Save filter draft as…** to keep the current conditions under a name.
Reusing a name asks for confirmation even if the saved entry is unavailable. Choose **No** to keep the existing entry.
Selecting a saved filter loads it as a draft. Review the selections and choose **Apply Filters** to use it.
The draft identifies any values that are unavailable in the loaded choices.

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

1. Choose **Last 7 days** in **Date range**, or choose **Custom** and enter your dates.
2. Check the range shown in the filter summary.
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
Selecting a concrete value clears **SELECT ALL**, and selecting **SELECT ALL** clears
concrete values. Older saved drafts containing both retain the concrete values.

If you leave a list on **SELECT ALL**, that dimension stays broad.

### Why is there a SELECTED HEADERS list?

It is a confirmation list, not a separate second filter system.

It mirrors what you selected in **HEADER**.

### How do I clear filters?

Use **Clear filters** next to **Edit...** in the Export dialog.

This clears the stored filter query and changes the summary back to **Not applied**.


## Draft, applied scope and keyboard actions

Each value list shows **All** or **Selected (n)**, the matching/listed choice count,
and hidden selected values. These counts describe choices, not a count of database rows.
Search hides choices only; hidden selections remain part of the filter.
The applied-scope line stays separate from edits until **Apply Filters [Ctrl+S]** succeeds.
Dates and expression errors remain visible before Apply; invalid input cannot be applied.

**Clear searches** changes visibility only. **Clear value selections (All)** broadens all
value lists while preserving dates, NOK and the expression. **Clear expression** removes
only that expression. **Reset draft [Ctrl+Shift+R]** resets all draft conditions after its
confirmation; the applied filter remains unchanged until Apply.
**Cancel [Ctrl+W]** or Esc uses the existing discard confirmation. **Ctrl+F** focuses the
search belonging to the active list. Existing Alt mnemonics remain secondary alternatives.

## Typed filter contract for adapters

The version 1 reference contract uses a field catalog. Each field has a stable ID,
display label, source, type and allowed operators. The type determines how both values
and cells are interpreted. For example, `Label = "001"` preserves the text `001` in
a text field. Name lookup accepts the exact field ID or an unambiguous case-insensitive
ID or label. An explicit field ID resolves an ambiguous display label.

All types support equality, inequality, membership (`IN` and `NOT IN`) and blank
checks. Number and date fields also support ordered comparisons and inclusive ranges.
Text fields also support contains, does not contain, starts with and ends with.
Conditions can be combined with AND and OR groups. The typed text parser supports
the Magic comparison and membership syntax above. Builders can also supply ranges
and blank checks through the structured document.

- **Numbers** use complete finite values. Missing, malformed, partial, non-finite
  and overflowing values match blank, inequality and `NOT IN`. Comparisons,
  ranges and `IN` require a valid number. Integer forms within signed and unsigned
  64-bit ranges remain exact. Other finite values use binary64 precision.
- **Dates** compare calendar days in the source's wall time. A timezone suffix
  leaves the source day intact. Ambiguous numeric dates prefer month first by
  default. The date field can use day-first parsing. Missing and invalid dates
  match blank, inequality and `NOT IN`. Comparisons, ranges and `IN` require a valid date.
- **Text** is case-insensitive by default using Unicode case folding. Whitespace
  is significant in comparisons and whitespace-only text counts as blank.
  Missing text matches blank, inequality, does not contain and `NOT IN`.
  With wildcards enabled, `*` matches zero or more characters in equality and
  membership. Contains, starts with and ends with use literal text.

The JSON document contains `version: 1` and `expression`. An empty expression is
`null`. Groups contain `operator` and `children`. Conditions contain `field`,
`kind`, `operator`, `values`, `case_sensitive`, `wildcards` and `dayfirst`.
Typed expressions allow at most 24 levels, counting the root as level 1, with
128 groups and conditions combined and 1,024 values across all conditions.
Typed expression text can have up to 24 levels of nested parentheses and must
also fit the expression limits. This keeps evaluation and compilation compatible
with the smaller parser stack of older SQLite builds. Reduce nesting, conditions
or values if a limit is reached.
Group operators are `and` and `or`. Common condition operators are `equals`,
`not_equals`, `in`, `not_in`, `is_blank` and `is_not_blank`. Numbers and dates
also allow `less_than`, `less_or_equal`, `greater_than`, `greater_or_equal`
and `between`. Text also allows `contains`, `not_contains`, `starts_with`
and `ends_with`. Blank checks take zero values, ranges take two and membership
takes one or more. Other conditions take one value.
Dates are saved as ISO calendar days. Numbers are saved as decimal strings to
preserve signed and unsigned integer precision in JSON readers. Saved filters
bind by exact field ID. If a field is missing or renamed, the adapter can offer
explicit remapping to a field of the same type with the needed operators.

### Adapter and preview contract

Parse the expression or load its v1 document with a field catalog, then call
`FilterAdapter.prepare(expression)` once for the source. Use `preview(sample_limit)`
for the exact matching-row count and the first matching row IDs. Use
`iter_row_ids()` on the same prepared filter for the complete selection. The
sample defaults to 20 rows and accepts a limit from zero through 1,000. A limit
of zero requests the count alone. Each source supplies unique, nonmissing row IDs
of one type, either integers or text, returned in ascending order. Preview and
final selection agree on unchanged data. The caller owns the source snapshot or
read transaction if both operations must agree while the source can change.

`PandasFilterAdapter` binds logical field IDs directly to DataFrame columns.
`SqliteFilterAdapter` binds a trusted table or view, identity column and
field-to-column map. It keeps the supplied connection open and uses its own
cursor. An independent count subquery and the limited, ordered selection run
in one SQLite statement so both read the same snapshot. A consumer that stops
streaming row IDs early should close the iterator.

Prepared filters report where the predicate ran. `in_memory` applies it to the
in-memory source. `sqlite_scan` applies it inside SQLite with a connection-local
function and bound condition values. An index on a source value cannot speed up
that reference predicate. Reserve `sqlite_indexed` for a plan that uses an index
to narrow candidate rows. Use `post_filter` when remaining conditions must run
after reading candidates, and include a reason for the user. Preview must apply
those remaining conditions before counting or sampling.

Adapter tests can replay `FIELDS`, `ROWS`, `OPERATOR_CASES` and `GROUPED_CASE` from
[the shared conformance fixture](../../tests/typed_filter_conformance.py). Load
the rows through the adapter's source mapping with the same stable IDs. Pass the
adapter, loaded expression and fixture's expected IDs to `assert_selected_rows`
to check the count, ordered sample and final selection. CSV/Excel
Summary [#939](https://github.com/hexafe/metroliza/issues/939) and the industrial
cache [#940](https://github.com/hexafe/metroliza/issues/940) own the corresponding
schema mappings, indexed plans and additional source-specific cases.

### Reports compatibility and migration scope

For **Whole database → Main plots → local XLSX**, use **Typed expression** in
the filter dialog when you want field types to control the comparison. Enter an
expression and choose **Preview rows…**. The dialog shows the exact matching
measurement count and up to 20 rows ordered by measurement ID. You can cancel
the scan while it runs. The preview includes your list choices, date range and
NOK restrictions. Choose **Apply Filters** to use that scope for the workbook.
If the draft or database changes, preview again before applying or exporting.

The typed catalog includes Reference (`Ref`), Dimension, Axis, Status,
Measurement (`meas`) and Date. Choose **Saved filters… → Save typed filter draft as…**
to keep a typed draft. **Load typed as draft** restores the conditions and
requires a new preview against the current database before Apply. Typed presets
store the expression and its stable field IDs separately from Magic presets.
Saved typed presets check the integrity of the whole definition, including list,
date and NOK conditions. They are saved atomically in `reports.typed.json`.
Experimental typed entries in `reports.ini` are kept for reference. Recreate
them as new drafts. If a typed preset changes while you are confirming
replacement, review the newer entry and try saving again.
An unavailable typed preset shows the field or condition that needs attention
and keeps the original entry. Use **Edit expression…** to replace an incompatible
field or operator in a new draft, then preview it. The original preset stays saved
until you explicitly replace it. Export recipes continue to use the existing Magic format.
Clear the typed filter before switching to grouping, HTML, Google Sheets,
industrial context or the last-import scope.

Existing Magic filters, Reports presets and recipes retain their current
semantics. The report alias `Ref` resolves to
`reference`. For `Ref IN ("001") AND Dimension = W*`, Magic infers a number and
matches reference text `001` and `1` when the dimension also matches. A typed
text field matches only `001`. The regression fixture exercises the saved state,
measurement selection, report grouping, and export with fixed row IDs.
[Report migration regression](../../tests/test_report_query_service.py)

The typed workbook path binds the same query and parameters used by the preview
and selects its rows into a temporary export snapshot. Both require the standard
Reports measurement view. If that view has changed, restore an intact Reports
database or import the source reports into a new database. Grouping and other
export targets remain separate work.
