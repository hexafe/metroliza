#!/usr/bin/env python3
"""Generate deterministic realtime industrial validation fixtures."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random


SEED = 20260613
DEFAULT_OUTPUT = Path("tests/fixtures/industrial_realtime")
FIELDNAMES = (
    "record_id",
    "process_timestamp",
    "part_number",
    "revision",
    "station",
    "line",
    "metric_value",
    "metric_name",
    "expected_label",
    "event_id",
    "event_time",
    "cycle_time_s",
)
START = datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Fixture:
    filename: str
    rows: tuple[dict[str, str], ...]


def _iso_at(index: int, *, gap_minutes: int = 1) -> str:
    return (START + timedelta(minutes=index * gap_minutes)).isoformat().replace("+00:00", "Z")


def _row(
    index: int,
    value: float | str,
    *,
    station: str = "S1",
    line: str = "L1",
    label: str = "normal",
    metric_name: str = "cycle_time_s",
    timestamp: str | None = None,
    part_number: str = "PN-100",
    revision: str = "A",
) -> dict[str, str]:
    record_id = f"{station}-{index + 1:04d}"
    text_value = f"{value:.6g}" if isinstance(value, float) else str(value)
    event_time = timestamp or _iso_at(index)
    return {
        "record_id": record_id,
        "process_timestamp": event_time,
        "part_number": part_number,
        "revision": revision,
        "station": station,
        "line": line,
        "metric_value": text_value,
        "metric_name": metric_name,
        "expected_label": label,
        "event_id": record_id,
        "event_time": event_time,
        "cycle_time_s": text_value,
    }


def _stable_rows(count: int, *, station: str = "S1", nominal: float = 100.0) -> list[dict[str, str]]:
    rng = random.Random(SEED + count + sum(ord(char) for char in station))
    pattern = (-0.2, 0.0, 0.2, 0.1, -0.1)
    return [
        _row(
            index,
            nominal + pattern[index % len(pattern)] + rng.choice((-0.02, 0.0, 0.02)),
            station=station,
        )
        for index in range(count)
    ]


def _legacy_rows(values: Iterable[float], *, labels: Iterable[str] | None = None) -> tuple[dict[str, str], ...]:
    label_list = tuple(labels or ())
    return tuple(
        _row(
            index,
            value,
            label=label_list[index] if index < len(label_list) and label_list[index] else "normal",
        )
        for index, value in enumerate(values)
    )


def build_fixtures() -> tuple[Fixture, ...]:
    stable_40 = tuple(_stable_rows(40))
    single_high = tuple([*_stable_rows(35), _row(35, 120.0, label="high_outlier")])
    single_low = tuple([*_stable_rows(35), _row(35, 80.0, label="low_outlier")])
    usl_lsl = tuple(
        [
            *_stable_rows(6),
            _row(6, 111.0, label="usl_breach"),
            _row(7, 89.0, label="lsl_breach"),
        ]
    )
    warning_only = tuple([*_stable_rows(8), _row(8, 106.0, label="upper_warning")])
    drift = tuple(
        _row(index, 100.0 + index * 0.22, label="drift" if index >= 25 else "normal")
        for index in range(40)
    )
    step = tuple(
        [
            *(
                _row(index, 100.0 + (-0.25 if index % 2 else 0.25), label="normal")
                for index in range(35)
            ),
            *(_row(35 + offset, 107.0, label="step_change") for offset in range(8)),
        ]
    )
    stuck = tuple(_row(index, 100.0, label="stuck_value") for index in range(40))
    stale = (
        _row(0, 100.0, label="normal"),
        _row(1, 100.1, label="last_sample_before_gap"),
    )
    station_baselines = tuple(
        [
            *(_row(index, 100.0 + (-0.2 if index % 2 else 0.2), station="S1") for index in range(24)),
            *(
                _row(
                    24 + index,
                    150.0 + (-0.3 if index % 2 else 0.3),
                    station="S2",
                    part_number="PN-200",
                )
                for index in range(24)
            ),
            _row(48, 156.0, station="S2", part_number="PN-200", label="station_s2_high"),
        ]
    )
    low_count = tuple(
        _row(index, 100.0 + (-0.3 if index % 2 else 0.3), label="low_count")
        for index in range(10)
    )

    return (
        Fixture("stable_normal_process.csv", stable_40),
        Fixture("single_high_outlier.csv", single_high),
        Fixture("single_low_outlier.csv", single_low),
        Fixture("usl_lsl_breach.csv", usl_lsl),
        Fixture("warning_limit_breach.csv", warning_only),
        Fixture("gradual_drift_upward.csv", drift),
        Fixture("sudden_step_change.csv", step),
        Fixture("stuck_sensor.csv", stuck),
        Fixture("missing_stale_data.csv", stale),
        Fixture("station_segment_baselines.csv", station_baselines),
        Fixture("low_sample_count.csv", low_count),
        Fixture("normal_stable_process.csv", _legacy_rows((10.0, 10.1, 9.9, 10.0, 10.2))),
        Fixture(
            "single_point_outlier.csv",
            _legacy_rows((10.0, 10.1, 9.9, 10.2, 25.0), labels=("", "", "", "", "critical")),
        ),
        Fixture(
            "spec_limit_breach.csv",
            _legacy_rows((10.0, 10.2, 13.5), labels=("", "", "critical")),
        ),
        Fixture(
            "gradual_drift.csv",
            _legacy_rows((10.0, 10.4, 10.8, 11.2, 11.8), labels=("", "", "", "", "warning")),
        ),
        Fixture("stuck_value.csv", _legacy_rows((10.0, 10.0, 10.0, 10.0, 10.0))),
    )


def write_fixture(output_dir: Path, fixture: Fixture, *, force: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / fixture.filename
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(fixture.rows)
    return path


def generate_fixtures(output_dir: Path, *, force: bool = False) -> tuple[Path, ...]:
    return tuple(write_fixture(output_dir, fixture, force=force) for fixture in build_fixtures())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = generate_fixtures(args.output, force=args.force)
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
