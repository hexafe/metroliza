#!/usr/bin/env python3
"""Serial, fresh-process CSV pipeline measurements for Issue #1028.

Run with the same resolved interpreter for every checkout. The small fixture and
options match benchmark_csv_summary_path (300 rows, four metrics, three groups).
Timing excludes fixture generation and artifact inspection; process time includes
imports/startup. Profiling is a separate mode, never performance evidence.
Linux worker measurements require resource; imports, provenance helpers and CLI
help remain platform-neutral.
"""
from __future__ import annotations

import os
import sys

_CLI_OPTIONS = {name: "--" + name for name in (
    "repo", "output", "case", "compare", "samples", "blocks", "requests",
    "timeout", "profile", "worker",
)}


def _bootstrap_roots(arguments):
    """Locate declared source roots without importing shadowable CLI dependencies.

    argparse still validates the CLI. Share its long option names and recognize
    the same unambiguous prefixes; inspect every comparison value conservatively.
    """
    actual_script_directory = os.path.dirname(os.path.realpath(__file__))
    roots = [os.path.dirname(actual_script_directory)]
    invocation_directory = os.path.dirname(os.path.abspath(__file__))
    # Windows direct-file symlinks can admit the link directory; POSIX normally
    # resolves the target for sys.path[0]. Inspect only the actually admitted root.
    if (sys.path and os.path.realpath(sys.path[0]) == os.path.realpath(invocation_directory)
            and os.path.realpath(invocation_directory) != actual_script_directory):
        roots.append(invocation_directory)
    for index, argument in enumerate(arguments):
        if argument == "--":
            break
        option, separator, inline = argument.partition("=")
        if not option.startswith("--"):
            continue
        matches = [flag for flag in _CLI_OPTIONS.values() if flag.startswith(option)]
        if len(matches) != 1 or matches[0] not in {"--repo", "--compare"}:
            continue
        values = [inline] if separator else []
        for value in arguments[index + 1:]:
            if value.startswith("-"):
                break
            values.append(value)
        if matches[0] == "--repo":
            roots.extend(values[:1])
        else:
            roots.extend(value.split("=", 1)[1] for value in values if "=" in value)
    return roots


def _bootstrap_reject_native(root, ancestors=frozenset()):
    """Dependency-free rejection before stdlib/helper names can be shadowed.

    Deliberately duplicate the small helper predicate: importing that helper first
    could itself initialize an ignored extension. Full identities follow later.
    """
    resolved = os.path.realpath(root)
    if not os.path.exists(resolved):
        return  # argparse/the worker owns invalid or missing checkout diagnostics.
    if resolved in ancestors:
        raise RuntimeError("Unsupported cyclic import-directory symlink")
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name.lower().endswith((".so", ".pyd")) and entry.name.split(".")[0].isidentifier():
                raise RuntimeError("Checkout-local native inputs are unsupported before bootstrap imports")
            if entry.name.isidentifier() and entry.is_dir():
                _bootstrap_reject_native(entry.path, ancestors | {resolved})


for _bootstrap_root in _bootstrap_roots(sys.argv[1:]):
    _bootstrap_reject_native(_bootstrap_root)

# These imports must follow the dependency-free native rejection above.
import argparse  # noqa: E402
import cProfile  # noqa: E402
from dataclasses import asdict  # noqa: E402
import hashlib  # noqa: E402
import importlib.metadata  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = {
    "small": (300, 4, 3), "medium": (30_000, 12, 12), "large": (150_001, 4, 12),
    "many-groups": (600, 4, 24),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkout_identity(repo: Path) -> tuple[str, str]:
    """Reject mutable working trees before attributing execution to committed code."""
    from scripts.benchmark_native_provenance import reject_checkout_native

    reject_checkout_native(repo)
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo,
    )
    if status:
        raise RuntimeError("Benchmark checkout must be clean; commit changes and use external "
                           "or git-ignored output directories before measuring")
    return tuple(subprocess.check_output(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=repo, text=True,
    ).splitlines())


def _verify_checkout_identity(repo: Path, expected: tuple[str, str], driver_sha: str) -> None:
    if _checkout_identity(repo) != expected or _sha(Path(__file__).resolve()) != driver_sha:
        raise RuntimeError("Benchmark checkout or shared driver changed during measurement")


def _check_output_location(repo: Path, destination: Path) -> None:
    if destination.is_relative_to(repo) and subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(destination)], cwd=repo,
    ).returncode != 0:
        raise RuntimeError("Benchmark output must be external or git-ignored")


