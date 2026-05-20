"""
Downlink FastAPI Backend.

Implements the REST API contract expected by the Next.js frontend.
Coordinates data fetching from SatNOGS, anomaly detection, trend
analysis, and AI queries.
"""

import os
import re
import time
import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from satnogs_client import SatNOGSClient
from anomaly_detector import detect_anomalies
from trend_analyzer import analyze_trend
import ai_engine

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Verify required token
SATNOGS_TOKEN = os.getenv("SATNOGS_API_TOKEN")
if not SATNOGS_TOKEN:
    logger.warning("SATNOGS_API_TOKEN not found in environment. Data fetching will likely fail.")

# Global state for the client
satnogs_client: SatNOGSClient = None
query_rate_window_s = int(os.getenv("QUERY_RATE_WINDOW_S", "60"))
query_rate_limit = int(os.getenv("QUERY_RATE_LIMIT", "24"))
_query_rate_store: dict[str, deque[float]] = defaultdict(deque)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global satnogs_client
    satnogs_client = SatNOGSClient(api_token=SATNOGS_TOKEN or "")
    await satnogs_client.init()
    yield
    await satnogs_client.close()

app = FastAPI(
    title="Downlink API",
    description="Backend for Downlink ground station telemetry platform",
    lifespan=lifespan
)

# Allow CORS for development (Next.js rewrite handles it mostly, but good to have)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_client() -> SatNOGSClient:
    return satnogs_client


def _query_rate_key(request: Request, norad_id: int) -> str:
    ip = "unknown"
    if request and request.client and request.client.host:
        ip = request.client.host
    return f"{ip}:{norad_id}"


def _enforce_query_rate_limit(request: Request, norad_id: int):
    key = _query_rate_key(request, norad_id)
    now = time.time()
    window = _query_rate_store[key]
    while window and (now - window[0]) > query_rate_window_s:
        window.popleft()
    if len(window) >= query_rate_limit:
        raise HTTPException(status_code=429, detail="Too many AI queries. Please retry shortly.")
    window.append(now)


def _redact_user_query(q: str) -> str:
    if not q:
        return ""
    redacted = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", q)
    redacted = re.sub(r"\b\d{9,}\b", "[LONG_NUMBER]", redacted)
    return redacted[:300]

# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/satellites")
async def list_satellites(client: SatNOGSClient = Depends(get_client)):
    """Get the catalog of curated satellites."""
    satellites = await client.get_satellites()
    return {"satellites": satellites}

@app.get("/satellites/{norad_id}")
async def get_satellite_detail(norad_id: int, client: SatNOGSClient = Depends(get_client)):
    """Get rich detail for a single satellite."""
    sat = await client.get_satellite(norad_id)
    if not sat:
        raise HTTPException(status_code=404, detail="Satellite not found")

    parameters = await client.get_parameters(norad_id)
    summaries = await client.get_parameter_summaries(norad_id)
    passes = await client.get_observations(norad_id, limit=10)

    return {
        "satellite": sat,
        "parameters": parameters,
        "parameter_summaries": summaries,
        "recent_passes": passes,
        "parameter_count": len(parameters)
    }

@app.get("/satellites/{norad_id}/telemetry")
async def get_telemetry(norad_id: int, parameter: Optional[str] = None, last_n: int = 100, client: SatNOGSClient = Depends(get_client)):
    """Get time-series telemetry values."""
    values, is_simulated = await client.get_telemetry(norad_id, parameter, last_n)
    return {"values": values, "is_simulated": is_simulated}

@app.get("/satellites/{norad_id}/anomalies")
async def get_anomalies(norad_id: int, client: SatNOGSClient = Depends(get_client)):
    """Detect anomalies in recent telemetry."""
    # Fetch a decent chunk of recent frames to build the statistical baseline
    frames = await client._fetch_telemetry_frames(norad_id, limit=200)
    anomalies = detect_anomalies(frames)
    return {
        "count": len(anomalies),
        "anomalies": anomalies
    }

@app.get("/satellites/{norad_id}/trend/{parameter}")
async def get_trend(norad_id: int, parameter: str, client: SatNOGSClient = Depends(get_client)):
    """Get trend analysis and anomalies for a specific parameter."""
    frames = await client._fetch_telemetry_frames(norad_id, limit=200)
    
    # 1. Trend
    trend_info = analyze_trend(frames, parameter)
    
    # 2. Filter anomalies just for this parameter
    all_anomalies = detect_anomalies(frames)
    param_anomalies = [a for a in all_anomalies if a["parameter_name"] == parameter]

    return {
        "trend": trend_info,
        "anomalies": param_anomalies
    }

@app.get("/satellites/{norad_id}/observations/{obs_id}/summary")
async def get_pass_summary(norad_id: int, obs_id: str, client: SatNOGSClient = Depends(get_client)):
    """Get an AI-generated summary for a specific pass."""
    passes = await client.get_observations(norad_id, limit=20)
    obs = next((p for p in passes if str(p.get("observation_id")) == obs_id), None)
    
    if not obs:
         raise HTTPException(status_code=404, detail="Observation not found")
         
    summary = await ai_engine.generate_pass_summary(norad_id, obs, client)
    return summary

class QueryRequest(BaseModel):
    query: str

@app.post("/satellites/{norad_id}/query")
async def submit_query(norad_id: int, req: QueryRequest, request: Request, client: SatNOGSClient = Depends(get_client)):
    """Process a natural language query."""
    _enforce_query_rate_limit(request, norad_id)
    logger.info(
        "AI query request norad=%s prompt_ver=%s query=%s",
        norad_id,
        ai_engine.PROMPT_VERSION,
        _redact_user_query(req.query),
    )

    parameters = await client.get_parameters(norad_id)
    frames = await client._fetch_telemetry_frames(norad_id, limit=100)
    recent_anomalies = detect_anomalies(frames)
    
    response = await ai_engine.process_query(req.query, norad_id, parameters, recent_anomalies, telemetry_data=frames)
    return response

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
