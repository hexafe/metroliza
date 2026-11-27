# Performance envelope

[Issue #952](https://github.com/hexafe/metroliza/issues/952) defines the shared workload and measurement contract. The reference workloads below are repeatable checkpoints. Their timings describe the recorded environment and fixture size.

## Reference workloads

| Workload | Reference fixture and end point | Evidence to retain |
| --- | --- | --- |
| Report parsing and import | 120 synthetic PDF reports through the Reports window review and import. Use the separate discovery probe for filesystem and fingerprint costs. Measure image-only OCR separately in complete mode. | Reports attempted and committed, measurement counts, backend, time per stage, peak memory and cancellation outcome. |
| Report selection, grouping and Excel | 48 reports with 6,912 measurements through Main plots. Use the 600-report case for busy cancellation. Add wide and tall workloads when changing grouping, workbook construction or writer limits. | Selected rows, group identities, logical workbook parity, longest UI stall and preservation of any previous output. |
| Tabular selection and grouping | 100,000 rows with 20 numeric columns and a reference column through SQLite load, filtered preview, grouping and materialization. | Actual backend, input sizes, selected count, bounded preview size, peak memory and temporary store cleanup. |
| Tabular analytics and dashboard | 1,500 rows and eight numeric input columns through summary, dashboard and workbook. Add the [large CSV pipeline](../perf_csv_pipeline_1028.md) when changing calculation or visual sampling. | Result scope, statistics input count, rendered row count, total time and peak memory for each output. |
| Industrial cache | 20,000 synthetic cached rows, six dynamic fields and two sources through the SQLite bridge and tabular materialization. | Reachable sources, row and field counts, bridge and query timings, backend, freshness and last complete cache after failure. |
| Realtime | 20,000 timestamped CSV samples through the replay detector and SQLite. Use [sanitized replay scenarios](../realtime_industrial_validation.md) for edge cases and [detector throughput measurements](../perf_realtime_detectors.md) to isolate scoring cost. | Source and consumer offsets where applicable, event order and identity, end-to-end lag, effective detector path and restart outcome. |

For CLI or automation, use a fixture from the corresponding desktop workflow and compare selected rows, outputs and errors. Use the same measurements after integration when separate changes affect the same workflow.

## Resource and output behavior

- The CSV Summary loaders build a SQLite store for CSV and Excel inputs. The `force_sqlite` compatibility argument has no effect on the current backend. CSV ingest batches contain up to 50,000 rows, and the initial preview reads up to 5,000. Measure additional materialization separately when an operation needs it. [Tabular workload policy](../../src/metroliza/tabular/tabular_analytics_service.py)
- XLSX sheets support up to 1,048,576 rows, including the header, and 16,384 columns. The report export validates its size before publication and retains an existing workbook when the replacement cannot be written. [Writer limits](../../src/metroliza/exporting/xlsx_writer_policy.py) · [Report export qualification](https://github.com/hexafe/metroliza/pull/1278)
- Keep the selected statistical scope visible when using a smaller visual sample or a static chart layer. Retain selected and rendered row counts with the result. Use an explicit option and separate result scope if the calculation itself samples data. [Dashboard and sampling behavior](../user_manual/csv_summary.md#5-choose-outputs)
- Record progress at the user action, first visible feedback, first useful result and worker completion. For cancellation, request it during actual work and record the request-to-idle latency, the confirmed result and any surviving published or temporary files. Verify cleanup after success and after a synthetic failure in the same path. Any retained user-owned or previously published output remains part of the result check.
- Record the requested and effective backend and any fallback reason. Check selected rows, numerical output, ordering and errors against the existing reference before considering a native promotion. Use the existing parity and packaging gates for changes covered by [#908](https://github.com/hexafe/metroliza/issues/908).

## Reference measurements

The table records three fresh Linux source processes per row on a ThinkPad P15 with an Intel Xeon W-10855M, Python 3.11.16, Qt offscreen and the balanced power profile. The `benchmark_paths.py` figures include process startup and fixture setup. Data is generated from the same harness on each run. The operating system and plotting caches can warm. Memory in this table is peak RSS of the benchmark process. [Exact source](https://github.com/hexafe/metroliza/commit/aead72c529c28a7a232a02a485bf6e6126d19f13)

| Scenario | Median wall time and range | Median peak RSS |
| --- | --- | --- |
| `pdf_parse_path` discovery and fingerprint probe with stubbed persistence | 0.77 s, 0.77–0.82 s | 92 MiB |
| `csv_summary_large_data_probe` | 10.03 s, 9.63–10.99 s | 224 MiB |
| `csv_summary_export_path` | 15.35 s, 15.20–16.40 s | 222 MiB |
| `industrial_cache_to_csv_summary_bridge_probe` | 10.69 s, 10.53–10.89 s | 115 MiB |

Run `scripts/benchmark_paths.py` with `--output-dir` and the named `--scenarios`. Use `--pdf-count 120`, `--large-csv-rows 100000 --large-csv-columns 20`, `--csv-rows 1500 --csv-columns 8`, or `--industrial-cache-rows 20000 --industrial-cache-dynamic-fields 6 --industrial-cache-source-count 2` respectively. Use a dedicated temporary directory so the run can count owned files before and after it exits. For Qt progress and cancellation, use `scripts/benchmark_ui_flows.py` and retain the exact scenario command and fixture preparation settings.

The Reports window measured 1.74 s from Review to completed light metadata on 120 synthetic PDFs (1.73–1.81 s). Import measured 1.30 s after the completed review (1.26–2.28 s), with 120 reports and 2,880 measurements committed in every run. Median longest UI stalls were 61 ms for review and 39 ms for import. Median peak process-tree RSS was 417 and 345 MiB respectively. Prepare the harness PDF set with `--pdf-count 120 --measurements-per-report 24`, then run `reports_scan` and `reports_import` with `--pdf-set pdf_1500`.

On the same source tree, the CSV Summary window loaded and then removed the large fixture's SQLite store on close. Canceling a second load after progress became visible took 43 ms in that run, removed the temporary store and left the input file intact. The measurement harness itself initially retained a store after each large CSV probe. Its regression tests cover success and a failure after materialization. A repeat of the 100,000-row benchmark after the fix left zero stores.

Local CSV replay processed 20,000 samples in batches of 500 and committed the 20 expected specification-limit events in each run. The fixture uses one UTC timestamp per second, with value 100 except every thousandth row at 115 and limits 90 and 110. From replay start through SQLite event persistence the median was 1.40 s (1.39–1.47 s), with median peak process RSS of 26 MiB. This measures the local replay path with no source polling.

The published [export A/B evidence](https://github.com/hexafe/metroliza/issues/952#issuecomment-7216963572) uses peak process-tree RSS and whole UI flow timings. Compare those figures within the export experiment. Windows timing and live-source throughput require measurements in their respective environments.

## Evidence for changes and downstream workflows

Record the exact source tree, harness and fixture identity, operating system, hardware, packaging mode, dependencies, relevant runtime settings, dataset size and shape, and each run's status. Keep cold and warm results identifiable. Include per-stage times, end-to-end time, peak RSS and its measurement method, output and temporary bytes, progress and cancellation timing when available. Retain failed or excluded runs with reasons. With repeated runs, include the sample count, median and range. Validate correctness and record maintenance or packaging impact alongside speed changes.

Use the [CMM parser guardrail](../release_checks/cmm_parser_perf_guardrail.md) for the current blocking benchmark and its baseline refresh procedure. Additional benchmark results are advisory until their fixture, reference environment, noise and tolerances support a reproducible gate. Review any future blocking threshold in a dedicated change with raw repeated measurements and an agreed refresh policy.

CSV and Excel Summary [#939](https://github.com/hexafe/metroliza/issues/939), industrial acquisition [#940](https://github.com/hexafe/metroliza/issues/940) and realtime operations [#941](https://github.com/hexafe/metroliza/issues/941) use this evidence format for their own data sources, recovery behavior and supported workload ranges.
