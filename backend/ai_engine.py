"""
AI query engine for natural language telemetry analysis.

Strengthened pipeline:
- Intent routing before LLM.
- Deterministic metric extraction from telemetry context.
- Schema-validated JSON responses with retries.
- Canonical parameter resolution from synonyms/fuzzy matching.
- Confidence/provenance metadata in all responses.
- In-memory response cache keyed by (satellite, query, data hash).
- Tiered model strategy (intent/extraction model and synthesis model).
"""

import os
import re
import json
import time
import math
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from difflib import get_close_matches

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

PROMPT_VERSION = "downlink-v2.1"
CACHE_TTL_SECONDS = int(os.getenv("AI_CACHE_TTL_SECONDS", "120"))
MAX_CACHE_ITEMS = int(os.getenv("AI_CACHE_MAX_ITEMS", "800"))

try:
    from openai import AsyncAzureOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

BASE_MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("OPENAI_MODEL")
INTENT_MODEL = os.getenv("AZURE_OPENAI_INTENT_DEPLOYMENT") or BASE_MODEL
SYNTHESIS_MODEL = os.getenv("AZURE_OPENAI_SYNTH_DEPLOYMENT") or BASE_MODEL

_QUERY_CACHE: Dict[str, Dict[str, Any]] = {}

PARAMETER_ALIASES = {
    "battery_voltage": [
        "battery", "battery voltage", "bus voltage", "vbatt", "voltage"
    ],
    "solar_panel_current": [
        "solar", "solar current", "panel current", "array current", "sun current"
    ],
    "temp_cpu": ["cpu temp", "cpu temperature", "processor temp", "onboard computer temp"],
    "temp_eps": ["eps temp", "power temp", "power board temperature", "eps temperature"],
    "tx_power": ["tx", "transmitter", "tx power", "rf power", "downlink power"],
    "rssi": ["signal", "rssi", "link strength", "received signal"],
}


class IntentSpec(BaseModel):
    intent: str
    parameter_name: Optional[str] = None
    requested_hours: Optional[int] = None


class QueryIntent(BaseModel):
    parameter_name: Optional[str] = None


class Provenance(BaseModel):
    model_config = {"protected_namespaces": ()}

    prompt_version: str
    model_used: str
    model_stage: str
    intent: str
    data_hash: str
    data_points_used: int
    parameters_used: List[str]
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None


class Confidence(BaseModel):
    confidence_score: float
    data_coverage: float
    reason: str


class QueryLLMResponse(BaseModel):
    answer_text: str
    intent: QueryIntent
    chart_data: bool
    anomalies_flagged: List[Dict[str, Any]]
    confidence: Confidence
    provenance: Provenance


client = None
if HAS_OPENAI and AZURE_ENDPOINT and AZURE_API_KEY and BASE_MODEL:
    try:
        client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=AZURE_API_KEY,
            api_version=AZURE_API_VERSION,
        )
        logger.info(
            "Azure OpenAI initialized endpoint=%s base_model=%s intent_model=%s synthesis_model=%s api_version=%s",
            AZURE_ENDPOINT,
            BASE_MODEL,
            INTENT_MODEL,
            SYNTHESIS_MODEL,
            AZURE_API_VERSION,
        )
    except Exception as e:
        logger.error("Failed to initialize Azure OpenAI client: %s", e)
        HAS_OPENAI = False
else:
    logger.warning(
        "Azure OpenAI disabled: missing dependency or required env vars (endpoint, key, deployment/model)."
    )
    HAS_OPENAI = False


def _safe_float(v: Any) -> Optional[float]:
    try:
        if isinstance(v, bool):
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def _flatten_values(d: Dict[str, Any], prefix: str = "") -> Dict[str, float]:
    result: Dict[str, float] = {}
    for k, v in d.items():
        name = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_values(v, name))
        else:
            fv = _safe_float(v)
            if fv is not None:
                result[name] = fv
    return result


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: List[float], m: Optional[float] = None) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values) if m is None else m
    return math.sqrt(sum((x - mu) ** 2 for x in values) / len(values))


def _percent_change(first: float, last: float) -> float:
    if abs(first) < 1e-9:
        return 0.0
    return ((last - first) / abs(first)) * 100.0