def _prepare_non_small_fixture(fixture, case, pd, np, rows):
    if case == "small":
        return
    frame = pd.read_csv(fixture)
    # Keep full rows/columns; adversarial text and missing values are intentional.
    frame["DIM_01"] = frame["DIM_01"].astype(object)
    frame.loc[frame.index[::997], "DIM_01"] = "invalid"
    frame.loc[frame.index[::991], "DIM_02"] = np.nan
    frame["CATEGORY"] = [f"Category {i % 997:04d}" for i in range(rows)]
    frame.loc[0, "PART"] = '=HYPERLINK("https://example.invalid","<unsafe>&")'
    frame.to_csv(fixture, index=False)


def _worker(args: argparse.Namespace) -> None:
    from scripts.benchmark_native_provenance import reject_checkout_native

    repo = Path(args.repo).resolve()
    reject_checkout_native(repo)
    tooling_root = Path(__file__).resolve().parents[1]
    reject_checkout_native(tooling_root)
    import resource

    started = time.perf_counter()
    identity = _checkout_identity(repo)
    tooling_identity = identity if tooling_root == repo else _checkout_identity(tooling_root)
    driver_sha = _sha(Path(__file__).resolve())
    destination = Path(args.output).resolve()
    _check_output_location(repo, destination)
    sys.path[:0] = [str(repo / "src"), str(repo)]
    from scripts.benchmark_native_provenance import NativeProvenance
    native_guard = NativeProvenance(repo)
    native_guard.install()
    helper_path = Path(sys.modules[NativeProvenance.__module__].__file__).resolve()
    helper_sha = _sha(helper_path)
    provenance_s = time.perf_counter() - started

    def verify_inputs():
        nonlocal provenance_s
        checked_at = time.perf_counter()
        _verify_checkout_identity(repo, identity, driver_sha)
        if tooling_root != repo:
            _verify_checkout_identity(tooling_root, tooling_identity, driver_sha)
        if _sha(helper_path) != helper_sha:
            raise RuntimeError("Benchmark native provenance helper changed")
        native_guard.verify()
        provenance_s += time.perf_counter() - checked_at

    from scripts import benchmark_paths as harness
    harness_path = Path(harness.__file__).resolve()
    harness_root = tooling_root if harness_path.is_relative_to(tooling_root) else repo
    if not harness_path.is_relative_to(harness_root):
        raise RuntimeError("Benchmark harness resolved outside verified source roots")
    harness_origin = {"root": "shared_tooling" if harness_root == tooling_root else "measured_checkout",
                      "path": harness_path.relative_to(harness_root).as_posix(),
                      "sha256": _sha(harness_path)}
    harness._install_headless_stubs()
    import numpy as np
    import pandas as pd
    from metroliza.industrial.industrial_analytics_state import (
        ProductionChartSelection, ProductionMetricSelection,
    )
    from metroliza.industrial.industrial_analytics_workflow import run_tabular_file_analytics

    destination.mkdir(parents=True, exist_ok=False)
    rows, columns, groups = CASES[args.case]
    fixture = destination / "summary_fixture.csv"
    harness._create_csv_fixture(fixture, row_count=rows, data_columns=columns)
    _prepare_non_small_fixture(fixture, args.case, pd, np, rows)
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
        verify_inputs()
        profiler = cProfile.Profile() if args.profile else None
        import_guard_before = native_guard.import_guard_s
        run_start = time.perf_counter()
        if profiler:
            profiler.enable()
        result = run_tabular_file_analytics(**kwargs)
        if profiler:
            profiler.disable()
        elapsed_with_guard = time.perf_counter() - run_start
        import_guard_s = native_guard.import_guard_s - import_guard_before
        elapsed = elapsed_with_guard
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        verify_inputs()
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
            "request": request, "workflow_s": elapsed,
            "workflow_excluding_import_guard_s": elapsed_with_guard - import_guard_s,
            "native_import_guard_s": import_guard_s, "peak_rss_kib": peak_rss_kib,
            "outcome": outcome, "artifacts": artifacts,
        })
    import matplotlib
    payload = {
        "case": args.case, "rows": rows, "numeric_columns": columns, "groups": groups,
        "selected_metrics": 4, "seed": 7, "fixture_sha256": _sha(fixture),
        "head": identity[0], "tree": identity[1], "driver_sha256": driver_sha,
        "shared_tooling_head": tooling_identity[0], "shared_tooling_tree": tooling_identity[1],
        "shared_tooling_root": str(tooling_root), "harness_origin": harness_origin,
        "checkout_verified_clean_before_and_after": True,
        "profiled": args.profile, "setup_s": setup_s, "records": records,
        "matplotlib_backend": matplotlib.get_backend(),
        "native_helper_sha256": helper_sha,
        "versions": {name: importlib.metadata.version(name) for name in (
            "numpy", "pandas", "scipy", "matplotlib", "XlsxWriter", "openpyxl",
            "hexafe-groupstats", "hexafe-plotstats", "PyQt6", "PyQt6-Qt6",
        )}, "python": sys.version.split()[0],
    }
    verify_inputs()
    payload["native_provenance"] = native_guard.receipt()
    # Keep the historical import summary; content identity lives in native_provenance.
    payload["native_modules"] = {
        name: {"loaded": native_guard.bridge_loaded[name] is not None,
               "file": Path(native_guard.bridge_loaded[name]).name
               if native_guard.bridge_loaded[name] else None}
        for name in native_guard.resolutions if name.startswith("_metroliza_")
    }
    payload["provenance_s"] = provenance_s
    (destination / "result.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")


