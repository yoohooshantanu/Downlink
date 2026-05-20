"""
Unit tests for utils.py (flatten_values, flatten_keys, safe_float)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from utils import flatten_values, flatten_keys, safe_float


# ── safe_float ────────────────────────────────────────────────────────────────

def test_safe_float_int():
    assert safe_float(5) == 5.0


def test_safe_float_string_number():
    assert safe_float("3.14") == pytest.approx(3.14)


def test_safe_float_bool_returns_none():
    assert safe_float(True) is None
    assert safe_float(False) is None


def test_safe_float_nan_returns_none():
    assert safe_float(float("nan")) is None


def test_safe_float_inf_returns_none():
    assert safe_float(float("inf")) is None
    assert safe_float(float("-inf")) is None


def test_safe_float_non_numeric_returns_none():
    assert safe_float("hello") is None
    assert safe_float(None) is None


# ── flatten_values ────────────────────────────────────────────────────────────

def test_flatten_values_flat_dict():
    d = {"a": 1.0, "b": 2.0}
    assert flatten_values(d) == {"a": 1.0, "b": 2.0}


def test_flatten_values_nested():
    d = {"eps": {"voltage": 8.1, "current": 0.5}}
    result = flatten_values(d)
    assert result == {"eps.voltage": 8.1, "eps.current": 0.5}


def test_flatten_values_deep_nested():
    d = {"a": {"b": {"c": 42.0}}}
    assert flatten_values(d) == {"a.b.c": 42.0}


def test_flatten_values_skips_strings():
    d = {"mode": "safe", "voltage": 8.0}
    result = flatten_values(d)
    assert "mode" not in result
    assert result["voltage"] == 8.0


def test_flatten_values_skips_booleans():
    d = {"flag": True, "voltage": 8.0}
    result = flatten_values(d)
    assert "flag" not in result


def test_flatten_values_empty_dict():
    assert flatten_values({}) == {}


# ── flatten_keys ──────────────────────────────────────────────────────────────

def test_flatten_keys_flat():
    d = {"a": 1, "b": 2}
    keys = flatten_keys(d)
    assert set(keys) == {"a", "b"}


def test_flatten_keys_nested():
    d = {"eps": {"v": 1.0, "i": 0.5}, "cpu_temp": 25.0}
    keys = flatten_keys(d)
    assert set(keys) == {"eps.v", "eps.i", "cpu_temp"}


def test_flatten_keys_skips_non_numeric():
    d = {"mode": "safe", "v": 8.0}
    keys = flatten_keys(d)
    assert "mode" not in keys
    assert "v" in keys
