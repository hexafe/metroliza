# Output choices and request scope

CSV Summary always creates a **Dashboard (HTML)**. Enable **Output workbook
(XLSX)** to also create a workbook, then choose its path. Both paths and the
workbook choice are basic controls; Advanced contains chart/rendering tuning.
CSV Summary does not offer an XLSX-only run.

Export keeps its existing choices: a workbook, a workbook with a Dashboard
sidecar, or the Dashboard-only preset. Grouped exports require the Dashboard
sidecar. Google Sheets remains an upload attempt alongside the local workbook;
it does not replace the local result or guarantee a successful upload.

The pinned **Draft** summary shows the current source, applied filters, grouping
and chosen outputs. It uses existing selection metadata and does not run an
analysis. At launch, **Launch request** describes the validated request actually
handed to the worker, including a destination chosen by **Save a copy**. Full
paths and scope details are available in the summary tooltip. If source/settings
change during an output confirmation, review the new scope and generate again.
The last-result row continues to open only existing, completed artifacts.

Use **Ctrl+S** to generate/export, **Ctrl+Shift+S** to request stop, and
**Ctrl+W** or **Esc** to close through the existing working/draft guards.
**Ctrl+F** opens metric search/selection in CSV Summary or Filters in Export.
These shortcuts apply to the current window; standard text editing remains
available, and a modal child does not trigger its parent's generation command.
The reason generation is unavailable stays beside the pinned actions.
