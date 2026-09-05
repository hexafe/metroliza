#!/usr/bin/env python3
"""Serial, fresh-process CSV pipeline measurements for Issue #1028.

Run with the same resolved interpreter for every checkout. The small fixture and
options match benchmark_csv_summary_path (300 rows, four metrics, three groups).
Timing excludes fixture generation and artifact inspection; process time includes
imports/startup. Profiling is a separate mode, never performance evidence.
"""
from __future__ import annotations

import argparse
import cProfile
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

CASES = {
    "small": (300, 4, 3), "medium": (30_000, 12, 12), "large": (150_001, 4, 12),
    "many-groups": (600, 4, 24),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worker(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    repo = Path(args.repo).resolve()
    sys.path[:0] = [str(repo / "src"), str(repo)]
    from scripts import benchmark_paths as harness
    harness._install_headless_stubs()
    import numpy as np
    import pandas as pd
    from metroliza.industrial.industrial_analytics_state import (
        ProductionChartSelection, ProductionMetricSelection,
    )
    from metroliza.industrial.industrial_analytics_workflow import run_tabular_file_analytics

    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    rows, columns, groups = CASES[args.case]
    fixture = destination / "summary_fixture.csv"
    harness._create_csv_fixture(fixture, row_count=rows, data_columns=columns)
    if args.case != "small":
        frame = pd.read_csv(fixture)
        # Keep full rows/columns; adversarial text and missing values are intentional.
        frame["DIM_01"] = frame["DIM_01"].astype(object)
        frame.loc[frame.index[::997], "DIM_01"] = "invalid"
        frame.loc[frame.index[::991], "DIM_02"] = np.nan
        frame["CATEGORY"] = [f"Category {i % 997:04d}" for i in range(rows)]
        frame.loc[0, "PART"] = '=HYPERLINK("https://example.invalid","<unsafe>&")'
        frame.to_csv(fixture, index=False)
    grouping = pd.DataFrame({
        "REPORT_ID": np.arange(1, rows + 1, dtype=int),
        "GROUP": [f"Group {index % groups + 1}" for index in range(rows)],
    })
    metrics = () if args.case == "small" else tuple(
        ProductionMetricSelection(field_name=f"dim_{i:02d}", display_label=f"DIM {i:02d}")
        for i in range(1, 5)
    )
    setup_s = time.perf_counter() - started
    records = []
    for request in range(args.requests):
        output = destination / f"request-{request}"
        output.mkdir(exist_ok=True)
        kwargs = dict(
            input_file=str(fixture), output_dashboard_file=str(output / "dashboard.html"),
            reference_column="PART", grouping_df=grouping, metric_selection=metrics,
            chart_selection=ProductionChartSelection(
                time_series=True, histogram=True, violin=True, box=True, groupstats=True,
            ),
            output_workbook_file=str(output / "workbook.xlsx"), separate_parameter_sheets=True,
        )
        profiler = cProfile.Profile() if args.profile else None
        run_start = time.perf_counter()
        if profiler:
            profiler.enable()
        result = run_tabular_file_analytics(**kwargs)
        if profiler:
            profiler.disable()
        elapsed = time.perf_counter() - run_start
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if profiler:
            profiler.dump_stats(str(output / "pipeline.pstats"))
        artifacts = {
            str(p.relative_to(output)): {"bytes": p.stat().st_size, "sha256": _sha(p)}
            for p in sorted(output.rglob("*")) if p.is_file()
        }
        outcome = asdict(result)
        for key in ("html_dashboard_path", "html_dashboard_assets_path", "workbook_path"):
            outcome[key] = Path(outcome[key]).name
        records.append({
            "request": request, "workflow_s": elapsed, "peak_rss_kib": peak_rss_kib,
            "outcome": outcome, "artifacts": artifacts,
        })
    modules = {}
    for name in ("_metroliza_chart_native", "_metroliza_group_stats_native",
                 "_metroliza_comparison_stats_native", "_metroliza_distribution_fit_native",
                 "_metroliza_cmm_native"):
        module = sys.modules.get(name)
        modules[name] = {"loaded": module is not None, "file": Path(
            str(getattr(module, "__file__", ""))).name if module else None}
    import matplotlib
    payload = {
        "case": args.case, "rows": rows, "numeric_columns": columns, "groups": groups,
        "selected_metrics": 4, "seed": 7, "fixture_sha256": _sha(fixture),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip(),
        "profiled": args.profile, "setup_s": setup_s, "records": records,
        "matplotlib_backend": matplotlib.get_backend(), "native_modules": modules,
        "versions": {name: importlib.metadata.version(name) for name in (
            "numpy", "pandas", "scipy", "matplotlib", "XlsxWriter", "openpyxl",
            "hexafe-groupstats", "hexafe-plotstats", "PyQt6", "PyQt6-Qt6",
        )}, "python": sys.version.split()[0],
    }
    (destination / "result.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")


def _summary(values: list[float]) -> dict:
    median = statistics.median(values)
    quartiles = statistics.quantiles(values, method="inclusive") if len(values) > 1 else [median] * 3
    return {"samples": values, "median": median,
            "mad": statistics.median(abs(v - median) for v in values),
            "iqr": quartiles[2] - quartiles[0], "min": min(values), "max": max(values)}


def _compare(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    variants = dict(item.split("=", 1) for item in args.compare)
    env = os.environ.copy()
    env.update({"MPLBACKEND": "Agg", "MPLCONFIGDIR": str(output / "mpl-cache"),
                "QT_QPA_PLATFORM": "offscreen", "PYTHONHASHSEED": "0",
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    records = []
    for block in range(args.blocks):
        # One declared fresh-process warmup per variant per independent block.
        for index in range(-1, args.samples):
            order = list(variants)
            if (index + block) % 2:
                order.reverse()
            for label in order:
                run_dir = output / f"block-{block}-{index + 1}-{label}"
                command = [sys.executable, str(Path(__file__).resolve()), "--worker",
                           "--repo", variants[label], "--case", args.case,
                           "--output", str(run_dir), "--requests", str(args.requests)]
                if args.profile:
                    command.append("--profile")
                start = time.perf_counter()
                with (output / f"{run_dir.name}.log").open("w") as log:
                    subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   check=True, timeout=args.timeout)
                process_s = time.perf_counter() - start
                payload = json.loads((run_dir / "result.json").read_text())
                record = {"variant": label, "block": block, "warmup": index == -1,
                          "process_s": process_s, "result": payload}
                records.append(record)
                (output / "samples.json").write_text(json.dumps(records, indent=2) + "\n")
                print(json.dumps({"variant": label, "block": block, "warmup": index == -1,
                                  "workflow_s": payload["records"][0]["workflow_s"],
                                  "process_s": process_s}), flush=True)
    summary = {}
    for label in variants:
        selected = [r for r in records if r["variant"] == label and not r["warmup"]]
        summary[label] = {
            key: _summary([r["result"]["records"][0][key] for r in selected])
            for key in ("workflow_s", "peak_rss_kib")
        }
        summary[label]["process_s"] = _summary([r["process_s"] for r in selected])
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo")
    parser.add_argument("--output", required=True)
    parser.add_argument("--case", choices=CASES, default="small")
    parser.add_argument("--compare", nargs="+")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--requests", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        _worker(args)
    elif args.compare:
        _compare(args)
    else:
        parser.error("supply --compare LABEL=CHECKOUT ... or --worker --repo CHECKOUT")


if __name__ == "__main__":
    main()
