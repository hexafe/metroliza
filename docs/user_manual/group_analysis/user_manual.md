# Group Analysis User Manual

This guide explains how to read exported **Group Analysis** output in plain English.
For standard grouped Export, the active reading surface is the **HTML dashboard**.
Do not expect standard grouped Export to add separate Group Analysis workbook sheets.
Use workbook details only as a secondary, legacy, technical, or internal/debug surface
when they are present.

Printable companion: [user_manual.pdf](user_manual.pdf).

If you are setting up grouping or export options, start with [Export grouping](../export_grouping.md)
and [Export overview](../export_overview.md). This page focuses on reading the result after export.

## What Group Analysis Answers

Group Analysis helps you compare named groups for each measured characteristic.

Use it when you want to answer practical questions such as:

- Are the groups behaving similarly or differently?
- If they differ, is the difference probably real or just noise?
- Is the gap large enough to matter in practice?
- Are any groups moving toward a specification limit?
- Which metric deserves attention first?

Grouped exports add Group Analysis to the HTML dashboard automatically. Without grouping, Group
Analysis is off.

## Fast Dashboard Reading Path

If you only have a minute, read the dashboard in this order:

1. Open the exported HTML dashboard.
2. Go to **Group comparison** from the dashboard jump list.
3. Read the top summary: status, analysis level, scope, metric count, group count, reference count,
   and warning count.
4. Read any **Warnings**, **Run notes**, or skipped-analysis message before interpreting metrics.
5. Use the metric jump list to open the measured characteristic you care about.
6. In the metric block, read **Key takeaways** first.
7. Read **Metric summary** next for spec status, restrictions, the main takeaway, recommended
   action, and flags.
8. Review the plots as visual confirmation.
9. Open **Detailed tables** only when you need the supporting numbers.

That sequence usually tells you:

- whether there is evidence of a group difference,
- whether the difference is practically important,
- whether the result is safe to act on now, and
- which follow-up question to ask next.

## A Quick Real-World Example

Imagine you measure the same feature from three production lines: **Line A**, **Line B**, and
**Line C**.

Open the dashboard and jump to **Group comparison**. The section summary tells you whether the
analysis ran, how many metrics and groups were compared, and whether warnings exist. Then choose
the metric for the feature you care about.

Inside that metric block, start with **Key takeaways**. If the takeaway says one line is separated
from the others and the recommended action points to review, then check the plot and the detailed
pairwise table. If the detailed table also shows a small adjusted p-value and a meaningful effect
size, the difference is more likely to be both statistically supported and operationally relevant.

## Dashboard Section Map

### Group comparison summary

The **Group comparison** section is the dashboard home for grouped statistics. It shows:

- **Level**: how much Group Analysis detail was produced.
- **Scope**: whether the comparison was treated as single-reference or multi-reference.
- **Metrics**: how many metric blocks are available.
- A summary table with status, level, scope, metrics, groups, references, and warnings.

Read this before any metric block. It confirms that you are looking at the expected export and
shows whether the analysis was complete, skipped, or warning-heavy.

### Warnings and run notes

Warnings and run notes tell you when the result needs caution. Do not treat them as cosmetic text.
They may explain:

- small or uneven group counts,
- missing numeric measurements,
- metrics excluded by comparability policy,
- chart or histogram coverage limits,
- grouping assignments that did not match exported rows, or
- scope mismatches between the requested analysis and exported data.

If a warning disagrees with a strong-looking chart, trust the warning and inspect the detail before
acting.

### Metric jump list

When metrics are available, the dashboard provides a jump list for the metric blocks. Use it instead
of scrolling through the whole dashboard.

Each metric block includes a **Back to group comparison** control. Use it to return to the jump list
after reading one metric.

### Metric blocks

Each metric block keeps one measured characteristic together. Depending on the export and data, it
can include:

- **Key takeaways**,
- **Metric summary**,
- plots,
- **Detailed tables**,
- descriptive statistics,
- pairwise comparisons,
- distribution difference context, and
- distribution pairwise comparisons.

The dashboard is designed so routine users can stop after the takeaways, summary, notes, and plots.
The detailed tables are there for verification, review, and deeper investigation.

## Reading A Metric Block

### Key takeaways

Read **Key takeaways** first. These cards convert the statistical result into a plain-language
signal. They may describe the main difference, the comparison that matters most, or why the result
is limited.

