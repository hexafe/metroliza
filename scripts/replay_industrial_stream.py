#!/usr/bin/env python3
"""Replay CSV industrial samples into the realtime anomaly foundation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from metroliza.industrial.realtime.numeric_validation import exact_integral
from metroliza.industrial.realtime.replay import ReplayRequest, replay_industrial_stream


def _positive_exact_integer(value: str) -> int:
    try:
        return exact_integral(value, field_name="value", minimum=1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--source-profile-id", required=True, type=int)
    parser.add_argument("--signal-key", required=True)
    parser.add_argument("--metric-column", required=True)
    parser.add_argument("--event-time-column", required=True)
    parser.add_argument("--record-key-column", required=True)
    parser.add_argument("--detectors", default="spec_limits")
    parser.add_argument(
        "--now",
        help=(
            "ISO-8601 replay evaluation time; required when stale_source is selected so replay "
            "results remain deterministic (naive values use --source-timezone)"
        ),
    )
    parser.add_argument("--limit", type=_positive_exact_integer)
    parser.add_argument(
        "--source-timezone",
        default="UTC",
        help="IANA timezone for naive source timestamps (default: UTC)",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_exact_integer,
        default=500,
        help="bounded replay rows processed per batch (default: 500)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lsl", type=float)
    parser.add_argument("--usl", type=float)
    parser.add_argument("--lower-warning", type=float)
    parser.add_argument("--upper-warning", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=args.input,
            database=args.db,
            source_profile_id=args.source_profile_id,
            signal_key=args.signal_key,
            metric_column=args.metric_column,
            event_time_column=args.event_time_column,
            record_key_column=args.record_key_column,
            detectors=tuple(part.strip() for part in args.detectors.split(",") if part.strip()),
            limit=args.limit,
            dry_run=args.dry_run,
            lsl=args.lsl,
            usl=args.usl,
            lower_warning=args.lower_warning,
            upper_warning=args.upper_warning,
            source_timezone=args.source_timezone,
            batch_size=args.batch_size,
            now=args.now,
        )
    )
    for line in summary.as_lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
