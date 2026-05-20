"""
Shared utility functions for the Downlink backend.

Centralises helpers that were previously duplicated across
ai_engine.py, anomaly_detector.py and satnogs_client.py.
"""

import math
from typing import Dict, Any, Optional


def flatten_values(d: Dict[str, Any], prefix: str = "") -> Dict[str, float]:
    """
    Recursively flatten a nested dict into {dotted_key: numeric_value} pairs.
    Non-numeric and boolean values are silently skipped.
    """
    result: Dict[str, float] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(flatten_values(v, full_key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            fv = safe_float(v)
            if fv is not None:
                result[full_key] = fv
    return result


def flatten_keys(d: Dict[str, Any], prefix: str = "") -> list[str]:
    """
    Recursively flatten a nested dict and return all dotted numeric-value keys.
    """
    keys: list[str] = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(flatten_keys(v, full_key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            keys.append(full_key)
    return keys


def safe_float(v: Any) -> Optional[float]:
    """Convert a value to float, returning None if it is invalid or non-finite."""
    try:
        if isinstance(v, bool):
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None
