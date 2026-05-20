"""
Z-score based anomaly detection engine.

Computes rolling mean and standard deviation for satellite telemetry
parameters and flags readings that deviate beyond a specified threshold.
"""

import math
from typing import List, Dict, Any

from utils import flatten_values as _flatten_values

# Threshold for flagging an anomaly (number of standard deviations)
Z_SCORE_THRESHOLD = 2.5

def detect_anomalies(frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect anomalies in a list of telemetry frames.
    Frames should be chronologically ordered.
    Returns a list of anomaly records matching the frontend contract.
    """
    if not frames:
        return []

    # Group values by parameter
    param_values: Dict[str, List[float]] = {}
    param_latest: Dict[str, Dict[str, Any]] = {}

    for frame in frames:
        decoded = frame.get("decoded", {})
        ts = frame.get("timestamp")
        if not decoded or not ts or not isinstance(decoded, dict):
            continue

        flat = _flatten_values(decoded)
        for k, v in flat.items():
            if k not in param_values:
                param_values[k] = []
            param_values[k].append(v)
            param_latest[k] = {"value": v, "timestamp": ts}

    anomalies = []

    for param, values in param_values.items():
        if len(values) < 5:
            continue  # Need a minimum sample size to compute stats

        # Compute mean and standard deviation
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            continue  # Avoid division by zero if all values are identical

        # Check the latest reading against the historical baseline
        latest = param_latest[param]
        latest_val = latest["value"]
        
        z_score = abs(latest_val - mean) / std_dev

        if z_score > Z_SCORE_THRESHOLD:
            # Assign severity based on magnitude of deviation
            severity = "critical" if z_score > 4.0 else "warning"
            
            anomalies.append({
                "parameter_name": param,
                "value": latest_val,
                "mean": round(mean, 2),
                "deviation_sigma": round(z_score, 1),
                "severity": severity,
                "timestamp": latest["timestamp"]
            })

    # Sort anomalies by timestamp descending (most recent first)
    anomalies.sort(key=lambda x: x["timestamp"], reverse=True)
    return anomalies

# _flatten_values is imported from utils.py