def _summary(values: list[float]) -> dict:
    median = statistics.median(values)
    quartiles = statistics.quantiles(values, method="inclusive") if len(values) > 1 else [median] * 3
    return {"samples": values, "median": median,
            "mad": statistics.median(abs(v - median) for v in values),
            "iqr": quartiles[2] - quartiles[0], "min": min(values), "max": max(values)}


def _verify_comparison_sample(payload, identity, tooling_identity, driver_sha, helper_sha,
                              native_inputs, label):
    if (tuple(payload[key] for key in ("head", "tree")) != identity
            or payload["driver_sha256"] != driver_sha
            or payload["native_helper_sha256"] != helper_sha
            or tuple(payload[key] for key in ("shared_tooling_head", "shared_tooling_tree"))
            != tooling_identity):
        raise RuntimeError("Comparison source/driver identity changed between samples")
    native = payload["native_provenance"]
    # Stable availability and observed loading must both agree within a variant.
    # These fields contain no timing counters; imports still do not prove use.
    native_identity = {key: native[key] for key in
                       ("artifacts", "bridge_resolution", "interpreter",
                        "requested_backend_environment", "loaded_bridges",
                        "loaded_extensions", "observed_native_imports", "initially_loaded")}
    if native_inputs.setdefault(label, native_identity) != native_identity:
        raise RuntimeError("Comparison native inputs changed between samples")


def _compare(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    variants = dict(item.split("=", 1) for item in args.compare)
    identities = {label: _checkout_identity(Path(repo).resolve()) for label, repo in variants.items()}
    driver_sha = _sha(Path(__file__).resolve())
    tooling_root = Path(__file__).resolve().parents[1]
    tooling_identity = _checkout_identity(tooling_root)
    from scripts import benchmark_native_provenance
    helper_path = Path(benchmark_native_provenance.__file__).resolve()
    helper_sha = _sha(helper_path)
    native_inputs = {}
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
                _verify_comparison_sample(payload, identities[label], tooling_identity,
                                          driver_sha, helper_sha, native_inputs, label)
                record = {"variant": label, "block": block, "warmup": index == -1,
                          "process_s": process_s, "result": payload}
                records.append(record)
                (output / "samples.json").write_text(json.dumps(records, indent=2) + "\n")
                print(json.dumps({"variant": label, "block": block, "warmup": index == -1,
                                  "workflow_s": payload["records"][0]["workflow_s"],
                                  "process_s": process_s}), flush=True)
    for label, repo in variants.items():
        _verify_checkout_identity(Path(repo).resolve(), identities[label], driver_sha)
    _verify_checkout_identity(tooling_root, tooling_identity, driver_sha)
    if _sha(helper_path) != helper_sha:
        raise RuntimeError("Comparison native provenance helper changed")
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
    parser.add_argument(_CLI_OPTIONS["repo"])
    parser.add_argument(_CLI_OPTIONS["output"], required=True)
    parser.add_argument(_CLI_OPTIONS["case"], choices=CASES, default="small")
    parser.add_argument(_CLI_OPTIONS["compare"], nargs="+")
    parser.add_argument(_CLI_OPTIONS["samples"], type=int, default=7)
    parser.add_argument(_CLI_OPTIONS["blocks"], type=int, default=2)
    parser.add_argument(_CLI_OPTIONS["requests"], type=int, default=1)
    parser.add_argument(_CLI_OPTIONS["timeout"], type=int, default=600)
    parser.add_argument(_CLI_OPTIONS["profile"], action="store_true")
    parser.add_argument(_CLI_OPTIONS["worker"], action="store_true")
    args = parser.parse_args()
    if args.worker:
        _worker(args)
    elif args.compare:
        _compare(args)
    else:
        parser.error("supply --compare LABEL=CHECKOUT ... or --worker --repo CHECKOUT")


if __name__ == "__main__":
    main()
