# Group Comparison Toolkit Extraction

## Goal

Make the current Group Analysis logic reusable outside Metroliza so the same comparison engine can be applied to:

- report exports inside Metroliza,
- EOL / production datasets,
- supplier-vs-supplier studies,
- line / shift / machine / operator comparisons.

The target state is:

- a standalone package that owns comparison-domain logic,
- thin adapters inside Metroliza for workbook/dashboard/UI export,
- input data mapped into a stable toolkit contract instead of being tied to current export-frame column names.

## Recommendation

Do this as an extracted Python package, not as a hard split of the current codebase in one step.

Preferred rollout:

1. Define a stable toolkit API inside Metroliza first.
2. Move pure comparison logic behind that API.
3. Extract the package into a separate repo only after the API and tests are stable.

That avoids creating a second repo while the interface is still moving with export-specific assumptions.

## What belongs in the standalone toolkit

These parts are good extraction candidates because they are domain logic, not Metroliza UI/export plumbing:

- statistical comparability policy,
- per-group descriptive statistics,
- pairwise comparison computation,
- distribution-difference computation,
- capability summary logic,
- metric-level diagnostics, flags, takeaways, and recommended actions,
- normalized result schemas for summary rows, pairwise rows, diagnostics, and plot-ready grouped values.

Current likely homes:

- `modules/group_analysis_service.py`
- `modules/comparison_stats.py`
- `modules/distribution_shape_analysis.py`
- `modules/stats_utils.py`

The toolkit should return structured payloads. It should not know about:

- Qt,
- Excel writers,
- HTML rendering,
- Metroliza sheet layout,
- Metroliza-specific completion messaging,
- database access,
- report-parser internals.

## What should stay in Metroliza

These are application adapters and should stay local:

- workbook writers and sheet formatting,
- HTML dashboard rendering,
- image generation for workbook insertion,
- export-dialog options and presets,
- SQLite query/build steps,
- report-specific alias resolution and grouping UI,
- current `ExportDataThread` orchestration.

Current likely homes:

- `modules/export_data_thread.py`
- `modules/group_analysis_writer.py`
- `modules/export_html_dashboard.py`
- `modules/export_dialog.py`
- `modules/export_query_service.py`

## Proposed package contract

Use a neutral dataset contract instead of passing the current export dataframe shape directly.

Suggested top-level API:

```python
from group_comparison_toolkit import build_group_comparison_payload

payload = build_group_comparison_payload(
    rows=dataframe,
    schema={
        "metric": "metric_name",
        "group": "supplier",
        "value": "measurement_value",
        "reference": "reference_id",
        "lsl": "lsl",
        "nominal": "nominal",
        "usl": "usl",
    },
    scope="single_reference",
    analysis_level="standard",
)
```

Principles:

- the toolkit accepts column mapping explicitly,
- it does not assume report-specific column names like `HEADER - AX`,
- it returns pure Python payloads,
- it includes plot-ready grouped values but not rendered images.

## Suggested internal package layout

```text
group_comparison_toolkit/
  __init__.py
  api.py
  schema.py
  normalization.py
  policies.py
  descriptive.py
  pairwise.py
  distribution.py
  capability.py
  narratives.py
  plots.py
```

Expected responsibilities:

- `schema.py`: input/output contracts and validation.
- `normalization.py`: normalize incoming rows using a caller-provided schema map.
- `policies.py`: spec comparability and analysis restrictions.
- `descriptive.py`: descriptive stats by group.
- `pairwise.py`: pairwise statistical engine.
- `distribution.py`: shape-difference logic.
- `capability.py`: Cp/Cpk/Cpu/Cpl style summaries.
- `narratives.py`: diagnostics, flags, takeaways, actions.
- `plots.py`: plot-ready grouped vectors and normalized plot metadata.

## Extraction sequence

### Phase 1: Stabilize in-place

- Introduce a narrow facade in Metroliza, for example `build_group_comparison_payload(...)`.
- Keep implementation local for now.
- Add tests that assert only the facade contract, not internal module paths.

### Phase 2: Remove Metroliza-specific assumptions

- Replace direct dependence on export-frame column names with schema mapping.
- Move alias resolution out of the core payload builder or make it an optional pre-processing step.
- Separate narrative text from workbook-only layout concerns.

### Phase 3: Extract repo

- Create a new repo, for example `group-comparison-toolkit`.
- Copy the stabilized core modules and contract tests.
- Publish as an internal package first.
- Pin Metroliza to tagged releases of that package.

### Phase 4: Rewire Metroliza

- Metroliza imports the toolkit payload builder.
- Existing writers keep consuming the payload.
- Any Metroliza-only decoration remains in local adapter code.

## Dependency approach

Keep the toolkit dependency-light:

- `numpy`
- `pandas`
- `scipy`

Avoid toolkit dependencies on:

- `PyQt6`
- `XlsxWriter`
- `matplotlib`
- `seaborn`

If interactive browser plots are needed later, expose plot-ready normalized data or optional Plotly specs, but keep rendering optional and separate from the statistical core.

## Versioning and compatibility

The extracted package should use semantic versioning with a strict payload contract.

Metroliza-side rule:

- payload schema changes in the toolkit must be treated as integration changes,
- workbook/dashboard adapters should pin to a compatible toolkit release range,
- contract tests in Metroliza should run against the pinned version.

## Immediate next steps

1. Introduce a new neutral facade name in Metroliza, separate from workbook wording.
2. Add a schema-mapping layer so non-report datasets can call the same engine.
3. Move workbook/html writers to consume only the facade payload.
4. Once the facade is stable across report and EOL/supplier use cases, extract the repo.

## Non-goal

Do not split the repo immediately by copying `group_analysis_service.py` as-is into a new package. Right now it still carries Metroliza naming and export-shape assumptions. Extracting before stabilizing the contract would freeze the wrong interface.
