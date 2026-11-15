# Recipes

Recipes save a local sequence of supported operations. Open **Receptury** from
the main navigation, or choose a quick flow at the top of Home.

## Quick report flows

Choose **Raporty → Excel Main** or **Raporty → Dashboard HTML**, select the report
folder and destination file, check the database path shown below them, then
press Start. `Wyniki/Pomiar.xlsx` and `Wyniki/Pomiar.html` both derive
`Wyniki/Pomiar.db`. The HTML flow does not require a workbook.

An existing database or output requires a decision. Choose a fresh output family
to retain previous results. Ambiguous reports, changed sources and partial
imports also stop for review. Cancellation stops subsequent steps; an import
already committed remains available. Navigation keeps the active task alive.

## Your own recipes

Copy a built-in recipe to edit it. The editor lists supported steps and parameter
modes: fixed, ask when running or derive using an available rule. Save a copy or
a new revision. A running job retains the plan that was shown when it started.
Changes to the library apply to future runs.

Use **Zapisz jako recepturę** in a supported analysis/export window to capture its
configuration. Field mappings and supported group rules must match the selected
source. Manual assignments to specific rows do not transfer to a new source;
resolve the compatibility message before running.

Private names, paths and filter values stay in local bindings in the application
data directory. Recipes run locally. Availability in the catalog reflects the
implemented source adapter and method, and incompatible settings require review.

Packaged Windows qualification and PO acceptance are tracked separately in
[#1239](https://github.com/hexafe/metroliza/issues/1239).
