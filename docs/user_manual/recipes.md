# Recipes

Recipes save a local sequence of supported operations. Open **Receptury** from
the main navigation, or choose a pinned recipe at the top of Home. Pin, unpin
and change the order of recipes in **Wszystkie receptury**. Press Enter on a
selected recipe to open its form. To open Home on launch, clear **View → Open
last workspace on startup**. Return to the same pinned recipe to resume the form
you started. Choose **Zacznij od nowa** to restore its starting values.

## Quick report flows

Choose **Raporty → Excel Main** or **Raporty → Dashboard HTML**, select the report
folder and destination file, check the database path shown below them, then
press Start. `Wyniki/Pomiar.xlsx` and `Wyniki/Pomiar.html` both derive
`Wyniki/Pomiar.db`. The HTML flow does not require a workbook.

Excel Main starts with the same quick metadata mode as Reports. Select the
complete mode under **Tryb importu** when the report metadata needs OCR.
The run view names the current step and shows its elapsed time.

In **Receptury**, choose **Dopisz do bazy → Excel Main** to add reports to a
selected Reports database. Choose the folder, database and workbook. The flow skips reports
already in that database and exports the reviewed reports from the selected
folder, including those already present. With zero new reports, it can
regenerate the workbook from the same selection. If the workbook exists,
the run asks whether to replace it or save a copy.

In a flow that creates a database, a collision requires a decision. Choose a
fresh output family to retain previous results. Ambiguous reports, changed sources and partial
imports also stop for review. Cancellation stops subsequent steps; an import
already committed remains available. Navigation keeps the active task alive.
During review, the table highlights fields that need attention. Clear **Tylko
raporty wymagające uwagi** to inspect every report in the review. Home shows the
current step and a link back to the task. The latest verified Excel or HTML
result can be opened directly from Home while the app is open.

## Your own recipes

Copy a built-in recipe to edit it. Choose **Pytaj przy każdym uruchomieniu**
to enter a value for each run, **Używaj zapisanej wartości** to reuse a value,
or **Ustal automatycznie** to derive the database path from the output.
Choose **Zapisz recepturę** to save all visible choices together, including
dates, grouping and the additional HTML report. The confirmation lists the
report formats. Choose **Zapisz jako nową** to keep a separate recipe. Select **Przypnij do Home po zapisaniu** to pin it at the same
time. A running job retains the plan that was shown when it started.
Changes to the library apply to future runs.

Use **Save as recipe** in CSV Summary, or **Zapisz jako recepturę** in Export, to capture the
configuration. Field mappings and supported group rules must match the selected
source. Manual assignments to specific rows do not transfer to a new source;
resolve the compatibility message before running.

Private names, paths and filter values stay in local bindings in the application
data directory. Recipes run locally. Availability in the catalog reflects the
implemented source adapter and method, and incompatible settings require review.

Packaged Windows qualification and PO acceptance are tracked separately in
[#1239](https://github.com/hexafe/metroliza/issues/1239).
