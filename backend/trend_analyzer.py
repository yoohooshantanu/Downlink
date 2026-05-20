"""
Trend analysis engine for satellite telemetry parameters.

Computes the direction and magnitude of change for a named parameter
over a set of telemetry frames.  Designed to be deterministic and
fast — no external dependencies beyond the standard library.
"""

import math
from typing import List, Dict, Any, Optional

from utils import flatten_values

# Minimum number of data points required before reporting a trend.
MIN_POINTS = 3

# Threshold (% change) below which a trend is considered "stable".
STABLE_THRESHOLD_PCT = 2.0


def analyze_trend(
    frames: List[Dict[str, Any]],
    parameter: str,
) -> Dict[str, Any]:
    """
    Analyse the trend of *parameter* across the supplied telemetry frames.

    Parameters
    ----------
    frames:
        Chronologically ordered list of telemetry frame dicts, each with
        a ``"timestamp"`` key and a ``"decoded"`` dict of telemetry values.
    parameter:
        The dotted parameter name to analyse (e.g. ``"battery_voltage"``).

    Returns
    -------
    dict with keys:
        - ``direction``      – ``"increasing"``, ``"decreasing"``, or ``"stable"``
        - ``percent_change`` – float, positive for increases
        - ``first_value``    – oldest observed value (or ``None``)
        - ``last_value``     – most-recent observed value (or ``None``)
        - ``mean``           – arithmetic mean over the window
        - ``std``            – population standard deviation
        - ``min``            – minimum observed value
        - ``max``            – maximum observed value
        - ``count``          – number of data points used
        - ``sufficient_data``– bool, False when fewer than MIN_POINTS samples
    """
    values: List[float] = []

    for frame in frames:
        decoded = frame.get("decoded")
        if not decoded or not isinstance(decoded, dict):
            continue
        flat = flatten_values(decoded)
        if parameter in flat:
            values.append(flat[parameter])

    if not values:
        return _empty_result(parameter)

    # Sort frames are already roughly chronological, so we respect insertion order.
    first_val = values[0]
    last_val = values[-1]
    count = len(values)

    mean = sum(values) / count
    variance = sum((x - mean) ** 2 for x in values) / count
    std = math.sqrt(variance)

    # Percent change relative to the first observed value.
    if abs(first_val) > 1e-9:
        pct_change = ((last_val - first_val) / abs(first_val)) * 100.0
    else:
        pct_change = 0.0

    if pct_change > STABLE_THRESHOLD_PCT:
        direction = "increasing"
    elif pct_change < -STABLE_THRESHOLD_PCT:
        direction = "decreasing"
    else:
        direction = "stable"

    return {
        "parameter": parameter,
        "direction": direction,
        "percent_change": round(pct_change, 2),
        "first_value": round(first_val, 4),
        "last_value": round(last_val, 4),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "count": count,
        "sufficient_data": count >= MIN_POINTS,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _empty_result(parameter: str) -> Dict[str, Any]:
    return {
        "parameter": parameter,
        "direction": "stable",
        "percent_change": 0.0,
        "first_value": None,
        "last_value": None,
        "mean": None,
        "std": None,
        "min": None,
        "max": None,
        "count": 0,
        "sufficient_data": False,
    }
