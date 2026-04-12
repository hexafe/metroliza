# Group Analysis User Manual

This guide explains how to read the exported **Group Analysis** worksheet in plain English. It is the main end-user reading guide for the current Group Analysis-focused release.

Printable companion: [`user_manual.pdf`](user_manual.pdf).

If you are not sure where to start, read the worksheet top summary first, then move to the metric block you care about, then use the pairwise table and caution notes before acting on the result.

## A quick real-world example

Imagine you measure the same feature from three production lines: **Line A**, **Line B**, and **Line C**.

You open the Group Analysis worksheet because you want to answer practical questions such as:

- Are the lines behaving similarly or differently?
- If they differ, is the difference probably real or just noise?
- Is the gap large enough to matter in practice?
- Are any groups drifting toward a specification limit?

The worksheet helps you answer those questions without making you jump between multiple tabs.

## What the sheet is for

The Group Analysis sheet is a **single place to compare groups for each measured characteristic**.

Use it when you want to:

- compare one group against another,
- spot metrics that need attention first,
- see whether a difference is statistically supported,
- judge whether the difference is small or meaningful in practice,
- check whether specification performance looks healthy or risky, and
- decide what to review next.

It is designed for non-technical and semi-technical readers first. You do not need to be a statistician to use it safely.

## Fastest way to read the sheet

If you only have a minute, use this order:

1. Read the **top summary** to confirm what export you are looking at.
2. Jump to the **metric block** for the feature you care about.
3. In the pairwise area, read the **adjusted p-value** first.
4. Then read the **effect size** and **Delta mean**.
5. Check the **spec status** and any caution note.
6. If a plot is shown, use it as a visual confirmation.

That quick sequence usually tells you:

- whether there is evidence of a difference,
- whether the difference is practically important, and
- whether the result is safe to act on immediately.

## Plain-English meanings of the key terms

### Adjusted p-value

The **adjusted p-value** answers this question:

> After accounting for multiple comparisons, how strong is the evidence that the groups are truly different?

Why it matters:

- the worksheet may compare many groups and many pairs,
- more comparisons increase the chance of false alarms, and
- the adjusted p-value is the safer value to use for the final significance decision.

Simple reading guide:

- **Smaller is stronger evidence** of a real difference.
- **Larger means weaker evidence**.
- A common guide rail is:
  - **<= 0.05**: evidence supports a difference,
  - **> 0.05**: not enough corrected evidence for a confident difference claim.

Important: **not significant** does **not** automatically mean **the groups are equivalent**. It can also mean the sample is small, noisy, or uneven.

### Effect size

The **effect size** tells you how big the difference looks in practical terms.

Think of it as the **size of the gap**, not just whether a test detected it.

Simple reading guide:

- **Small effect**: a detectable difference may exist, but it may not matter much operationally.
- **Moderate effect**: the gap is more noticeable and may matter.
- **Large effect**: the groups are meaningfully separated and usually deserve attention.

Different statistical methods can use different effect-size formulas. You do not need to memorize the formulas. The main point is to read effect size as the worksheet's **practical importance signal**.

### Delta mean

**Delta mean** is the plainest number on the sheet: it is the **difference between average values**.

It answers:

> By how much did one group's average move relative to the other?

Simple reading guide:

- **Near zero**: averages are very similar.
- **Positive**: the first group average is higher than the comparison group.
- **Negative**: the first group average is lower than the comparison group.
- **Larger absolute values** mean a bigger average shift.

Delta mean is easy to understand, but it should not be used alone. Two groups can have a similar average and still differ in spread or shape.

## Why adjusted p-value and effect size should be read together

These two fields answer different questions:

- **Adjusted p-value** asks: *Is there enough evidence that the difference is real?*
- **Effect size** asks: *If it is real, is it small or large in practice?*

Read them together because either one alone can mislead:

- **Small adjusted p-value + tiny effect size**: the difference is probably real, but may not matter much operationally.
- **Large adjusted p-value + visible effect size**: the gap may matter, but the data is not yet strong enough for a confident significance claim.
- **Small adjusted p-value + large effect size**: this is usually the clearest signal that the groups differ in a practically important way.
- **Large adjusted p-value + small effect size**: most likely there is nothing actionable yet.

A safe habit is: **significance first, practical size second**.

## What is inside each metric block

Each metric block keeps the key information for one measured characteristic together.

Depending on the export level, a metric block may include:

- the metric or characteristic name,
- analysis status or interpretation label,
- descriptive statistics for each group,
- pairwise comparison results,
- adjusted p-values,
- effect size,
- Delta mean,
- distribution-shape or distance context,
- specification-related context such as capability and spec status,
- caution notes, and
- an on-sheet plot in the Standard export.

The goal is to let you stay in one place while reading one metric from summary to conclusion.

## Optional HTML dashboard view

If you enable the optional **HTML dashboard** during export, Metroliza also saves a browser-friendly view of the charts.

For **Group Analysis** plots in that dashboard, the plot callouts are intentionally simplified for faster non-technical review. In practical terms, the dashboard focuses on the main capability/status message and does not repeat extra confidence-interval callouts on those plots.

Use the dashboard when you want a quick visual review. Use the workbook when you need the fuller worksheet detail.

## Column guide

Exact column placement can vary a little by export level, but the meaning stays the same.

### Context and status columns

These columns help you orient yourself before reading the numbers.

- **Metric / Characteristic**: the feature being analyzed.
- **Status / Interpretation**: plain-language signal such as DIFFERENCE, NO DIFFERENCE, APPROXIMATE, or USE CAUTION.
- **Analysis level**: how much analysis depth was enabled for the export.
- **Notes / Warnings**: user-facing caveats about sample size, imbalance, comparability, or distribution behavior.

