"""
Offline evaluation harness for AI routing and parameter resolution.

Run:
  python backend/eval_ai.py
"""

import json
from ai_engine import evaluate_queries


def default_cases():
    params = [
        "battery_voltage",
        "solar_panel_current",
        "temp_cpu",
        "temp_eps",
        "tx_power",
        "rssi",
    ]
    return [
        {
            "query": "Battery voltage trend last 10 passes",
            "expected_intent": "trend",
            "expected_parameter": "battery_voltage",
            "parameters": params,
        },
        {
            "query": "Any anomalies in the last 24 hours?",
            "expected_intent": "anomaly",
            "expected_parameter": None,
            "parameters": params,
        },
        {
            "query": "Compare solar current morning vs evening",
            "expected_intent": "compare",
            "expected_parameter": "solar_panel_current",
            "parameters": params,
        },
        {
            "query": "Summarize the last pass quickly",
            "expected_intent": "pass_summary",
            "expected_parameter": None,
            "parameters": params,
        },
        {
            "query": "How healthy is the spacecraft right now?",
            "expected_intent": "health_overview",
            "expected_parameter": None,
            "parameters": params,
        },
    ]


if __name__ == "__main__":
    results = evaluate_queries(default_cases())
    print(json.dumps(results, indent=2))
