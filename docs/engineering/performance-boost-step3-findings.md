# Załącznik A — wszystkie znaleziska GPT (126) z werdyktem koordynatora

Werdykt: **Z** zweryfikowane pomiarem/PoC (wynik identyczny), **K** mechanizm potwierdzony w kodzie przez koordynatora, **W** wiarygodne (mechanizm i mikropomiar GPT, niesprawdzone osobno), **D** wymaga decyzji PO, **S** spekulatywne lub marginalne. Szacunki oszczędności są przepisane z ustaleń GPT (po angielsku, z ich podstawą) i nie sumują się — wiele się nakłada.

Rozkład werdyktów: D 1, K 7, S 21, W 91, Z 6.

## S3-1 — Extended: wykresy podsumowań (12)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A01-F01 | Z | `exporting/export_data_thread.py:3245` render_panel_table._measure_layout | spawn | S | Approximately 6-10 s (9-14%) of the 68.8 s Extended flow, if the profiled share transfers to the existing pool. Basis: remove roughly 65-98% of the 13.85% la… |
| A01-F02 | W | `exporting/export_data_thread.py:1029` render_histogram_annotations | spawn | M | Approximately 1-3 s (1.5-4.5%) of the 68.8 s Extended flow. Basis: 6.51% profiled inclusive share times a conservative 25-65% removable portion (synthetic he… |
| A01-F03 | K | `exporting/export_data_thread.py:2934` render_density_line | spawn | S | Approximately 0.4-1.5 s (0.6-2.2%) of Extended with seaborn and 216 fitted curves; zero when seaborn is absent/no curve. Basis: ~19 ms/curve synthetic setup … |
| A01-F04 | W | `exporting/export_data_thread.py:462` _numeric_array | spawn | S | Approximately 0.05-0.4 s (<1%) of Extended at the supplied 216k-row scale; possible additional allocation reduction. Basis: ~0.18 CPU s per 216k typed values… |
| A02-F01 | Z | `exporting/export_data_thread.py:6490` ExportDataThread.summary_sheet_fill | worker | M | Approximately 3-10 s (4-15% of the 68.8 s Extended flow) if Plotstats succeeds for these charts; lower if adapter fallback is frequent. Geometry alone sugges… |
| A02-F04 | W | `exporting/export_data_thread.py:4695` ExportDataThread._apply_group_assignments | worker | M | Approximately 0.2-1.5 s on the grouped 216-header/1500-report scale, plus lower IPC allocation; 0 s with no grouping. This is a planning range, not a measure… |
| A02-F06 | W | `exporting/export_data_thread.py:6088` ExportDataThread._sample_column_for_width | worker | S | Approximately 0.05-0.4 s for a 216000-row, ~30-column non-streamed export, with smaller temporary allocation. Approximately 0 s in the supplied streaming Mai… |
| A03-F02 | W | `exporting/export_summary_render_pool.py:243` SummaryRenderPool.iter_results | worker | M | 0-1 s for one large reference; approximately 1-10 s for 4-16 references at ~1 s/group by parallelizing R-1 avoidable serial groups, plus possible tail utiliz… |
| A03-F04 | W | `exporting/export_summary_utils.py:30` _to_numeric_array | worker | S | Approximately 0.25-0.32 s CPU per redundant 216k-value pass; about 0.1-1.0 s wall time across Extended/HTML depending on worker count and passes, or 0.2-1.5 … |
| A04-F01 | Z | `charts/chart_renderer.py:348` PlotstatsChartRenderer.render_distribution_png / | spawn | L | 2-6 s of the 68.8 s Extended flow (roughly 3-9%), conditional on retaining current PNG and dashboard geometry. Planning estimate: avoid a modest part of non-… |
| A04-F06 | S | `charts/hexafe_plotstats_adapter.py:652` render_chart_artifact_png / build_chart_artifact | spawn | M | 0-0.8 s of the 68.8 s Extended flow as a low-priority planning range (0-1.2%); zero remains possible if rendering dominates or PNGs are simple. Do not claim … |
| B01-F01 | W | `charts/chart_render_spec.py:39` _resolve_violin_density_shape | worker | S | ~0.1–0.6 s from first cold export setup if SciPy is not already loaded; no change to warm export or total export computation expected. |

## S3-2 — Main: dane partycji i zapis arkuszy (7)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A02-F02 | Z | `exporting/export_data_thread.py:4096` ExportDataThread._iter_reference_partitions | worker | M | Approximately 0.8-2.5 s (3-9% of 27.7 s Main); include index construction and existing row-table conversion in the comparison. Potentially much larger for ma… |
| A02-F03 | W | `exporting/export_data_thread.py:4657` ExportDataThread._sort_header_group | worker | S | Approximately 0.6-1.5 s (2-5% of 27.7 s Main), based on reducing only part of the 9% sort share. Additional scoped normalization reuse could help but is not … |
| A02-F05 | W | `exporting/export_data_thread.py:5183` ExportDataThread.add_measurements_horizontal_she | worker | M | Approximately 0-0.5 s total flow latency through overlap; first chart submission could start roughly 0.5-2 s earlier for a single large reference. Main benef… |
| A03-F05 | W | `exporting/export_backends.py:565` _extract_table_columns_and_rows | worker | M | Roughly 0.3-1.2 s and 80-275 MB transient memory on a 216k x 38 DataFrame-backed sheet; 0 s on the already streamed default Main flow. Chunking retains compa… |
| A09a-F06 | S | `reports/report_query_service.py:536` _append_industrial_context_to_export_query | worker | M | 0 s for standard export; provisional 0.1-1.0 s for 216000-row industrial-context export with several candidates/report. Validate before scheduling; may be ne… |
| A18-F02 | W | `analytics/row_table.py:283` RowTable.__getitem__ / RowTable.drop | worker | M | 0.5-1.1 s (roughly 2-4% of the 27.7 s Main baseline), assuming 40-80% of the approximately 5% materialization envelope is removable. Extended may benefit, bu… |
| B04-F01 | Z | `exporting/export_query_service.py:245` load_export_partition_dataframe | worker | M | ~1–8 s (roughly 4–29% of the 27.7 s flow); estimate only, from avoiding repeated scoped scans/materializations across partitions. |

## S3-3 — Pakowanie XLSX (2)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A03-F01 | D | `exporting/export_backends.py:612` ExcelExportBackend.close_writer | worker | M | LIKELY 3-7 s (11-25%) of the 27.7 s Main flow, if real-data close has comparable compression share: 27.7 * 0.53 * roughly 0.2-0.45. No reliable Extended esti… |
| A03-F06 | W | `exporting/export_sheet_writer.py:293` create_measurement_formats | worker | S | 0-0.01 s per normal export; bounds retained format-cache memory to the active workbook and prevents invalid XLSX styles/rework. No seconds-level gain or meas… |

## S3-4 — CSV analytics: dashboard (14)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A04-F02 | W | `charts/hexafe_plotstats_adapter.py:575` build_plotstats_dashboard_spec / build_chart_art | GUI | M | About 1-2.5 s of synchronous preview work per histogram refresh (five unused fits requested twice; warm-fit timing still needed); 0.5-4 s per grouped analyti… |
| A04-F03 | W | `charts/chart_numeric_helpers.py:53` finite_float_list / finite_array / _raw_numeric_ | worker | M | 2-4 s (roughly 6-11%) of the 35.4 s CSV analytics flow if numeric fast paths remove 40-75% of the profiled 15% bucket. Export saving unquantified because pay… |
| A04-F04 | W | `charts/hexafe_plotstats_adapter.py:2538` _canonical_legend_key / _constant_line_axis_and_ | worker | S | 1-2 s (roughly 3-6%) of CSV analytics, assuming most 6% is ordinary data trace rejection. Overlaps F03 numeric coercion: after F03 the incremental saving is … |
| A04-F05 | W | `charts/hexafe_plotstats_adapter.py:1530` _payload_with_resolved_histogram_bin_count / _en | worker | M | 0.1-0.6 s of CSV analytics for eight metrics at present sample limits; more at large group counts. This is an additional pass-count opportunity, not an extra… |
| A11-F01 | W | `industrial/industrial_analytics_dashboard.py:1740` _build_time_series_charts | worker | M | 1.5-3.5 s (~4-10% of the 35.4 s CSV analytics flow) when auto/static group layers replace these traces; near zero for explicitly interactive layers. Estimate… |
| A11-F02 | W | `industrial/industrial_analytics_dashboard.py:356` write_production_dashboard | worker | M | 0.8-2.0 s (~2-6% of CSV analytics) and fewer payload-sized transient allocations; 1.5 s redundant measurement time in the synthetic 15.7 MB case before clone… |
| A11-F03 | W | `industrial/industrial_analytics_dashboard.py:2849` _render_matplotlib_distribution_image | worker | S | LIKELY 0.2-0.8 s (~0.6-2.3% of CSV analytics), with potentially larger gains for dense/high-entropy images. The measured synthetic encoding difference is onl… |
| A11-F04 | W | `industrial/industrial_analytics_dashboard.py:3249` _sample_allocations | worker | S | 0 s material saving for the usual few groups; 0.29-4.27 s per allocator invocation at 1,600-3,200 groups in the synthetic checks. Repeated chart/metric calls… |
| A11-F05 | S | `industrial/industrial_analytics_dashboard.py:4733` _render_plotly_runtime | worker | M | 0.5-5 s less first-open blocking for dashboards with tens of substantial offscreen charts; unvalidated estimate and no claimed Python analytics speedup. Tota… |
| A11-F07 | W | `industrial/industrial_analytics_dashboard.py:2903` _chart_payload | worker | M | 0.5-2 s avoidable raw-trace preparation for eight 50k-point charts in Snapshots only mode; net full-flow improvement is UNKNOWN until the required time-serie… |
| B02-F01 | W | `charts/dashboard_visual_options.py:775` dashboard_visual_group_names_from_grouping_frame | GUI | S | 0.05–0.8 s on a 100k-row frame; proportional to row count and Python normalization cost, not measured in this audit. |
| B02-F02 | W | `charts/dashboard_plotly_visuals.py:107` apply_dashboard_visual_settings | worker | M | 0.05–1.5 s across a large multi-chart export with hundreds of groups; estimated from removing repeated label scans, not measured. |
| B03-F01 | W | `charts/export_html_dashboard.py:609` _write_export_html_dashboard_generation | spawn | S | About 0.05–0.5 s per dashboard when it contains hundreds of specs or several MB of Plotly data; lower for small dashboards. Estimate is unmeasured and scales… |
| B03-F02 | W | `charts/export_html_dashboard.py:315` summarize_dashboard_chart_payload | spawn | S | About 0.1–0.8 s for a dashboard with roughly 100–500 histogram charts and large series; much less for a small dashboard. Estimate is unmeasured and scales wi… |

## S3-5 — CSV Summary: skoroszyt i walidacja grupowania (4)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A05-F05 | S | `tabular/tabular_analytics_service.py:1558` list_tabular_excel_sheets | GUI | M | Plausible 0.05-0.5s of GUI blocking avoided per ordinary large-workbook selection, potentially >1s for large shared-string workbooks; unmeasured, no gain for… |
| A06-F01 | K | `tabular/contracts.py:119` _record_value / validate_grouping_assignments | GUI | M | About 0.02-0.04 s before report export for 1500 assignments; about 2-4 s of pre-start GUI blocking and 2-5 s total for tabular analytics IF approximately 100… |
| A10-F01 | K | `industrial/industrial_workers.py:352` IndustrialAnalyticsThread.__init__ | GUI | M | 0.8-1.5 s GUI stall removed at this constructor alone for 100k assignments; 2.5-5.0 s total including 2-4 s before worker start if the coordinator also remov… |
| A15a-F04 | S | `ui/industrial_analytics_dialog.py:1617` IndustrialAnalyticsDialog._populate_tabular_shee | GUI | M | Estimated 0.05-2.0 s of GUI blocking on large Excel selection; approximately 0 s on the measured CSV scenario. Moving metadata discovery changes responsivene… |

## S3-6 — Import i Review: parsowanie i zapis (17)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A07-F01 | W | `parsing/report_parser_factory.py:765` _probe_with_cache | worker | M | 0 s for 1500 PDFs/one compatible plugin with intact cache; conditional planning range 1-8 s per 1500-file import with >=2 compatible plugins, by eliminating … |
| A07-F02 | K | `parsing/report_parser_factory.py:1330` _ensure_external_plugins_loaded_once | worker | M | Estimated 0.4-0.8 s (4-8% of 9.6 s import), assuming 40-80% of the observed 10% refresh share can be removed; profile times under external load are not scale… |
| A07-F03 | W | `parsing/parse_reports_thread.py:1755` ParseReportsThread._selected_enrichment_identity | worker | S | LIKELY 0.15-0.35 s at 1500 accepted reports, 2-5 s at 6000; 0 s when background enrichment is disabled. The optional OCR flow can take minutes, so this is a … |
| A07-F04 | W | `parsing/report_parser_factory.py:1651` invoke_parser_factory | worker | S | Approximately 0.03-0.10 s per 1500-file import; quick metadata/fresh Review benefit is similarly small and depends on which optional keywords are passed. Do … |
| A07-F05 | S | `parsing/parse_reports_thread.py:734` _parse_new_reports | worker | M | 0-0 s claimed throughput improvement; the defensible target is bounded memory, not an established latency win. Potential paging/OOM avoidance and cancellatio… |
| A08a-F01 | W | `parsing/review_pool.py:372` read_metadata_in_order | spawn | M | 15-30% of the pooled quick-metadata operation for 1500 CMM PDFs (planning estimate, medium confidence). A corresponding unprofiled quick-metadata wall baseli… |
| A08a-F02 | W | `parsing/cmm_report_parser.py:803` CMMReportParser.open_report | worker | M | 15-25% of warm quick-metadata flow at the supplied 1500 three-page PDF scale; up to the 28% profile-share ceiling for non-header open work. No gain to prefli… |
| A08a-F03 | W | `cmm/block_parser.py:37` _normalize_status_token | spawn | S | About 0.2-0.6 s (2-7%) of the supplied 8.4 s Review scan, planning estimate: 18.6% parser micro improvement x 46% worker-service share gives ~8.6% service up… |
| A08a-F04 | W | `parsing/cmm_report_parser.py:689` CMMReportParser._extract_first_page_header_items | worker | M | 3-8% of quick-metadata flow at 1500 PDFs, likely lower for tiny first pages; potential memory reduction for image-heavy headers. Import prepare also benefits… |
| A08b-F01 | W | `parsing/header_ocr_geometry.py:94` _block_candidates | worker | M | Approximately 5-8% of the profiled in-process quick-metadata worker stage if 60-90% of this cost disappears. No defensible pooled end-to-end seconds estimate… |
| A08b-F02 | K | `parsing/declarative_parser_profiles.py:1499` profile_store_signature | worker | M | Approximately 3-6% of import worker time by removing redundant checks and path reconstruction; a proportional planning translation is ~0.3-0.6 s of the 9.6 s… |
| A08b-F04 | W | `parsing/declarative_parser_profiles.py:871` parse_profile_result | worker | S | ~0.05-0.15 s per 1500 declarative reports with 144 short rows and one pattern; more with many specs/long text, not quantified. Zero claimed for the supplied … |
| A09a-F01 | W | `reports/report_repository.py:1548` ReportRepository._replace_full_report_payload | worker | M | 0.4-1.2 s (4-13% of 9.6 s import), LIKELY if preparation has spare parallel capacity; serial fallback may gain little. Not benchmarked end to end. |
| A09b-F01 | W | `reports/header_ocr_corrections.py:132` compact_token | spawn | S | Estimated 0.3-0.8 s (4-10%) of the measured 8.4 s Review-1500 journey, pending complete pooled-flow validation; 0.755 s saved in isolated synthetic metadata … |
| A12-F01 | W | `ui/report_planner_model.py:386` ReportPlannerModel._row_changed | GUI | M | LIKELY 0.05-0.20s GUI work for a 1500-report pooled Review/quick-read phase, 0.10-0.40s for less-coalesced in-process feedback, plus shorter worst flushes un… |
| A12-F02 | W | `ui/metadata_review_worker.py:59` MetadataReviewThread._on_progress | worker | M | LIKELY 0.005-0.05s per 1500-file pass from bounded producer batches/progress deduplication, potentially 0s end-to-end when overlapped. Main benefit is boundi… |
| A13-F01 | W | `ui/ui_foundation.py:614` finalize_window_size | GUI | S | LIKELY 0.02-0.10 s per 1500-file import, 0.005-0.04 s per Review and 0.005-0.05 s Main export in cumulative GUI work; potentially 0.02-0.15 s Extended with i… |

## S3-7 — SQL i ładowanie w oknach dialogowych (22)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A05-F01 | K | `tabular/tabular_analytics_service.py:2555` _update_metric_stats_from_row | worker | M | Approximately 0.7-1.4s (15-30% of the measured 4.71s CSV-load flow), estimated by removing 45-65% of stats work plus redundant display/row bookkeeping; not a… |
| A05-F03 | W | `tabular/tabular_analytics_service.py:2488` _parse_tabular_numbers | worker | M | Approximately 0.05-0.2s (1-4% of 4.71s CSV load) for the observed fallback workload; little/no gain on all-valid data. Upper bound constrained by the supplie… |
| A05-F04 | W | `tabular/tabular_analytics_service.py:1933` _load_tabular_files_into_sqlite | worker | S | Approximately 0.05-0.2s (1-4% of 4.71s CSV load) by reusing about one of two per-row parses/formats. Conditional on a timestamp source column; savings could … |
| A05-F06 | W | `tabular/tabular_analytics_service.py:1145` TabularSqliteStore.date_bounds | GUI | S | Approximately 0.02-0.08s of GUI stall per repeated 100k-row bounds request; 0.2-0.8s is a scale-based projection at 1M rows, not a measurement. Initial retri… |
| A05-F07 | W | `tabular/tabular_analytics_service.py:848` TabularSqliteStore.has_rows_for_group_search | GUI | S | Approximately 0.03-0.08s of GUI stall per 100k-row existence request with an early match; less/no gain for missing or late matches. Larger data can amplify i… |
| A06-F04 | W | `tabular/grouping_assignment_store.py:341` TabularGroupingAssignmentStore._prepare_effectiv | GUI | S | Approximately 0.015-0.030 s per count refresh and 0.006-0.010 s per member selection at 100k assigned rows. Larger tables scale with scanned assignments; no … |
| A06-F05 | W | `tabular/data_grouping_service.py:242` build_grouping_row_index (identical filtered/ful | GUI | S | Approximately 0.01-0.02 s per no-filter invalidation/open at 1500 reports, including GUI-stall reduction; profile supports roughly 11 percentage points of th… |
| A09a-F02 | Z | `reports/report_query_service.py:665` _distinct_filter_scope | worker | M | 0.5-0.9 s (39-70% of 1.29 s first filter open), medium transfer estimate; cache hits already cheap. Synthetic query-only saving measured 1.18-1.33 s. |
| A09a-F03 | W | `reports/characteristic_mapping_service.py:120` _metric_source_cte | worker | S | 0.2-0.35 s (25-44% of 0.8 s mapping open), medium transfer estimate from a 46-55% reduction in the 78% hotspot; not end-to-end measured. |
| A09a-F07 | W | `reports/report_schema.py:843` ensure_report_schema._ensure_schema | GUI | M | Near 0-0.02 s on measured modern MDB open; provisional 0.2-2 s per ensure on an upgraded 216000-measurement legacy database, plus a full legacy result alloca… |
| A09b-F04 | W | `storage/industrial_schema.py:458` ensure_industrial_data_schema | worker | M | Estimated 0.001-0.01 s per warm explicit-connection ensure on an uncontended local DB, plus avoiding an unnecessary writer lock; no substantial gain claimed … |
| A10-F02 | K | `industrial/industrial_tabular_bridge.py:747` _insert_dynamic_value_facets | worker | M | 0.5-1.8 s of the 5.73 s bridge flow on sparse inputs (roughly 9-31%); 36% profile share sets an approximately 2.1 s upper envelope, not a guaranteed saving. … |
| A10-F03 | W | `industrial/industrial_tabular_bridge.py:673` _insert_base_value_facets | worker | M | 0.6-1.0 s from initial 5.73 s bridge open (10-17%) by deferring unused base facets; this is shifted work if the user later opens every column. Total all-colu… |
| A10-F04 | W | `industrial/industrial_tabular_bridge.py:780` _dynamic_field_metadata | worker | M | 0.3-0.9 s of bridge open (5-16%) on repeated-value inputs; near zero or negative for mostly unique real-valued measurements. Estimate is conditional, not 34%… |
| A10-F05 | W | `industrial/industrial_tabular_bridge.py:888` _create_industrial_tabular_view | worker | M | 0.05-0.3 s of bridge preview plus roughly 0.5-2.0 s per full 100k-row count/projected read with 20 mostly-unused fields, based on the 20k probe. Filter-selec… |
| A10-F09 | W | `industrial/industrial_tabular_bridge.py:520` _metadata_scope_fingerprint | worker | M | 0 s direct latency saving; correctness prerequisite for retaining or expanding the facet caching in A10-F03. Selectively invalidating source-label facets can… |
| A14-F04 | W | `ui/data_grouping.py:1076` DataGrouping._ensure_group_color_integrity | GUI | M | 0.2-0.45 s per population of 1500 rows/216 assigned groups; near 0 s for one default group. Overlaps the population component of F03; do not sum that compone… |
| A14-F05 | W | `ui/data_grouping.py:1687` DataGrouping.populate_list_widgets | GUI | S | 0.04-0.09 s GUI/flow saving per first open (about 6-15% of 0.62 s); similar duplicate-work saving on refresh, depending on selected-group size. Does not incl… |
| A14-F06 | W | `ui/modify_db.py:513` ModifyDB.populate_tables | GUI | M | 0.03-0.09 s initial-open time/stall saving by deferring hidden tabs and removing per-cell construction; worker queries mainly reduce blocking. More for high-… |
| B05-F01 | W | `industrial/industrial_join_service.py:314` materialize_industrial_report_links | GUI | M | About 0.1–5 s of GUI stall per refresh for tables in the several-thousand to tens-of-thousands row range if the join is scan-bound; unmeasured and may be neg… |
| B07-F01 | W | `shared/grouping_filter_core.py:276` DataFrameGroupingIndex._preview_frame | GUI | S | 0.05–0.25 s (about 8–40% of the measured 0.62 s Grouping-open flow) on a high-cardinality in-memory dataset; smaller on low-cardinality data. |
| B08-F01 | W | `ui/industrial_filter_dialog.py:188` IndustrialFilterDialog.load_database_references | GUI | M | 0.02–0.3 s of GUI stall per click at ~1,500 reports (estimate; unprofiled); scales with report count |

## S3-8 — Responsywność GUI przy dużym grupowaniu (20)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A05-F02 | W | `tabular/tabular_analytics_service.py:1029` TabularSqliteStore.count_source_row_numbers | GUI | M | Approximately 0.1-0.4s of GUI blocking per 100k fully assigned rows across repeated summary refreshes; depends on refresh count, assignment representation, f… |
| A06-F02 | W | `tabular/grouping_assignment_store.py:543` _selected_key_predicate / TabularGroupingAssignm | GUI | M | At 100k rows: approximately 0.5-0.7 s for 50 keys on an unindexed/non-indexable scope; approximately 0.15-1.8 s for 800 indexed keys depending on planner sta… |
| A06-F03 | S | `tabular/data_grouping_service.py:106` load_grouping_dataframe (synchronous reopen call | GUI | M | Provisionally 0.02-0.30 s less GUI blocking per report-scale reopen by moving SQL/DataFrame read off-thread; roughly unchanged total work. This low-confidenc… |
| A08b-F03 | W | `parsing/parser_profile_handoff.py:532` validate_profile_handoff | GUI | M | Roughly 0.05-0.08 s and 0.6-0.8 s of uninterrupted GUI occupation for the two synthetic sizes, by moving the work to an owned worker. Total operation time ne… |
| A09a-F04 | W | `reports/characteristic_mapping_service.py:294` fetch_mapping_impact_counts | GUI | M | About 0.1-0.2 s of GUI blocking removed per query on this fixture (10 edits currently about 1-2 s of aggregate event-loop occupancy); little total compute sa… |
| A09a-F05 | W | `reports/report_repository.py:1443` ReportRepository.update_measurement_fields._upda | GUI | M | At most 0.01-0.05 s on supplied small apply; estimated 0.2-3 s latency/GUI occupancy for a 1000-edit batch, low confidence in seconds. Moving the existing wo… |
| A09b-F02 | W | `reports/report_edit_service.py:241` ReportEditService.apply_record_updates | GUI | M | Estimated 0.3-0.7 s total Apply time per 1000 similar edits from connection reuse alone (synthetic delta 0.546 s). Moving persistence to a worker also remove… |
| A09b-F03 | W | `reports/characteristic_alias_service.py:552` import_characteristic_aliases_csv | GUI | M | Estimated 0.08-0.2 s of GUI blockage per 10000-row valid CSV for service work alone, based on 0.104s synthetic import; asynchronous execution mainly improves… |
| A14-F01 | W | `ui/data_grouping.py:2077` DataGrouping._select_visible_parts_for_grouping | GUI | S | 1.5-2.1 s GUI stall per selecting 1000 visible parts in this synthetic shape; proportionally smaller for short references. Not part of the supplied first-ope… |
| A14-F02 | W | `ui/characteristic_mapping_dialog.py:398` CharacteristicAliasEditorDialog._refresh_impact_ | GUI | M | 0.05-0.20 s GUI blocking per resolved edit; roughly 0.3-1.5 s avoided work for a 10-keystroke name after coalescing (plus responsiveness while the remaining … |
| A14-F03 | W | `ui/data_grouping.py:976` DataGrouping.refresh_data | GUI | M | 0.2-0.6 s less GUI blocking per 1500-report reopen is a planning range; near 0 s guaranteed total-flow reduction. Avoiding a redundant in-flight refresh can … |
| A15a-F01 | W | `ui/industrial_analytics_dialog.py:2081` IndustrialAnalyticsDialog._tabular_grouping_has_ | GUI | M | Approximately 0.4-0.6 s per unchanged grouped UI refresh at 100k assignments, 0.8-1.1 s at 216k, after the first valid summary. Up to the same GUI stall remo… |
| A15a-F03 | W | `ui/industrial_analytics_dialog.py:1573` IndustrialAnalyticsDialog._tabular_filtered_row_ | GUI | M | Estimated 0.02-0.5 s of GUI blocking per new filter at 100k rows; complex expressions/wide SQLite views can exceed this. Count-only pandas mask evaluation co… |
| A15b-F01 | W | `ui/tabular_analytics_grouping_dialog.py:1380` TabularAnalyticsGroupingDialog._apply_group_assi | GUI | S | 3.5–4.2 s per 100k-assignment / 216-group restore; larger N/G scale worse. Do not add the full 7.248 s to F02. |
| A15b-F02 | W | `ui/tabular_analytics_grouping_dialog.py:847` TabularAnalyticsGroupingDialog._selector_color_m | GUI | M | 1.1–1.3 s per 100k-row selector repaint; roughly 2–3 s of duplicate color work on a 100k saved-assignment restore. These are alternative stages, not an addit… |
| A15b-F03 | W | `ui/tabular_analytics_grouping_dialog.py:1287` TabularAnalyticsGroupingDialog._group_assignment | GUI | S | Estimated 0.5–3 s per 100k-row saved pandas-group restore; lower confidence than the completed probes. No saving claimed for first open with no saved groups … |
| A15b-F04 | W | `ui/tabular_analytics_grouping_dialog.py:2203` TabularAnalyticsGroupingDialog._render_selector_ | GUI | S | 0.7–1.1 s per fully selected 1,000-key async page restoration; near zero when no keys are selected. No saving claimed for the already-blocked synchronous route. |
| A15b-F05 | W | `ui/tabular_analytics_grouping_dialog.py:1479` TabularAnalyticsGroupingDialog._sqlite_selector_ | GUI | M | About 0.45–0.75 s less uninterrupted GUI blocking per such preview; total operation time may remain similar or rise slightly due to thread dispatch. Facet-hi… |
| A15b-F06 | W | `ui/tabular_analytics_filter_dialog.py:919` TabularAnalyticsFilterDialog._column_date_bounds | GUI | S | 0.05–0.10 s per repeated SQLite date-control refresh at 216k rows; ~0.01 s per repeated-date pandas refresh at 100k. Worker loading can remove the first scan… |
| A15b-F07 | W | `ui/tabular_analytics_filter_dialog.py:1016` TabularAnalyticsFilterDialog._accept_filter | GUI | M | 0.002–0.003 s on the cheap indexed case; about 0.06–0.09 s per Apply on the tested date-scan case by retaining one validation/count instead of four. Expressi… |

## S3-9 — Anulowanie i zamykanie (10)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A03-F03 | W | `exporting/export_backends.py:717` ExcelExportBackend.run | worker | M | 0 s on successful exports; roughly 1-15 s cancellation/failure cleanup latency after substantial Main work, less on early cancel. Avoids serializing/compress… |
| A10-F08 | W | `industrial/industrial_analytics_workflow.py:994` _write_dashboard | worker | M | 0 s on successful runs; approximately 0-34 s of avoidable post-cancel work depending on where cancellation arrives, with a target of checking at each metric/… |
| A11-F06 | W | `industrial/industrial_analytics_dashboard.py:187` build_production_dashboard_manifest | worker | M | 0 s on successful runs; 0-29 s avoidable remaining build work after a cancel request, or 0-5.7 s during writer, on the supplied flow scale. These are separat… |
| A13-F03 | S | `ui/main_window.py:1680` MainWindow._recover_abandoned_realtime_staging | GUI | M | 0-0.05 s GUI blocking on an already-ready uncontended database; roughly 0.1-15.1 s of GUI blocking avoided for slow cleanup/write-lock contention (three 5 s … |
| A13-F04 | S | `ui/main_window.py:1482` MainWindow._resolve_realtime_session_before_disc | GUI | M | Potential 0.1-2 s of GUI freeze avoided for an illustrative 10-100 MB populated session on local storage; 0 s when no temporary data needs saving, and possib… |
| A13-F05 | S | `ui/export_dialog.py:277` reveal_file_in_explorer | GUI | S | Potential 0.05-1 s of GUI blocking per cold file-manager launch; 0 s export-computation saving. Actual delay is unmeasured and a hung child has no finite bou… |
| A14-F07 | W | `ui/modify_db_records.py:231` RecordTableModel.first_rows_by_key | GUI | S | 0.03-0.06 s per confirmation or dirty-close check for a last-position edit at 216k rows; near 0 s for early edits. Avoided scan needs no full-row index memory. |
| A14-F08 | W | `ui/modify_db_records.py:379` cancel_load_thread | GUI | M | 0 s claimed on normal successful open; potentially 0.05-2 s less GUI blocking for slow Grouping/Mapping cancellation and up to 3 s or an unbounded wait remov… |
| A15a-F02 | W | `ui/industrial_data_dialog.py:862` IndustrialDataDialog._stop_oznak_status_check /  | GUI | M | 0-2.0 s of GUI blocking per pending worker (0 when already complete), up to 4.0 s for both sequential waits on close; normal-case wall-time distribution need… |
| A15a-F06 | S | `ui/industrial_data_dialog.py:524` IndustrialDataDialog.create_database_file / _res | GUI | M | Estimated 0.1-5 s of GUI blocking for the stated illustrative cache sizes/storage rates; approximately 0 s total I/O time saved by merely moving work to a wo… |

## S3-10 — Group Analysis export (5)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A18-F01 | W | `analytics/group_analysis_service.py:1905` build_group_analysis_payload | worker | M | 1.0-1.6 s at 100k input rows; approximately 2.0-3.4 s at 216k rows by linear scaling of the avoided pass. Conditional on Group Analysis being enabled; no per… |
| A18-F03 | W | `analytics/group_analysis_service.py:157` _group_table | worker | S | 0.3-0.6 s at 100k rows, approximately 0.6-1.2 s at 216k rows across three grouping passes, allowing overhead and reduced realized gains. Remains after F01: r… |
| A18-F04 | W | `analytics/distribution_shape_analysis.py:174` _fit_profile_distributions_by_group | worker | S | 0.2-0.6 s for 216 uncached group profiles with approximately 1500 values each, distributed over metrics that remain below the 10k per-metric fit threshold; s… |
| A18-F05 | W | `analytics/hexafe_groupstats_adapter.py:691` analyze_group_metric (one-sided capability adapt | worker | S | 0.04-0.07 s per 216 one-sided groups on this fixture; approximately linear in actual qualifying groups. This is a minor cleanup, not an explanation for the 3… |
| A18-F06 | S | `analytics/distribution_fit_service.py:1300` fit_measurement_distribution_batch | worker | M | 0 s with no cache hits or native backend unavailable. Conditional planning range 0.1-1.0 s for 100 native warm-hit groups if avoided fitting/metrics average … |

## S3-11 — Higiena: start, pamięć, launcher, drobne (13)

| ID | W. | Miejsce | Wątek | Wysiłek | Szacunek GPT |
| --- | --- | --- | --- | --- | --- |
| A10-F06 | W | `industrial/industrial_workers.py:28` <module> (industrial_workers imports industrial_ | GUI | S | 0.05-0.15 s of the 0.40 s first-open flow when these modules are still cold (about 13-38%); negligible if already imported by another feature. Upper bound li… |
| A10-F07 | S | `industrial/industrial_data_repository.py:1020` IndustrialDataRepository.promote_staged_industri | worker | L | 0-1 s speculative from reduced allocation churn at 100k rows; primary benefit is reducing promotion Python working memory from whole-run size to a bounded ba… |
| A12-F03 | S | `ui/report_planner.py:427` ReportPlanner._show_columns_menu | GUI | S | 0-0.005s per menu opening expected (not measured); negligible effect on the supplied benchmark flows, which do not repeatedly open this menu. Memory improvem… |
| A13-F02 | W | `ui/ui_foundation.py:454` apply_metroliza_application_theme | GUI | M | LIKELY 0.02-0.06 s (about 12-35% of the supplied 0.17 s theme switch), bounded by the approximately 41% local-refresh profile share. Synthetic duplicate-pass… |
| A15a-F05 | W | `ui/industrial_data_dialog.py:706` IndustrialDataDialog._load_cache_status / refres | GUI | M | Approximately 0.01-0.04 s per ordinary status refresh (roughly most of the cited _load_cache_status share, not additive with its parents); potentially much l… |
| A15a-F07 | W | `ui/industrial_data_dialog.py:1131` IndustrialDataDialog._on_analytics_cache_loaded | GUI | S | 0 s demonstrated direct flow-latency gain; avoid O(reopens x assigned rows) retained memory. A 100k-216k two-column pandas assignment frame commonly has seve… |
| A16-F01 | S | `app/gc_policy.py:70` GuiGcPolicy.collect_due | GUI | M | Measured synthetic opportunity: 0.033-0.035 s per avoided full sweep, 0.067-0.069 s per 300 synthetic ticks. Tentative representative heavy-flow range 0-0.5 … |
| A16-F02 | S | `shared/compute_worker.py:28` worker_executable | worker | M | Illustrative only: 0.03-0.5 s per pool admission if the six components total 30-100 MB and effective warm/cold read+hash throughput is 0.2-1 GB/s. Actual sav… |
| A16-F03 | S | `app/startup_splash.py:268` QtStartupSplash.finish | GUI | S | No demonstrated wall-latency saving. Illustrative planning range 0-0.15 s GUI CPU per minute of session at 25 frames/s if hidden frame callbacks/decode cost … |
| A19-F01 | S | `packaging/launcher/archive.rs:98` decode_file | worker | M | 0-0.5 s on cold/repair extraction and 0-0.1 s on pending verification at ~2156 files; hypothesis only, not additive to known E3 savings. 0 s on completed war… |
| A19-F02 | S | `packaging/launcher/platform/splash_windows.rs:793` start_splash / close_splash; ProgressWindow::beg | startup | M | 0 s for healthy launches. In a synthetic 10-30 s window-thread stall, a single 2 s readiness/teardown budget would avoid roughly 8-28 s of orchestration dela… |
| A19-F03 | S | `packaging/launcher/platform/splash_windows.rs:633` window_thread / FRAMES cache | GUI | S | 0 s normal launch latency; release about 10.01 MiB of live pixel allocations after splash handoff (OS working-set saving unmeasured). A rare repair pays a fr… |
| B06-F01 | S | `resources/base64_encoded_files.py:1` <module: encoded_loading_gif> | startup | S | Approximately 0.005–0.08 s from pre-first-paint GUI work (estimate only; target-platform measurement required). |
