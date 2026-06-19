# Dashboard Visuals

## What the dialog is for

The **Dashboard visuals** dialog changes how Plotly charts look in the exported HTML
dashboard. It changes chart presentation only. It does not change measurements, filters,
group assignments, statistics, or saved source data.

Open it from Export when **HTML dashboard** is enabled:

1. In the Export dialog, find **Dashboard style**.
2. Click **Change...**.
3. Choose a visual recipe, saved theme, or custom settings.

The exported dashboard also includes its own **Plot Visuals** dialog when interactive
Plotly charts are available. Use it for review-time changes inside the HTML file.

## Start with a recipe

Recipes are complete visual setups. They are the safest choice for routine users because
they adjust colors, group emphasis, markers, lines, and opacity together.

| Recipe | When to use it |
| --- | --- |
| **Metroliza default** | Everyday review when you want the normal Metroliza dashboard look. |
| **Corporate contrast** | Routine reports where comparison groups should stand out clearly from the population. |
| **Accessible groups** | Reviews where color alone should not carry the message, including color-vision accessibility. |
| **Dense group scan** | Many visible groups or busy dashboards where each group needs stronger separation. |
| **Executive report** | Management or customer-facing reports that need quieter, professional colors. |
| **Soft review** | Exploratory reviews and meetings where a calmer palette is easier to scan. |
| **Scientific sequential** | Ordered groups such as process stages, ranked batches, or low-to-high conditions. |
| **Nominal divergence** | Groups that should be read as deviations around a real nominal or target value. |
| **Print mono** | Printed reports, grayscale review, or PDFs where color may not survive. |
| **Highlight story** | A report that needs one highlight color to guide attention through the charts. |
| **Custom** | Exact brand colors, a saved local style, or a special case that recipes do not cover. |

For most exports, choose one recipe and stop there. If reviewers ask for a different
visual emphasis, choose another recipe before editing individual controls.

## Customize versus recipes

Use a recipe when the goal is clear communication with minimal effort.

Use **Customize...** when you need a specific visual result, such as:

- a required company color,
- a group that must be quieter or more prominent than the others,
- a thicker nominal/specification line,
- marker shapes that make overlapping groups easier to separate, or
- a grayscale-safe chart for a printed package.

Selecting a recipe applies a complete set of choices. Manual per-element edits belong to
**Custom**. If you switch from **Custom** back to a recipe, expect the recipe to replace
many manual choices so the charts stay internally consistent.

## Color controls

The dialog can control the chart palette in three common ways:

- **Use color set** keeps a fixed list of colors.
- **Generate gradient** builds a smooth ordered sequence.
- **Around highlight** builds the palette around one highlight color.

The **Differentiate** control decides when Metroliza should add non-color differences:

- **Color only** uses color as the main group signal.
- **When similar** adds markers or patterns when colors are close.
- **Always** uses extra distinction even when colors are already different.

Use color sets for unrelated groups. Use gradients for ordered groups. Use highlight
mode when the report has one main story and supporting groups should remain secondary.

## Lines, markers, and opacity

Fine tuning is for readability, not data editing.

- **Marker size** changes how prominent scatter and point-like traces look.
- **Marker symbol** can separate groups even when colors look similar.
- **Line width** changes statistic, trend, and reference-line emphasis.
- **Line dash** helps distinguish nominal, limit, mean, trend, or review lines.
- **Pattern** can make histogram/bar groups easier to separate in print or grayscale.
- **Opacity** controls how strongly an element shows through other elements.

Use lower opacity for background population points and higher opacity for comparison
groups that should be read first. Use thicker or solid lines for the one reference line
reviewers must notice, and lighter or dashed lines for supporting context.

## Selected chart elements

When the dashboard has interactive Plotly charts, the selected-element controls can style
one chart element at a time. The available controls depend on what you selected:

- histogram or bar elements can expose color, opacity, and pattern,
- scatter points can expose color, opacity, marker size, marker symbol, and outline,
- line-like elements can expose color, opacity, width, and dash, and
- reference or statistic lines can be edited without changing the underlying statistic.

Per-element opacity is useful when one group hides another. It lets you make a single
series lighter or stronger without changing the rest of the recipe.

## Marking Individual Points

In an exported interactive Plotly dashboard, click a point and open **Plot Visuals**. The
**Point marks** section shows the selected point, lets you choose a mark color, and can
add or clear a visible point marker. Point marks are saved in the browser for that HTML
dashboard and do not change the exported data, the source database, or trace styling.

Use **Find point** when you know a `TraceCode`, sample number, or another point value.
The **Search in** dropdown controls which point fields are searched. It defaults to
**TraceCode / record key** when point metadata is available, otherwise to **Any field**.
**Next** and **Previous** move through matches in chart order, then trace order, then
point order. The navigation wraps around at the end or beginning. Each selected match is
temporarily highlighted; click **Mark selected point** to save it as a persistent point
mark.

Point search can use the visible series name, x-axis value, y-axis value, and point
details carried by the dashboard. This is useful when a reviewer wants to call out one
assembly, sample, or TraceCode without changing the chart recipe for the whole series.

Point marks work on interactive Plotly charts. They do not repaint static image snapshots
or older dashboard files that were exported before point-mark controls existed. Export the
dashboard again when you need point marking in an older HTML file.

## Static and pre-rendered colors

Some dashboard visuals are pre-rendered before the HTML file is opened. This can happen
for image snapshots, static raw-point layers, or dashboards that fall back to snapshots
because of size limits, static mode, or missing interactive chart support.

Those static pieces use the dashboard visual colors that were resolved at export time.
The live **Plot Visuals** dialog can restyle interactive Plotly traces, but it cannot
repaint an already rendered image snapshot. If a static image needs a different color,
change the dashboard visuals before export and export the dashboard again.

## Practical choices

- For a routine grouped export, start with **Corporate contrast**.
- For many small groups, try **Dense group scan**.
- For a printed review, use **Print mono** and check that markers or patterns still
  separate the groups.
- For a process-stage story, use **Scientific sequential**.
- For a target-centered story, use **Nominal divergence**.
- For one important group, use **Highlight story** or **Custom** and keep supporting
  groups quieter.