Use them as orientation, not as a replacement for judgment. A takeaway can tell you where to look;
the warnings, metric summary, and detailed table tell you how much confidence to place in it.

### Metric summary

The **Metric summary** is the next stop. It can show:

- **Spec status**: how the groups relate to specification limits.
- **Restrictions**: whether the metric is fully comparable or limited.
- **Takeaway**: the main reading for the metric.
- **Recommended action**: what the dashboard suggests you review next.
- **Flags**: compact indicators for caution, risk, or notable behavior.

This block is the best place to decide whether the metric is routine, needs review, or should be
escalated.

### Plots

Plots give a fast visual check of the numeric result. Use them to see group separation, spread,
tails, and possible outliers.

Important habits:

- Do not act from a plot alone.
- Compare the plot with the key takeaway and metric summary.
- If the chart is skipped or sparse, use the detailed tables and warnings instead.
- Treat visible overlap as a reason to read the effect size and Delta mean carefully.

### Detailed tables

Open **Detailed tables** when you need the supporting numbers. The dashboard may include:

- **Descriptive stats**: per-group counts, means, spread, medians, ranges, capability fields, fit
  model, fit quality, and flags.
- **Pairwise comparisons**: group A, group B, Delta mean, adjusted p-value, effect size, difference
  label, comment, takeaway, and test rationale.
- **Distribution difference**: context for how the full distributions differ.
- **Distribution pairwise comparison**: pair-by-pair distribution-shape detail when available.

Most training and routine review should start in the dashboard summary and metric blocks. Detailed
tables are secondary unless you are validating a decision, investigating a warning, or preparing a
technical review.

## How To Read Group Comparisons

Pairwise comparisons answer:

> Which specific groups differ from which other groups?

Read the main fields in this order:

1. **Adjusted p-value**
2. **Effect size**
3. **Delta mean**
4. **Difference/comment/takeaway**
5. **Test rationale**

### Adjusted p-value

The **adjusted p-value** answers:

> After accounting for multiple comparisons, how strong is the evidence that the groups are truly
> different?

Simple reading guide:

- **<= 0.05**: evidence supports a difference.
- **> 0.05**: not enough corrected evidence for a confident difference claim.

Important: **not significant** does not automatically mean **the groups are equivalent**. It can
also mean the sample is small, noisy, or uneven.

### Effect size

The **effect size** tells you how large the difference looks in practical terms. Think of it as the
size of the gap, not just whether a test detected it.

Simple reading guide:

- **Small effect**: a detectable difference may exist, but it may not matter much operationally.
- **Moderate effect**: the gap is more noticeable and may matter.
- **Large effect**: the groups are meaningfully separated and usually deserve attention.

Different statistical methods can use different effect-size formulas. You do not need to memorize
the formulas. Read effect size as the dashboard's practical-importance signal.

### Delta mean

**Delta mean** is the difference between average values.

It answers:

> By how much did one group's average move relative to the other?

Simple reading guide:

- **Near zero**: averages are very similar.
- **Positive**: the first group average is higher than the comparison group.
- **Negative**: the first group average is lower than the comparison group.
- **Larger absolute values** mean a bigger average shift.

Delta mean is easy to understand, but it should not be used alone. Two groups can have similar
averages and still differ in spread or shape.

### Difference, comment, and takeaway

These fields translate the statistical result into a short interpretation. They are useful for
quick review, but they depend on the data quality and comparison context.

If the comment says the result is approximate, limited, or cautionary, do not reduce the decision to
the adjusted p-value alone.

### Test rationale

Metroliza chooses the comparison method automatically based on the data. The **Test rationale**
explains why that method was selected or why the result needs caution.

You do not need to choose the test yourself. Your job is to read the outcome, warnings, and action
signals correctly.

## Reading Spec And Capability Context

### Spec status

Spec status connects the statistical result to a manufacturing decision. Even if a difference is
statistically supported, the practical urgency depends on whether the process is comfortably inside
spec, moving toward a limit, or already showing risk.

Typical safe interpretation:

- **Comfortable / within spec**: values appear well inside the required limits.
- **Near limit / watch**: performance may still be acceptable, but margin is getting tight.
- **At risk / out of spec**: this metric needs prompt review.
- **Unavailable / not applicable**: spec limits were not suitable for this calculation.

### Cp / Cpk / capability

Capability metrics describe how comfortably the process fits inside specification limits.