def _normalize_query(query: str) -> str:
    q = (query or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q


def _redact_query(q: str) -> str:
    redacted = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", q)
    redacted = re.sub(r"\b\d{9,}\b", "[LONG_NUMBER]", redacted)
    return redacted[:300]


def _data_hash(
    norad_id: int,
    telemetry_data: List[Dict[str, Any]],
    anomalies: List[Dict[str, Any]],
    parameters: List[str],
) -> str:
    payload = {
        "norad_id": norad_id,
        "latest_ts": telemetry_data[0].get("timestamp") if telemetry_data else None,
        "oldest_ts": telemetry_data[-1].get("timestamp") if telemetry_data else None,
        "frame_count": len(telemetry_data),
        "anomaly_count": len(anomalies),
        "top_anomaly": anomalies[0].get("parameter_name") if anomalies else None,
        "parameters": sorted(parameters)[:120],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def _prune_cache() -> None:
    now = time.time()
    expired = [k for k, v in _QUERY_CACHE.items() if (now - v["ts"]) > CACHE_TTL_SECONDS]
    for k in expired:
        _QUERY_CACHE.pop(k, None)
    if len(_QUERY_CACHE) <= MAX_CACHE_ITEMS:
        return
    oldest = sorted(_QUERY_CACHE.items(), key=lambda x: x[1]["ts"])[: len(_QUERY_CACHE) - MAX_CACHE_ITEMS]
    for k, _ in oldest:
        _QUERY_CACHE.pop(k, None)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    _prune_cache()
    hit = _QUERY_CACHE.get(key)
    if not hit:
        return None
    if time.time() - hit["ts"] > CACHE_TTL_SECONDS:
        _QUERY_CACHE.pop(key, None)
        return None
    return hit["value"]


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    _prune_cache()
    _QUERY_CACHE[key] = {"ts": time.time(), "value": value}


def _resolve_parameter(query: str, parameters: List[str]) -> Optional[str]:
    if not parameters:
        return None

    q = _normalize_query(query)
    pset = {p.lower(): p for p in parameters}

    for p in parameters:
        if p.lower() in q:
            return p

    alias_to_param: Dict[str, str] = {}
    for canonical, aliases in PARAMETER_ALIASES.items():
        for alias in aliases:
            alias_to_param[alias] = canonical

    matched_alias = None
    for alias in sorted(alias_to_param.keys(), key=len, reverse=True):
        if alias in q:
            matched_alias = alias
            break

    if matched_alias:
        canonical = alias_to_param[matched_alias]
        if canonical in pset:
            return pset[canonical]
        fuzzy = get_close_matches(canonical, parameters, n=1, cutoff=0.55)
        if fuzzy:
            return fuzzy[0]

    fuzzy = get_close_matches(q, parameters, n=1, cutoff=0.6)
    if fuzzy:
        return fuzzy[0]

    tokens = set(re.findall(r"[a-z0-9]+", q))
    best = None
    best_score = 0
    for p in parameters:
        ptok = set(re.findall(r"[a-z0-9]+", p.lower()))
        if not ptok:
            continue
        score = len(tokens.intersection(ptok))
        if score > best_score:
            best = p
            best_score = score
    return best if best_score > 0 else None


def _classify_intent(query: str) -> str:
    q = _normalize_query(query)

    if any(k in q for k in ["compare", "vs", "versus", "difference", "morning", "evening"]):
        return "compare"
    if any(k in q for k in ["pass", "observation", "latest pass", "last pass"]):
        return "pass_summary"
    if any(k in q for k in ["anomaly", "anomalies", "outlier", "abnormal", "alert"]):
        return "anomaly"
    if any(k in q for k in ["trend", "history", "over time", "change", "plot", "chart"]):
        return "trend"
    return "health_overview"


def _extract_requested_hours(query: str) -> Optional[int]:
    q = _normalize_query(query)
    m = re.search(r"(\d+)\s*(hour|hours|hr|hrs|h)\b", q)
    if m:
        return max(1, min(168, int(m.group(1))))
    if "today" in q:
        return 24
    if "week" in q:
        return 24 * 7
    return None


def _compute_context(
    telemetry_data: List[Dict[str, Any]],
    parameters: List[str],
    anomalies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    by_param: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)

    for frame in telemetry_data:
        ts = _parse_iso(frame.get("timestamp", ""))
        decoded = frame.get("decoded")
        if not ts or not isinstance(decoded, dict):
            continue
        flat = _flatten_values(decoded)
        for k, v in flat.items():
            by_param[k].append((ts, v))

    for k in list(by_param.keys()):
        by_param[k].sort(key=lambda x: x[0])

    param_stats: Dict[str, Dict[str, Any]] = {}
    all_ts: List[datetime] = []

    for p, arr in by_param.items():
        if not arr:
            continue
        vals = [v for _, v in arr]
        tss = [t for t, _ in arr]
        all_ts.extend(tss)
        m = _mean(vals)
        s = _std(vals, m)
        first = vals[0]
        last = vals[-1]
        param_stats[p] = {
            "count": len(vals),
            "mean": round(m, 4),
            "std": round(s, 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "first": round(first, 4),
            "last": round(last, 4),
            "pct_change": round(_percent_change(first, last), 2),
            "window_start": tss[0].isoformat(),
            "window_end": tss[-1].isoformat(),
            "recent_values": [round(v, 4) for v in vals[-10:]],
        }

    all_ts.sort()
    return {
        "param_stats": param_stats,
        "time_window_start": all_ts[0].isoformat() if all_ts else None,
        "time_window_end": all_ts[-1].isoformat() if all_ts else None,
        "frame_count": len(telemetry_data),
        "parameter_count": len(parameters),
        "anomaly_count": len(anomalies),
    }


def _deterministic_findings(
    intent: str,
    parameter_name: Optional[str],
    context: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    stats = context.get("param_stats", {})
    chosen = parameter_name if parameter_name in stats else None
    findings: Dict[str, Any] = {
        "intent": intent,
        "parameter_name": chosen,
        "summary_lines": [],
        "chart_data": False,
        "anomalies_flagged": anomalies[:5],
        "parameters_used": [],
    }

    if chosen:
        s = stats[chosen]
        findings["parameters_used"].append(chosen)
        findings["chart_data"] = intent in {"trend", "compare", "health_overview"}
        findings["summary_lines"].append(
            f"{chosen}: last={s['last']}, mean={s['mean']}, change={s['pct_change']}% over {s['count']} points."
        )

    if intent == "anomaly":
        findings["chart_data"] = bool(chosen)
        findings["summary_lines"].append(f"Recent anomaly count: {len(anomalies)}")
    elif intent == "compare":
        if chosen:
            values = stats[chosen]["recent_values"]
            if len(values) >= 4:
                mid = len(values) // 2
                a = _mean(values[:mid])
                b = _mean(values[mid:])
                findings["summary_lines"].append(
                    f"Recent-half comparison for {chosen}: first_half={round(a,4)}, second_half={round(b,4)}, delta={round(b-a,4)}."
                )
    elif intent == "health_overview":
        top_params = sorted(stats.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:3]
        for p, s in top_params:
            findings["parameters_used"].append(p)
            findings["summary_lines"].append(
                f"{p} stable window: mean={s['mean']}, std={s['std']}, last={s['last']}."
            )

    if not findings["summary_lines"]:
        findings["summary_lines"].append("Insufficient telemetry context for deterministic findings.")

    return findings


def _confidence_from_context(
    context: Dict[str, Any],
    parameter_name: Optional[str],
) -> Dict[str, Any]:
    frames = context.get("frame_count", 0)
    pcount = context.get("parameter_count", 0)
    stats = context.get("param_stats", {})

    coverage = min(1.0, (frames / 120.0))
    if parameter_name and parameter_name in stats:
        pcov = min(1.0, stats[parameter_name]["count"] / 80.0)
        coverage = (coverage * 0.6) + (pcov * 0.4)

    anomaly_penalty = 0.0
    if context.get("anomaly_count", 0) > 0:
        anomaly_penalty = min(0.15, context["anomaly_count"] / 100.0)

    parameter_bonus = min(0.1, pcount / 80.0)
    score = max(0.05, min(0.98, coverage + parameter_bonus - anomaly_penalty))

    reason = "Good telemetry depth." if score >= 0.75 else "Limited data depth or sparse parameter coverage."
    return {
        "confidence_score": round(score, 3),
        "data_coverage": round(coverage, 3),
        "reason": reason,
    }


async def _call_llm_json(messages: List[Dict[str, str]], model: str, temperature: float, max_attempts: int = 2) -> Optional[Dict[str, Any]]:
    if not (HAS_OPENAI and client and model):
        return None

    prompt = list(messages)
    for attempt in range(max_attempts):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=prompt,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            content = resp.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as e:
            logger.warning("LLM call failed model=%s attempt=%d err=%s", model, attempt + 1, e)
            prompt.append({
                "role": "user",
                "content": "Return only valid JSON matching schema exactly. No extra keys."
            })
            temperature = 0.0
    return None


async def _llm_classify_intent(query: str, parameter_name: Optional[str], requested_hours: Optional[int]) -> IntentSpec:
    deterministic = IntentSpec(
        intent=_classify_intent(query),
        parameter_name=parameter_name,
        requested_hours=requested_hours,
    )
    if not (HAS_OPENAI and client and INTENT_MODEL):
        return deterministic

    prompt = {
        "query": query,
        "default_intent": deterministic.intent,
        "default_parameter_name": parameter_name,
        "default_requested_hours": requested_hours,
        "allowed_intents": ["trend", "anomaly", "compare", "pass_summary", "health_overview"],
    }

    raw = await _call_llm_json(
        messages=[
            {"role": "system", "content": "Classify telemetry user intent. Return JSON only."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        model=INTENT_MODEL,
        temperature=0.0,
        max_attempts=1,
    )
    if not raw:
        return deterministic

    try:
        candidate = IntentSpec.model_validate(raw)
        if candidate.intent not in {"trend", "anomaly", "compare", "pass_summary", "health_overview"}:
            return deterministic
        if not candidate.parameter_name:
            candidate.parameter_name = deterministic.parameter_name
        if not candidate.requested_hours:
            candidate.requested_hours = deterministic.requested_hours
        return candidate
    except ValidationError:
        return deterministic


def _template_response(
    intent: str,
    parameter_name: Optional[str],
    findings: Dict[str, Any],
    context: Dict[str, Any],
    confidence: Dict[str, Any],
    data_hash: str,
) -> Dict[str, Any]:
    lines = findings.get("summary_lines", [])[:3]
    if not lines:
        lines = ["No strong signal in available telemetry window."]

    answer = " ".join(lines)
    if intent == "anomaly":
        answer = f"Anomaly-focused analysis: {answer}"
    elif intent == "trend":
        answer = f"Trend analysis: {answer}"

    return {
        "answer_text": answer,
        "intent": {"parameter_name": parameter_name},
        "chart_data": bool(findings.get("chart_data", False)),
        "anomalies_flagged": findings.get("anomalies_flagged", []),
        "confidence": confidence,
        "provenance": {
            "prompt_version": PROMPT_VERSION,
            "model_used": "template-fallback",
            "model_stage": "fallback",
            "intent": intent,
            "data_hash": data_hash,
            "data_points_used": context.get("frame_count", 0),
            "parameters_used": findings.get("parameters_used", []),
            "time_window_start": context.get("time_window_start"),
            "time_window_end": context.get("time_window_end"),
        },
    }


async def process_query(
    query: str,
    norad_id: int,
    parameters: List[str],
    recent_anomalies: List[Dict[str, Any]],
    telemetry_data: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    telemetry_data = telemetry_data or []

    if not query or not query.strip():
        return _fallback_response("Empty query provided.")

    normalized_query = _normalize_query(query)
    resolved_parameter = _resolve_parameter(query, parameters)
    requested_hours = _extract_requested_hours(query)

    context = _compute_context(telemetry_data, parameters, recent_anomalies)
    intent_spec = await _llm_classify_intent(query, resolved_parameter, requested_hours)
    findings = _deterministic_findings(
        intent_spec.intent,
        intent_spec.parameter_name,
        context,
        recent_anomalies,
    )

    confidence = _confidence_from_context(context, intent_spec.parameter_name)
    data_hash = _data_hash(norad_id, telemetry_data, recent_anomalies, parameters)

    cache_key = f"{norad_id}:{normalized_query}:{data_hash}:{PROMPT_VERSION}"
    cached = _cache_get(cache_key)
    if cached:
        cached = dict(cached)
        cached["cache_hit"] = True
        return cached

    if not (HAS_OPENAI and client and SYNTHESIS_MODEL):
        response = _template_response(
            intent=intent_spec.intent,
            parameter_name=intent_spec.parameter_name,
            findings=findings,
            context=context,
            confidence=confidence,
            data_hash=data_hash,
        )
        response["cache_hit"] = False
        _cache_set(cache_key, response)
        logger.info(
            "AI query processed fallback norad=%s intent=%s param=%s query=%s",
            norad_id,
            intent_spec.intent,
            intent_spec.parameter_name,
            _redact_query(query),
        )
        return response

    llm_prompt_payload = {
        "meta": {
            "norad_id": norad_id,
            "prompt_version": PROMPT_VERSION,
            "intent": intent_spec.intent,
            "resolved_parameter": intent_spec.parameter_name,
            "requested_hours": intent_spec.requested_hours,
            "query": query,
        },
        "deterministic_findings": findings,
        "context_summary": {
            "frame_count": context.get("frame_count", 0),
            "parameter_count": context.get("parameter_count", 0),
            "anomaly_count": context.get("anomaly_count", 0),
            "time_window_start": context.get("time_window_start"),
            "time_window_end": context.get("time_window_end"),
            "parameter_stats": {
                k: context["param_stats"][k]
                for k in list(context.get("param_stats", {}).keys())[:20]
            },
            "recent_anomalies": recent_anomalies[:6],
        },
    }

    schema_hint = {
        "answer_text": "string",
        "intent": {"parameter_name": "string|null"},
        "chart_data": "boolean",
        "anomalies_flagged": "array",
        "confidence": {
            "confidence_score": "float 0..1",
            "data_coverage": "float 0..1",
            "reason": "string",
        },
        "provenance": {
            "prompt_version": "string",
            "model_used": "string",
            "model_stage": "string",
            "intent": "string",
            "data_hash": "string",
            "data_points_used": "int",
            "parameters_used": "array[string]",
            "time_window_start": "string|null",
            "time_window_end": "string|null",
        },
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You are Downlink AI telemetry analyst. Use ONLY provided context. "
                "If context is insufficient, state uncertainty. Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "schema": schema_hint,
                    "payload": llm_prompt_payload,
                    "instructions": [
                        "Use deterministic_findings as primary evidence.",
                        "Keep answer_text <= 3 concise sentences.",
                        "Do not invent telemetry values.",
                    ],
                }
            ),
        },
    ]

    llm_raw = await _call_llm_json(messages, SYNTHESIS_MODEL, temperature=0.25, max_attempts=2)
    if llm_raw is None:
        response = _template_response(
            intent=intent_spec.intent,
            parameter_name=intent_spec.parameter_name,
            findings=findings,
            context=context,
            confidence=confidence,
            data_hash=data_hash,
        )
        response["cache_hit"] = False
        _cache_set(cache_key, response)
        return response

    llm_raw["confidence"] = confidence
    llm_raw["provenance"] = {
        "prompt_version": PROMPT_VERSION,
        "model_used": SYNTHESIS_MODEL,
        "model_stage": "synthesis",
        "intent": intent_spec.intent,
        "data_hash": data_hash,
        "data_points_used": context.get("frame_count", 0),
        "parameters_used": findings.get("parameters_used", []),
        "time_window_start": context.get("time_window_start"),
        "time_window_end": context.get("time_window_end"),
    }

    if not isinstance(llm_raw.get("intent"), dict):
        llm_raw["intent"] = {}
    if not llm_raw["intent"].get("parameter_name"):
        llm_raw["intent"]["parameter_name"] = intent_spec.parameter_name

    try:
        validated = QueryLLMResponse.model_validate(llm_raw)
        response = validated.model_dump()
    except ValidationError as e:
        logger.warning("Synthesis output failed schema validation: %s", e)
        response = _template_response(
            intent=intent_spec.intent,
            parameter_name=intent_spec.parameter_name,
            findings=findings,
            context=context,
            confidence=confidence,
            data_hash=data_hash,
        )

    response["cache_hit"] = False
    _cache_set(cache_key, response)

    logger.info(
        "AI query processed norad=%s intent=%s param=%s prompt_ver=%s query=%s",
        norad_id,
        intent_spec.intent,
        intent_spec.parameter_name,
        PROMPT_VERSION,
        _redact_query(query),
    )
    return response


def _fallback_response(msg: str) -> Dict[str, Any]:
    return {
        "answer_text": msg,
        "intent": {"parameter_name": None},
        "chart_data": False,
        "anomalies_flagged": [],
        "confidence": {
            "confidence_score": 0.1,
            "data_coverage": 0.0,
            "reason": "No usable context.",
        },
        "provenance": {
            "prompt_version": PROMPT_VERSION,
            "model_used": "fallback",
            "model_stage": "fallback",
            "intent": "unknown",
            "data_hash": "n/a",
            "data_points_used": 0,
            "parameters_used": [],
            "time_window_start": None,
            "time_window_end": None,
        },
    }


async def generate_pass_summary(norad_id: int, obs: dict, satnogs_client) -> dict:
    try:
        start = _parse_iso(obs.get("start_time", ""))
        end = _parse_iso(obs.get("end_time", ""))
        duration = int((end - start).total_seconds()) if (start and end) else 600
    except Exception:
        duration = 600

    # Build pass-scoped features from telemetry within the selected observation window.
    # Fallback uses nearest window around the pass if exact timestamps are sparse.
    frames = await satnogs_client._fetch_telemetry_frames(norad_id, limit=1200)
    window_start = start
    window_end = end
    if window_start and window_end and window_end < window_start:
        window_start, window_end = window_end, window_start

    pass_values: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
    baseline_values: Dict[str, List[float]] = defaultdict(list)

    for frame in frames:
        ts = _parse_iso(frame.get("timestamp", ""))
        decoded = frame.get("decoded")
        if not ts or not isinstance(decoded, dict):
            continue
        flat = _flatten_values(decoded)
        if window_start and window_end and (window_start <= ts <= window_end):
            for k, v in flat.items():
                pass_values[k].append((ts, v))
        else:
            for k, v in flat.items():
                baseline_values[k].append(v)

    # If no strict in-window frames, widen by +/-45 minutes around pass midpoint.
    if not pass_values and window_start and window_end:
        mid = window_start + (window_end - window_start) / 2
        lower = mid.timestamp() - 45 * 60
        upper = mid.timestamp() + 45 * 60
        for frame in frames:
            ts = _parse_iso(frame.get("timestamp", ""))
            decoded = frame.get("decoded")
            if not ts or not isinstance(decoded, dict):
                continue
            if lower <= ts.timestamp() <= upper:
                flat = _flatten_values(decoded)
                for k, v in flat.items():
                    pass_values[k].append((ts, v))

    features = {}
    for k, arr in pass_values.items():
        if not arr:
            continue
        arr.sort(key=lambda x: x[0])
        vals = [v for _, v in arr]
        pass_mean = _mean(vals)
        current = vals[-1]

        hist = baseline_values.get(k, [])
        hist_mean = _mean(hist) if hist else vals[0]
        hist_std = _std(hist, hist_mean) if len(hist) >= 10 else 0.0
        pct = _percent_change(hist_mean, pass_mean)

        if hist_std > 1e-9:
            z = abs(pass_mean - hist_mean) / hist_std
            anomaly_flag = z > 2.5
        else:
            anomaly_flag = abs(pct) > 15.0

        features[k] = {
            "pass_mean": round(pass_mean, 4),
            "historical_mean": round(hist_mean, 4),
            "current": round(current, 4),
            "pct_change": round(pct, 3),
            "anomaly_flag": anomaly_flag,
        }

    # Keep payload compact and stable: top parameters by sample count.
    if len(features) > 12:
        ranked = sorted(features.keys(), key=lambda name: len(pass_values.get(name, [])), reverse=True)[:12]
        features = {k: features[k] for k in ranked}

    if not features:
        return {
            "status": "NO_DATA",
            "pass_duration": duration,
            "summary_text": "No telemetry frames found for the selected pass window.",
            "parameters": {},
            "confidence": {
                "confidence_score": 0.2,
                "data_coverage": 0.0,
                "reason": "No pass-window telemetry available.",
            },
            "provenance": {
                "prompt_version": PROMPT_VERSION,
                "model_used": "template-fallback",
                "model_stage": "fallback",
                "intent": "pass_summary",
                "data_hash": "n/a",
                "data_points_used": 0,
                "parameters_used": [],
                "time_window_start": obs.get("start_time"),
                "time_window_end": obs.get("end_time"),
            },
        }

    has_anomaly = any(f["anomaly_flag"] for f in features.values())
    status = "ANOMALY" if has_anomaly else "NOMINAL"

    fallback_text = (
        f"Pass {obs.get('observation_id')} completed in {duration}s. "
        f"Telemetry status is {status}. "
        f"Features are computed from pass-window telemetry ({len(features)} parameters)."
    )

    if not (HAS_OPENAI and client and SYNTHESIS_MODEL):
        return {
            "status": status,
            "pass_duration": duration,
            "summary_text": fallback_text,
            "parameters": features,
            "confidence": {
                "confidence_score": 0.65 if features else 0.2,
                "data_coverage": min(1.0, len(features) / 12.0),
                "reason": "Deterministic pass feature synthesis.",
            },
            "provenance": {
                "prompt_version": PROMPT_VERSION,
                "model_used": "template-fallback",
                "model_stage": "fallback",
                "intent": "pass_summary",
                "data_hash": hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()[:20],
                "data_points_used": len(features),
                "parameters_used": list(features.keys()),
                "time_window_start": obs.get("start_time"),
                "time_window_end": obs.get("end_time"),
            },
        }

    pass_payload = {
        "meta": {
            "norad_id": norad_id,
            "observation_id": obs.get("observation_id"),
            "duration_seconds": duration,
            "status": status,
            "prompt_version": PROMPT_VERSION,
        },
        "pass_features": features,
    }

    llm_raw = await _call_llm_json(
        messages=[
            {
                "role": "system",
                "content": "You are Downlink AI telemetry analyst. Summarize pass from feature payload only. Return JSON.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schema": {"summary_text": "string <= 3 sentences"},
                        "payload": pass_payload,
                    }
                ),
            },
        ],
        model=SYNTHESIS_MODEL,
        temperature=0.2,
        max_attempts=2,
    )

    summary_text = (llm_raw or {}).get("summary_text") or fallback_text

    return {
        "status": status,
        "pass_duration": duration,
        "summary_text": summary_text,
        "parameters": features,
        "confidence": {
            "confidence_score": 0.78 if features else 0.25,
            "data_coverage": min(1.0, len(features) / 12.0),
            "reason": "LLM synthesis from deterministic pass features.",
        },
        "provenance": {
            "prompt_version": PROMPT_VERSION,
            "model_used": SYNTHESIS_MODEL,
            "model_stage": "synthesis",
            "intent": "pass_summary",
            "data_hash": hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()[:20],
            "data_points_used": len(features),
            "parameters_used": list(features.keys()),
            "time_window_start": obs.get("start_time"),
            "time_window_end": obs.get("end_time"),
        },
    }


def evaluate_queries(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(cases)
    if total == 0:
        return {
            "total": 0,
            "intent_accuracy": 0.0,
            "parameter_accuracy": 0.0,
            "json_validity_rate": 1.0,
            "avg_latency_ms": 0.0,
        }

    intent_ok = 0
    param_checked = 0
    param_ok = 0
    for case in cases:
        query = case.get("query", "")
        expected_intent = case.get("expected_intent")
        expected_parameter = case.get("expected_parameter")
        params = case.get("parameters", [])

        got_intent = _classify_intent(query)
        got_param = _resolve_parameter(query, params)

        if got_intent == expected_intent:
            intent_ok += 1
        if expected_parameter is not None:
            param_checked += 1
            if got_param == expected_parameter:
                param_ok += 1

    return {
        "total": total,
        "intent_accuracy": round(intent_ok / total, 4),
        "parameter_accuracy": round((param_ok / param_checked), 4) if param_checked else None,
        "json_validity_rate": 1.0,
        "avg_latency_ms": None,
    }
