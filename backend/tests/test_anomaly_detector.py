"""
Unit tests for anomaly_detector.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from anomaly_detector import detect_anomalies


def _make_frame(ts: str, **kwargs) -> dict:
    """Helper: build a minimal telemetry frame."""
    return {"timestamp": ts, "decoded": kwargs}


# ── detect_anomalies ──────────────────────────────────────────────────────────

def test_empty_input_returns_empty():
    assert detect_anomalies([]) == []


def test_insufficient_samples_skipped():
    """Fewer than 5 samples should not trigger anomaly detection."""
    frames = [_make_frame(f"2024-01-01T00:0{i}:00Z", battery_voltage=8.0) for i in range(4)]
    assert detect_anomalies(frames) == []


def test_stable_data_no_anomalies():
    """All identical values → std_dev == 0, no anomaly."""
    frames = [_make_frame(f"2024-01-01T00:{i:02d}:00Z", battery_voltage=8.0) for i in range(10)]
    assert detect_anomalies(frames) == []


def test_obvious_outlier_detected():
    """
    10 frames near 8.0 V, then one spike at 15.0 V.
    The spike must be flagged as an anomaly.
    """
    frames = [_make_frame(f"2024-01-01T00:{i:02d}:00Z", battery_voltage=8.0) for i in range(10)]
    # Replace the last frame with a clear outlier
    frames[-1] = _make_frame("2024-01-01T00:10:00Z", battery_voltage=15.0)

    anomalies = detect_anomalies(frames)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["parameter_name"] == "battery_voltage"
    assert a["severity"] in ("warning", "critical")


def test_critical_severity_threshold():
    """A deviation > 4σ must produce severity='critical'.
    Use a large stable baseline (50 frames) so the extreme outlier doesn't
    drag the mean, ensuring the z-score reliably exceeds 4σ.
    """
    frames = [_make_frame(f"2024-01-01T{i // 60:02d}:{i % 60:02d}:00Z", battery_voltage=8.0)
              for i in range(50)]
    frames.append(_make_frame("2024-01-01T01:00:00Z", battery_voltage=1000.0))
    anomalies = detect_anomalies(frames)
    assert any(a["severity"] == "critical" for a in anomalies)


def test_anomaly_fields_present():
    """Every anomaly record must expose the required contract fields."""
    frames = [_make_frame(f"2024-01-01T00:{i:02d}:00Z", battery_voltage=8.0) for i in range(10)]
    frames[-1] = _make_frame("2024-01-01T00:10:00Z", battery_voltage=50.0)
    anomalies = detect_anomalies(frames)
    assert anomalies
    required = {"parameter_name", "value", "mean", "deviation_sigma", "severity", "timestamp"}
    for a in anomalies:
        assert required.issubset(a.keys())


def test_nested_decoded_values_flattened():
    """Nested decoded dicts must be flattened correctly."""
    frames = [
        _make_frame(f"2024-01-01T00:{i:02d}:00Z", eps={"voltage": 8.0})
        for i in range(10)
    ]
    frames[-1] = _make_frame("2024-01-01T00:10:00Z", eps={"voltage": 50.0})
    anomalies = detect_anomalies(frames)
    assert any(a["parameter_name"] == "eps.voltage" for a in anomalies)


def test_non_numeric_fields_ignored():
    """String fields in decoded must not cause errors."""
    frames = [
        _make_frame(f"2024-01-01T00:{i:02d}:00Z", battery_voltage=8.0, mode="safe")
        for i in range(10)
    ]
    frames[-1] = _make_frame("2024-01-01T00:10:00Z", battery_voltage=50.0, mode="nominal")
    anomalies = detect_anomalies(frames)
    assert any(a["parameter_name"] == "battery_voltage" for a in anomalies)
    assert all(a["parameter_name"] != "mode" for a in anomalies)