Practical reading guide:

- **Below 1.00**: process performance is usually not comfortably within spec.
- **Around 1.00**: borderline capability; watch closely.
- **Around 1.33 or higher**: often treated as healthier capability in many manufacturing settings.
- **Much higher than 1.33**: more comfort relative to the spec window, assuming the data is
  representative.

Helpful reminders:

- **Cp** reflects potential capability when the process is centered well.
- **Cpk** reflects actual capability after centering is considered.
- For one-sided specs, the dashboard may show a one-sided capability form instead of the usual
  two-sided pair.
- Capability needs caution when sample size is small or the distribution is strongly non-normal.

## Reading Distribution Context

Two groups can have similar averages but still behave differently.

For example, one group may:

- have a wider spread,
- be more skewed,
- have heavier tails, or
- contain more extreme values.

That is why distribution context matters. It helps explain differences that the mean alone would
hide. Treat distribution difference as supporting context alongside adjusted p-value, effect size,
Delta mean, and spec status.

## Skipped Or Insufficient-Data Messages

Sometimes Group Analysis cannot produce a full comparison. That is still a useful result, because
the dashboard tells you why the comparison should not be trusted or cannot be run.

Common messages include:

- **Group Analysis skipped: at least 2 groups are required.**
- **Group Analysis skipped: no numeric MEAS values are available.**
- **Group Analysis skipped: no eligible metrics are available.**
- **Group Analysis skipped: grouping assignments could not be matched to the exported measurement
  rows.**
- **Single-reference group analysis skipped: grouped rows span multiple references.**
- **Multi-reference group analysis skipped: grouped rows span only one reference.**

How to respond:

- If there are fewer than 2 populated groups, fix the grouping or export more data.
- If numeric MEAS values are missing, check parsing and filters.
- If no eligible metrics are available, check characteristic names, aliases, and whether the export
  contains comparable measurements.
- If grouping assignments could not be matched, revisit [Export grouping](../export_grouping.md)
  and confirm that the grouping was built for the exported rows.
- If the selected scope conflicts with the data, use automatic scope or choose the scope that
  matches the number of references in the export.

Do not treat a skipped message as a failed app run. Treat it as a data-readiness message.

## Workbook Details Are Secondary

The normal grouped Export reading path is the dashboard. Standard grouped Export adds
Group Analysis to the HTML dashboard rather than adding extra Group Analysis workbook
sheets.

The workbook remains useful for:

- the main exported measurement sheets,
- selected workbook charts,
- records that need spreadsheet review,
- technical verification of detailed numbers, and
- legacy or internal/debug diagnostics when explicitly enabled.

If a workbook includes a **Group Analysis** sheet or **Group Analysis Plots** sheet, treat it as
a secondary or legacy/debug view of the same analysis. Start with the dashboard first, then open
workbook details only when you need spreadsheet-level review, audit evidence, or troubleshooting.

If a separate **Diagnostics** worksheet appears, treat it as internal/debug information. Routine
users should use the dashboard warnings, run notes, and metric blocks instead.

## Safe Interpretation Checklist

Before you make a process decision, run through this checklist:

- Confirm you are reading the correct metric and correct groups.
- Check warnings and run notes before reading charts.
- Check the sample counts. Very small or very uneven groups need extra caution.
- Read the key takeaway and metric summary before opening detailed tables.
- Read the adjusted p-value first in pairwise rows.
- Read the effect size next.
- Check Delta mean so you know the direction and size of the average shift.
- Look at distribution context if shown; averages are not the whole story.
- Review spec status and capability before deciding operational urgency.
- If the result is borderline, treat it as a signal to review more data, not as proof.
- If significance and practical importance disagree, slow down and investigate.

## Final Takeaway

Group Analysis is meant to help you move from **"Are these groups different?"** to
**"Does that difference matter, and what should I do next?"**

The safest dashboard reading pattern is:

1. **Group comparison summary** for scope, status, and warnings.
2. **Metric jump list** to choose the characteristic.
3. **Key takeaways** for the plain-language signal.
4. **Metric summary** for spec status, restrictions, action, and flags.
5. **Plots** for visual confirmation.
6. **Detailed tables** for adjusted p-value, effect size, Delta mean, and technical review.

If those signals point in the same direction, you can usually act with more confidence. If they
disagree, the dashboard is telling you to slow down, review the cautions, and gather context before
making a decision.
