# Quick Start: Create a New Parser Plugin (Non-Technical Guide)

This guide is for team members who are **not developers** but need to onboard a new supplier report template.

## What you need before you start
1. **3–5 sample reports** from the supplier (same format, for example PDF).
2. A simple spreadsheet with expected values for each sample:
   - Reference
   - Date
   - Sample number
   - A few measurement rows (`AX`, `NOM`, `MEAS`, tolerance values)
3. Supplier details:
   - Supplier name
   - Country/language (if not English)
   - Any known template/version label on the report

---

## Step-by-step process

### Step 1) Put sample files in one folder
Create a folder like:

`new_supplier_samples/`

Put all supplier sample reports there.

### Step 2) Add expected results file
In the same folder, add a spreadsheet named:

`expected_results.xlsx`

Use one row per measurement line you can verify.

### Step 3) Ask engineering to generate plugin draft
Send this package to engineering with this sentence:

> "Please generate a parser plugin draft using the LLM plugin scaffold for these samples and validate against expected results."

### Step 4) Review the draft output report
Engineering should return:
- plugin id and version,
- confidence/warnings summary,
- pass/fail test summary.

You only need to check:
1. Are reference/date/sample number correct?
2. Are key measurements correct?
3. Are there warnings that look serious (many missing values)?

### Step 5) Approve or request fixes
- **Approve** if values match and warnings are acceptable.
- **Request fixes** if values are wrong or inconsistent.

Use this simple feedback format:
- File name
- Field that is wrong
- Expected value
- Actual value

### Step 6) Pilot rollout
After approval, enable plugin for a small pilot batch first (for example 20 reports), then full rollout if results are stable.

---

## Troubleshooting checklist
- If date format looks wrong: provide one more sample with a clearly labeled date.
- If decimal separator is wrong (`,` vs `.`): call this out in your notes.
- If headers are multilingual: provide at least one sample per language variant.
- If confidence is low: include more diverse samples (different months, different parts).

---

## Definition of done (business view)
A plugin is ready when:
- sample reports parse correctly,
- key expected values match,
- no critical warnings remain,
- pilot batch confirms stable output.
