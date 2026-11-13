"""Observed monitor metadata only; never query or infer a live freshness clock."""
import math


def observed_freshness(results, *, scheduled, poll_owned, stopping):
    if stopping:
        poller = "poller stopping"
    elif scheduled:
        poller = "scheduled monitoring running"
    elif poll_owned:
        poller = "one-off or finishing poll owned"
    else:
        poller = "monitoring stopped"
    if not results:
        return f"Data freshness: no completed poll snapshot; {poller}."
    lags = []
    watermark = ""
    for result in results:
        value = getattr(result, "lag_seconds", None)
        try:
            lag = float(value) if value is not None else float("nan")
        except (TypeError, ValueError):
            lag = float("nan")
        if math.isfinite(lag):
            lags.append(max(0.0, lag))
        if not watermark:
            watermark = str(getattr(result, "event_time_watermark", "") or "")[:80]
    lag_text = f"max lag {max(lags):.1f}s" if lags else "lag unavailable"
    through = f"; first reported data-through {watermark}" if watermark else "; data-through unavailable"
    return f"Data freshness: last poll snapshot {lag_text}{through}; {poller}. Snapshot, not live age."