### Group summary columns

These tell you what each group looks like on its own.

- **N / Count**: number of observations used for that group.
- **Mean**: average value.
- **Std / Standard deviation**: how spread out the values are.
- **Min / Max / Range**: rough low-to-high span.
- **Median or quartile fields**, if shown: center and spread viewed more robustly.

### Pairwise comparison columns

These answer which specific groups differ from which others.

- **Group A / Group B**: the two groups being compared.
- **Adjusted p-value**: corrected evidence for a true difference.
- **Effect size**: practical size of the difference.
- **Delta mean**: signed difference in averages.
- **Comparison status**: quick interpretation label.

### Distribution and specification columns

These add context beyond the average.

- **Distribution shape**: whether the groups look similar in spread, skew, or tail behavior.
- **Spec status**: where the group appears to sit relative to specification limits.
- **Cp / Cpk / Capability**: capability indicators that help show how comfortably a process sits within spec.

## Guide rails and interpretation ranges

These are interpretation aids, not replacements for engineering judgment.

### Adjusted p-value guide rail

Use the adjusted p-value as the final significance checkpoint.

- **<= 0.05**: evidence supports a difference.
- **> 0.05**: not enough corrected evidence for a confident difference claim.

If the worksheet labels a result as approximate or cautionary, trust the label and read the note before acting.

### Cp / Cpk / Capability guide rails

Capability metrics describe how comfortably the process fits inside specification limits.

Practical reading guide:

- **Below 1.00**: process performance is usually not comfortably within spec.
- **Around 1.00**: borderline capability; watch closely.
- **Around 1.33 or higher**: often treated as healthier capability in many manufacturing settings.
- **Much higher than 1.33**: more comfort relative to the spec window, assuming the data is representative.

Helpful reminders:

- **Cp** reflects potential capability when the process is centered well.
- **Cpk** reflects actual capability after centering is considered.
- For one-sided specs, the sheet may show a one-sided capability form instead of the usual two-sided pair.
- Capability should be treated carefully when sample size is small or the distribution is strongly non-normal.

### Delta mean guide rail

Delta mean has no universal pass/fail threshold because it depends on the unit, tolerance, and engineering meaning of the metric.

Use this practical rule:

- **Near zero**: little average movement.
- **Noticeable but still small compared with tolerance**: probably limited practical impact.
- **Large relative to tolerance, process spread, or known engineering margin**: potentially important.

Always read Delta mean alongside effect size and spec status.

### Spec status guide rail

Spec status is a plain-language indication of how the data relates to specification limits.

Typical safe interpretation:

- **Comfortable / within spec**: values appear well inside the required limits.
- **Near limit / watch**: performance may still be acceptable, but margin is getting tight.
- **At risk / out of spec**: this metric needs prompt review.
- **Unavailable / not applicable**: spec limits were not suitable for this calculation.

Treat spec status as an operational priority signal, especially when it agrees with a meaningful Delta mean or weak capability result.

## Why different tests are chosen

You may notice that the worksheet does not always rely on one single statistical test.

That is intentional.

Different tests are better suited to different situations, for example:

- how many groups are being compared,
- how much data each group has,
- whether the groups are balanced or imbalanced,
- whether the data looks roughly well-behaved or clearly skewed, and
- whether assumptions for a stricter test are reasonable.

A simple way to think about it:

- when the data is well-behaved, the worksheet can use stronger, more direct tests,
- when the data is messier, it can use safer or more robust alternatives,
- and the export still presents the result in the same user-friendly way so you can focus on interpretation.

You do **not** need to choose the test yourself. Your job is mainly to read the outcome and the caution notes correctly.

## Distribution shape, spec status, and analysis level

### Distribution shape

Two groups can have similar averages but still behave differently.

For example, one group may:

- have a wider spread,
- be more skewed,
- have heavier tails, or
- contain more extreme values.

That is why distribution-shape information matters. It helps explain differences that the mean alone would hide.

### Spec status

Spec status connects the statistical result to a manufacturing decision.

Even if a difference is statistically real, the practical urgency depends on whether the process is still comfortably inside spec, moving toward a limit, or already showing risk.

### Analysis level

The analysis level tells you how much detail the export includes.

In plain terms:

- a lighter level is meant for faster reading and lower visual density,
- a fuller level includes more supporting detail such as on-sheet plots and extra interpretation context.

The reading order stays the same either way.

## Safe interpretation checklist

Before you make a process decision, run through this checklist:

- Confirm you are reading the **correct metric** and **correct groups**.
- Check the **sample counts**. Very small or very uneven groups need extra caution.
- Read the **adjusted p-value** first.
- Read the **effect size** next.
- Check **Delta mean** so you know the direction and size of the average shift.
- Look at **distribution shape** if shown; averages are not the whole story.
- Review **spec status** and **capability** before deciding operational urgency.
- Read all **warnings or caution labels** instead of skipping them.
- If the result is borderline, treat it as a signal to review more data, not as proof.
- If significance and practical importance disagree, slow down and investigate.

## Final takeaway

The Group Analysis worksheet is meant to help you move from **"Are these groups different?"** to **"Does that difference matter, and what should I do next?"**

The safest reading pattern is:

1. **Adjusted p-value** for evidence,
2. **Effect size** for practical importance,
3. **Delta mean** for direction and magnitude,
4. **Distribution shape** for deeper context,
5. **Spec status and capability** for operational risk.

If those signals point in the same direction, you can usually act with more confidence.
If they disagree, the worksheet is telling you to slow down, review the cautions, and gather context before making a decision.
