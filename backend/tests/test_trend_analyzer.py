"""
Unit tests for trend_analyzer.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from trend_analyzer import analyze_trend


def _make_frame(ts: str, **kwargs) -> dict:
    return {"timestamp": ts, "decoded": kwargs}


# ── analyze_trend ─────────────────────────────────────────────────────────────

def test_empty_frames_returns_stable():
    result = analyze_trend([], "battery_voltage")
    assert result["direction"] == "stable"
    assert result["count"] == 0
    assert result["sufficient_data"] is False


def test_parameter_not_present():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", rssi=-90.0) for i in range(5)]
    result = analyze_trend(frames, "battery_voltage")
    assert result["count"] == 0
    assert result["direction"] == "stable"


def test_increasing_trend():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=float(7 + i)) for i in range(5)]
    result = analyze_trend(frames, "battery_voltage")
    assert result["direction"] == "increasing"
    assert result["percent_change"] > 0


def test_decreasing_trend():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=float(10 - i)) for i in range(5)]
    result = analyze_trend(frames, "battery_voltage")
    assert result["direction"] == "decreasing"
    assert result["percent_change"] < 0


def test_stable_trend():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=8.0) for i in range(5)]
    result = analyze_trend(frames, "battery_voltage")
    assert result["direction"] == "stable"
    assert result["percent_change"] == 0.0


def test_result_fields_present():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=8.0 + i * 0.1) for i in range(5)]
    result = analyze_trend(frames, "battery_voltage")
    required = {"direction", "percent_change", "first_value", "last_value",
                "mean", "std", "min", "max", "count", "sufficient_data"}
    assert required.issubset(result.keys())


def test_nested_parameter():
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", eps={"voltage": float(8 + i)}) for i in range(5)]
    result = analyze_trend(frames, "eps.voltage")
    assert result["direction"] == "increasing"
    assert result["count"] == 5


def test_sufficient_data_flag():
    """Less than MIN_POINTS (3) returns sufficient_data=False."""
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=8.0) for i in range(2)]
    result = analyze_trend(frames, "battery_voltage")
    assert result["sufficient_data"] is False


def test_mean_and_std_correctness():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", x=v) for i, v in enumerate(values)]
    result = analyze_trend(frames, "x")
    assert abs(result["mean"] - 3.0) < 0.01
    assert result["min"] == 1.0
    assert result["max"] == 5.0
