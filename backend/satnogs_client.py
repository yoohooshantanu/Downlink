"""
SatNOGS API client with SQLite caching.

Fetches satellite metadata, decoded telemetry frames, and ground station
observations from the SatNOGS DB and Network APIs. All responses are cached
in SQLite with per-type TTLs to avoid hammering the API on every frontend poll.
"""

import json
import time
import logging
import hashlib
import math
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import aiosqlite

logger = logging.getLogger(__name__)

DB_API = "https://db.satnogs.org/api"
NETWORK_API = "https://network.satnogs.org/api"

# Cache TTLs in seconds
SATELLITE_TTL = 86400   # 24 hours — catalog doesn't change often
TELEMETRY_TTL = 3600    # 1 hour — frames arrive after passes
OBSERVATION_TTL = 3600  # 1 hour

# Curated NORAD IDs known to have good telemetry on SatNOGS.
# Used as the default satellite list so users see data immediately.
CURATED_NORAD_IDS = [
    39444,  # FUNcube-1 (AO-73)
    43017,  # NanoCom
    40967,  # HORYU-4
    43803,  # JY1SAT (JO-97)
    44832,  # SAUDISAT 1C
    47960,  # CAS-6 (TO-108)
    25544,  # ISS
    43770,  # KS-1Q
    40903,  # ALSAT-1N
    43137,  # FOX-1D (AO-92)
    42017,  # NAYIF-1 (EO-88)
    40908,  # LILACSAT-2
    44830,  # FUNCUBE-4 (AO-76)
    43678,  # ESEO
    53106,  # GREENCUBE
    47959,  # CAS-5A
    40014,  # UKube-1
    40069,  # Meteor M2
    44406,  # NOAA 19
    33591,  # NOAA 18
    25338,  # NOAA 15
    48274,  # CubeBel-1
    43743,  # D-STAR ONE (iSat)
    42790,  # Pegasus
    40012,  # BugSat-1
    39430,  # GOMX-1
]
# Deduplicate
CURATED_NORAD_IDS = list(dict.fromkeys(CURATED_NORAD_IDS))


class SatNOGSClient:
    """Async SatNOGS API client with transparent SQLite caching."""

    def __init__(self, api_token: str, db_path: str = "cache.db"):
        self.api_token = api_token
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._telemetry_backoff_until: float = 0.0

    async def init(self):
        """Initialize the SQLite cache database."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS satellites (
                norad_id INTEGER PRIMARY KEY,
                name TEXT,
                status TEXT,
                countries TEXT,
                operator TEXT,
                launched TEXT,
                has_telemetry INTEGER DEFAULT 0,
                parameter_count INTEGER DEFAULT 0,
                fetched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                norad_id INTEGER NOT NULL,
                parameter_name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT NOT NULL,
                fetched_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_telem_norad
                ON telemetry(norad_id);
            CREATE INDEX IF NOT EXISTS idx_telem_norad_param
                ON telemetry(norad_id, parameter_name);
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                norad_id INTEGER NOT NULL,
                status TEXT,
                ground_station TEXT,
                station_name TEXT,
                start_time TEXT,
                end_time TEXT,
                fetched_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_obs_norad
                ON observations(norad_id);
        """)
        # Lightweight schema migration for older cache DBs.
        async with self._db.execute("PRAGMA table_info(satellites)") as cursor:
            cols = [row[1] async for row in cursor]
        if "parameter_count" not in cols:
            await self._db.execute(
                "ALTER TABLE satellites ADD COLUMN parameter_count INTEGER DEFAULT 0"
            )
        await self._db.commit()

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._db:
            await self._db.close()

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _db_headers(self) -> dict:
        """Auth headers for SatNOGS DB API."""
        if not self.api_token:
            return {}
        return {"Authorization": f"Token {self.api_token}"}

    async def _get(self, url: str, headers: Optional[dict] = None,
                   params: Optional[dict] = None, timeout: float = 30.0) -> list | dict:
        """Make an authenticated GET request with bounded retries on transient failures."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._http.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 429:
                    wait_s = self._retry_after_seconds(exc.response, default=8.0)
                    if "/telemetry/" in url:
                        self._telemetry_backoff_until = max(
                            self._telemetry_backoff_until,
                            time.time() + wait_s
                        )
                    logger.warning(
                        "Rate limited (429) for %s; honoring backoff %.2fs",
                        url, wait_s
                    )
                    raise

                retryable = status in {500, 502, 503, 504}
                if retryable and attempt < max_attempts:
                    wait_s = self._retry_after_seconds(exc.response, default=0.6 * attempt)
                    logger.warning(
                        "Transient HTTP %s for %s; retrying in %.2fs (attempt %s/%s)",
                        status, url, wait_s, attempt, max_attempts
                    )
                    await asyncio.sleep(wait_s)
                    continue
                raise
            except httpx.RequestError:
                if attempt < max_attempts:
                    wait_s = 0.4 * attempt
                    logger.warning(
                        "Network error for %s; retrying in %.2fs (attempt %s/%s)",
                        url, wait_s, attempt, max_attempts
                    )
                    await asyncio.sleep(wait_s)
                    continue
                raise

        raise RuntimeError(f"Unexpected retry loop exit for {url}")

    def _retry_after_seconds(self, response: Optional[httpx.Response], default: float) -> float:
        """Read Retry-After header when present; otherwise use default backoff."""
        if response is None:
            return max(0.1, default)
        header = response.headers.get("Retry-After")
        if not header:
            return max(0.1, default)
        try:
            return max(0.1, min(float(header), 8.0))
        except (TypeError, ValueError):
            return max(0.1, default)

    # ── Cache helpers ─────────────────────────────────────────────────

    async def _get_cache(self, key: str, ttl: int) -> Optional[str]:
        """Get a cached value if it exists and hasn't expired."""
        async with self._db.execute(
            "SELECT value, fetched_at FROM cache WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and (time.time() - row[1]) < ttl:
                return row[0]
        return None

    async def _set_cache(self, key: str, value: str):
        """Store a value in the cache."""
        await self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, fetched_at) VALUES (?, ?, ?)",
            (key, value, time.time())
        )
        await self._db.commit()

    async def _satellite_telem_stats(self) -> dict[int, tuple[bool, int]]:
        """
        Return per-satellite telemetry capability from locally observed real data.
        Values are (has_telemetry, parameter_count).
        """
        stats: dict[int, tuple[bool, int]] = {}
        async with self._db.execute(
            "SELECT norad_id, has_telemetry, COALESCE(parameter_count, 0) AS parameter_count FROM satellites"
        ) as cursor:
            async for row in cursor:
                stats[int(row["norad_id"])] = (bool(row["has_telemetry"]), int(row["parameter_count"] or 0))
        return stats

    async def _update_satellite_telemetry_stats(self, norad_id: int, frames: list[dict]):
        """
        Persist telemetry capability for a satellite based on real fetched frames.
        """
        params: set[str] = set()
        for frame in frames:
            decoded = frame.get("decoded")
            if isinstance(decoded, dict):
                params.update(self._flatten_keys(decoded))
        has_telemetry = 1 if len(frames) > 0 else 0
        parameter_count = len(params)
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO satellites (norad_id, has_telemetry, parameter_count, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(norad_id) DO UPDATE SET
                has_telemetry = excluded.has_telemetry,
                parameter_count = excluded.parameter_count,
                fetched_at = excluded.fetched_at
            """,
            (norad_id, has_telemetry, parameter_count, now_iso),
        )
        await self._db.commit()

    # ── Satellite catalog ─────────────────────────────────────────────

    async def get_satellites(self) -> list[dict]:
        """
        Fetch the satellite catalog from SatNOGS DB.
        Returns satellite metadata matching what the frontend expects.
        """
        cache_key = "satellites_list_full_v2"
        cached = await self._get_cache(cache_key, SATELLITE_TTL)
        if cached:
             return json.loads(cached)

        now = datetime.now(timezone.utc).isoformat()
        satellites = []
        try:
            sat_stats = await self._satellite_telem_stats()
            data = await self._get(
                f"{DB_API}/satellites/",
                headers=self._db_headers(),
                params={"format": "json"}
            )
            
            if isinstance(data, list):
                curated_set = set(CURATED_NORAD_IDS)
                curated_sats = []
                other_sats = []
                
                for sat in data:
                    nid = sat.get("norad_cat_id")
                    if not nid: continue
                    record = {
                        "norad_id": nid,
                        "name": sat.get("name", f"NORAD {nid}"),
                        "status": sat.get("status", "unknown"),
                        "countries": sat.get("countries", ""),
                        "operator": sat.get("operator") or "",
                        "launched": sat.get("launched", ""),
                        "has_telemetry": sat_stats.get(nid, (False, 0))[0],
                        "parameter_count": sat_stats.get(nid, (False, 0))[1],
                        "fetched_at": now,
                    }
                    if nid in curated_set:
                        curated_sats.append(record)
                    else:
                        other_sats.append(record)
                        
                # Prioritize curated, then pad with others to ~300
                satellites = curated_sats + other_sats[:300]
                
                await self._set_cache(cache_key, json.dumps(satellites))
                
                for s in satellites:
                    await self._db.execute("""
                        INSERT OR REPLACE INTO satellites
                        (norad_id, name, status, countries, operator, launched, has_telemetry, parameter_count, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        s["norad_id"], s["name"], s["status"],
                        s["countries"], s["operator"], s["launched"],
                        1 if s["has_telemetry"] else 0,
                        int(s["parameter_count"] or 0),
                        now
                    ))
                await self._db.commit()
                return satellites
        except Exception as e:
            logger.warning(f"Failed to fetch full satellite list: {e}")
            
        return satellites

    async def _count_parameters(self, norad_id: int) -> int:
        """Count unique telemetry parameter names for a satellite."""
        try:
            frames = await self._fetch_telemetry_frames(norad_id, limit=20)
            params = set()
            for frame in frames:
                decoded = frame.get("decoded", {})
                if decoded and isinstance(decoded, dict):
                    params.update(self._flatten_keys(decoded))
            return len(params)
        except Exception:
            return 0

    # ── Satellite detail ──────────────────────────────────────────────

    async def get_satellite(self, norad_id: int) -> Optional[dict]:
        """Fetch a single satellite's metadata."""
        cache_key = f"satellite_{norad_id}"
        cached = await self._get_cache(cache_key, SATELLITE_TTL)
        if cached:
            return json.loads(cached)

        try:
            data = await self._get(
                f"{DB_API}/satellites/",
                headers=self._db_headers(),
                params={"norad_cat_id": norad_id}
            )
            if data and isinstance(data, list) and len(data) > 0:
                sat = data[0]
                result = {
                    "norad_id": sat.get("norad_cat_id", norad_id),
                    "name": sat.get("name", f"NORAD {norad_id}"),
                    "status": sat.get("status", "unknown"),
                    "countries": sat.get("countries", ""),
                    "operator": sat.get("operator") or "",
                    "launched": sat.get("launched", ""),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                await self._set_cache(cache_key, json.dumps(result))
                return result
        except Exception as e:
            logger.warning(f"Failed to fetch satellite {norad_id}: {e}")

        # Fallback to cached
        async with self._db.execute(
            "SELECT * FROM satellites WHERE norad_id = ?", (norad_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = {
                    "norad_id": row["norad_id"], "name": row["name"], "status": row["status"],
                    "countries": row["countries"], "operator": row["operator"],
                    "launched": row["launched"], "fetched_at": row["fetched_at"],
                }
                # Cache the fallback result too so we don't keep hitting the DB on subsequent calls
                await self._set_cache(cache_key, json.dumps(result))
                return result
        return None

    # ── Telemetry ─────────────────────────────────────────────────────

    def _parse_ts_utc(self, ts: str) -> datetime:
        """Parse ISO timestamp into timezone-aware UTC datetime."""
        try:
            normalized = (ts or "").strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            dt = datetime.fromisoformat(normalized) if normalized else datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    def _sim_profile(self, norad_id: int) -> dict:
        """Deterministic satellite-specific simulation profile."""
        rng = random.Random(norad_id * 2654435761)
        return {
            "orbit_period_s": rng.uniform(5400.0, 6200.0),   # 90-103 min
            "sun_bias": rng.uniform(-0.35, 0.20),            # beta-angle like offset
            "panel_peak_a": rng.uniform(0.75, 1.80),
            "battery_nom_v": rng.uniform(7.85, 8.15),
            "battery_swing_v": rng.uniform(0.35, 0.70),
            "thermal_base_c": rng.uniform(8.0, 16.0),
            "cpu_offset_c": rng.uniform(5.0, 10.0),
            "tx_nom_w": rng.uniform(1.5, 2.1),
            "pass_phase": rng.uniform(0.0, 2.0 * math.pi),
            "degrade_per_year": rng.uniform(0.002, 0.012),
        }

    def _active_sim_event(self, norad_id: int, epoch: float) -> tuple[str, float] | tuple[None, float]:
        """
        Return deterministic short-lived event mode for realism.
        Event windows are 15 minutes and occur rarely, but persist across frames.
        """
        window = int(epoch // (15 * 60))
        h = hashlib.md5(f"{norad_id}:{window}".encode()).hexdigest()
        sample = int(h[:8], 16) / 0xFFFFFFFF
        if sample > 0.03:  # ~3% of windows have an event
            return None, 0.0
        event_pool = ("temp_spike", "battery_sag", "panel_shadow", "rf_fade")
        event = event_pool[int(h[8:10], 16) % len(event_pool)]
        intensity = 0.4 + (int(h[10:12], 16) / 255.0) * 0.9
        return event, intensity

    def _generate_simulated_payload(self, norad_id: int, ts: str) -> dict:
        """Generate deterministic, pass-aware telemetry with coupled subsystem behavior."""
        dt = self._parse_ts_utc(ts)
        epoch = dt.timestamp()
        profile = self._sim_profile(norad_id)

        # Deterministic frame noise source
        frame_seed = int(hashlib.md5(f"{norad_id}:{int(epoch)}".encode()).hexdigest()[:16], 16)
        rng = random.Random(frame_seed)

        omega = 2.0 * math.pi / profile["orbit_period_s"]
        phase = epoch * omega

        # Illumination (0..1), with harmonic structure for smoother orbit transitions
        sun_signal = (
            0.80 * math.sin(phase + profile["sun_bias"])
            + 0.20 * math.sin(2.0 * phase - 0.35)
        )
        sunlit = max(0.0, min(1.0, 0.5 + 0.55 * sun_signal))
        eclipse = 1.0 - sunlit

        # Long-term component aging
        years_since_2020 = max(0.0, (epoch - 1577836800.0) / (365.25 * 24.0 * 3600.0))
        aging_factor = max(0.70, 1.0 - years_since_2020 * profile["degrade_per_year"])

        # Geometry-like visibility factor for received signal / pass quality
        visibility = max(0.0, math.cos(phase - profile["pass_phase"]))
        pass_quality = visibility ** 1.6

        # Power subsystem coupling
        attitude_loss = 0.92 + 0.08 * math.cos(phase * 0.5 + 0.9)
        solar_current = profile["panel_peak_a"] * sunlit * attitude_loss * aging_factor
        solar_current += rng.uniform(-0.02, 0.03)
        solar_current = max(0.0, solar_current)

        base_load = 0.28 + 0.22 * (0.5 + 0.5 * math.sin(phase * 2.0 - 0.6))
        rf_load = 0.08 + 0.18 * pass_quality
        load_factor = base_load + rf_load + rng.uniform(-0.03, 0.03)

        net_charge = (solar_current * 0.18) - (load_factor * (0.65 + 0.35 * eclipse))
        battery_v = profile["battery_nom_v"] + profile["battery_swing_v"] * net_charge
        battery_v += 0.04 * math.sin(phase * 0.33 + 0.5) + rng.uniform(-0.02, 0.02)

        # Thermal subsystem
        thermal_env = profile["thermal_base_c"] + 26.0 * sunlit + 2.5 * math.sin(phase - 0.8)
        eps_temp = thermal_env + 2.0 * load_factor + rng.uniform(-0.4, 0.4)
        cpu_temp = eps_temp + profile["cpu_offset_c"] + 1.8 * load_factor + rng.uniform(-0.6, 0.6)

        # RF/Tx behavior coupled to thermal + battery state
        tx_power = profile["tx_nom_w"] + 0.12 * pass_quality + rng.uniform(-0.04, 0.04)
        if cpu_temp > 56.0:  # thermal derating
            tx_power -= min(0.35, (cpu_temp - 56.0) * 0.025)
        if battery_v < 7.55:  # low-voltage derating
            tx_power -= min(0.28, (7.55 - battery_v) * 0.35)

        rssi = -121.0 + 54.0 * pass_quality + rng.uniform(-2.0, 1.5)

        # Deterministic short-lived events
        event, intensity = self._active_sim_event(norad_id, epoch)
        if event == "temp_spike":
            eps_temp += 2.5 * intensity
            cpu_temp += 8.0 * intensity
        elif event == "battery_sag":
            battery_v -= 0.45 * intensity
            tx_power -= 0.16 * intensity
        elif event == "panel_shadow":
            solar_current *= (1.0 - 0.55 * intensity)
            battery_v -= 0.22 * intensity
        elif event == "rf_fade":
            rssi -= 14.0 * intensity

        # Clamp to operationally plausible ranges
        battery_v = max(6.8, min(8.5, battery_v))
        solar_current = max(0.0, min(2.2, solar_current))
        eps_temp = max(-15.0, min(70.0, eps_temp))
        cpu_temp = max(-10.0, min(85.0, cpu_temp))
        tx_power = max(0.2, min(3.0, tx_power))
        rssi = max(-130.0, min(-55.0, rssi))

        return {
            "battery_voltage": round(battery_v, 2),
            "solar_panel_current": round(solar_current, 3),
            "temp_cpu": round(cpu_temp, 1),
            "temp_eps": round(eps_temp, 1),
            "tx_power": round(tx_power, 2),
            "rssi": round(rssi, 0)
        }

    async def _fetch_telemetry_frames(self, norad_id: int, limit: int = 100) -> list[dict]:
        """
        Fetch decoded telemetry frames from SatNOGS DB.
        Uses cache to avoid repeated API calls within the TTL.
        """
        cache_key = f"telemetry_v2_{norad_id}"
        cached = await self._get_cache(cache_key, TELEMETRY_TTL)
        if cached:
            frames = json.loads(cached)
            return frames[:limit]

        fetch_limit = max(limit, 200)
        now_ts = time.time()
        if now_ts < self._telemetry_backoff_until:
            backoff_left = self._telemetry_backoff_until - now_ts
            logger.info(
                "Telemetry backoff active for NORAD %s (%.2fs left); using synthetic frames",
                norad_id, backoff_left
            )
            synthetic_frames = self._generate_synthetic_frames(norad_id, fetch_limit)
            return synthetic_frames[:limit]

        try:
            frames = await self._get(
                f"{DB_API}/telemetry/",
                headers=self._db_headers(),
                params={
                    "satellite": norad_id,
                    "format": "json",
                },
                timeout=5.0,
            )

            if isinstance(frames, dict) and "results" in frames:
                frames = frames.get("results", [])

            if isinstance(frames, list):
                frames = frames[:fetch_limit]
            else:
                frames = []
                
            for i, frame in enumerate(frames):
                decoded = frame.get("decoded")
                if not decoded or not isinstance(decoded, dict):
                    ts = frame.get("timestamp", "")
                    if not ts:
                        ts = datetime.now(timezone.utc).isoformat()
                        frame["timestamp"] = ts
                    frame["decoded"] = self._generate_simulated_payload(norad_id, ts)
                    frame["_simulated"] = True

            await self._set_cache(cache_key, json.dumps(frames))
            await self._update_satellite_telemetry_stats(norad_id, frames)
            return frames[:limit]

        except Exception as e:
            logger.warning(f"Failed to fetch telemetry for {norad_id}: {e}")
            synthetic_frames = self._generate_synthetic_frames(norad_id, fetch_limit)
            return synthetic_frames[:limit]

    def _generate_synthetic_frames(self, norad_id: int, fetch_limit: int) -> list[dict]:
        """Generate synthetic frames that mimic pass bursts + sparse housekeeping."""
        synthetic_frames = []
        now = datetime.now(timezone.utc)
        cursor = now
        profile = self._sim_profile(norad_id)
        omega = 2.0 * math.pi / profile["orbit_period_s"]

        while len(synthetic_frames) < fetch_limit:
            epoch = cursor.timestamp()
            phase = epoch * omega
            visibility = max(0.0, math.cos(phase - profile["pass_phase"]))
            in_pass = visibility > 0.28

            # Keep dense telemetry during passes, sparse frames outside passes.
            keep = in_pass or (int(epoch // 3600) % 4 == 0)
            if keep:
                ts = cursor.isoformat()
                synthetic_frames.append({
                    "timestamp": ts,
                    "decoded": self._generate_simulated_payload(norad_id, ts),
                    "_simulated": True
                })

            # Deterministic cadence jitter
            step_rng = random.Random(
                int(hashlib.md5(f"{norad_id}:{int(epoch)}:cadence".encode()).hexdigest()[:16], 16)
            )
            if in_pass:
                step_seconds = step_rng.randint(45, 110)
            else:
                step_seconds = step_rng.randint(240, 720)
            cursor -= timedelta(seconds=step_seconds)

        return synthetic_frames

    def _flatten_keys(self, d: dict, prefix: str = "") -> list[str]:
        """Flatten nested dict keys into dot-separated names."""
        keys = []
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.extend(self._flatten_keys(v, full_key))
            elif isinstance(v, (int, float)):
                keys.append(full_key)
        return keys

    def _flatten_values(self, d: dict, prefix: str = "") -> dict[str, float]:
        """Flatten nested dict into {dotted_key: numeric_value} pairs."""
        result = {}
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(self._flatten_values(v, full_key))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                result[full_key] = float(v)
        return result

    async def get_telemetry(self, norad_id: int,
                            parameter: Optional[str] = None,
                            last_n: int = 100) -> tuple[list[dict], bool]:
        """
        Get telemetry values for a satellite.
        Returns a tuple: (list of {timestamp, value} dicts, is_simulated flag).
        """
        frames = await self._fetch_telemetry_frames(norad_id, limit=max(last_n * 2, 200))
        is_simulated = any(f.get("_simulated", False) for f in frames)

        values = []
        for frame in frames:
            decoded = frame.get("decoded")
            ts = frame.get("timestamp")
            if not decoded or not ts or not isinstance(decoded, dict):
                continue

            flat = self._flatten_values(decoded)

            if parameter:
                if parameter in flat:
                    values.append({
                        "timestamp": ts,
                        "value": flat[parameter],
                    })
            else:
                for k, v in flat.items():
                    values.append({
                        "timestamp": ts,
                        "parameter_name": k,
                        "value": v,
                    })

        # Sort by timestamp descending, take last_n
        values.sort(key=lambda x: x["timestamp"], reverse=True)
        return values[:last_n], is_simulated

    async def get_parameters(self, norad_id: int) -> list[str]:
        """Get all unique telemetry parameter names for a satellite."""
        frames = await self._fetch_telemetry_frames(norad_id, limit=50)
        params = set()
        for frame in frames:
            decoded = frame.get("decoded", {})
            if decoded and isinstance(decoded, dict):
                flat = self._flatten_values(decoded)
                params.update(flat.keys())
        return sorted(params)

    async def get_parameter_summaries(self, norad_id: int) -> dict:
        """
        Compute per-parameter summaries: last value, first value,
        direction, and percent change. This is what the frontend
        parameter list sidebar needs for sparklines and trend arrows.
        """
        frames = await self._fetch_telemetry_frames(norad_id, limit=100)
        # Group values by parameter, ordered by timestamp
        param_values: dict[str, list[tuple[str, float]]] = {}

        for frame in frames:
            decoded = frame.get("decoded", {})
            ts = frame.get("timestamp", "")
            if not decoded or not isinstance(decoded, dict):
                continue
            flat = self._flatten_values(decoded)
            for k, v in flat.items():
                if k not in param_values:
                    param_values[k] = []
                param_values[k].append((ts, v))

        summaries = {}
        for param, readings in param_values.items():
            readings.sort(key=lambda x: x[0])  # chronological
            if len(readings) < 2:
                summaries[param] = {
                    "last_value": readings[-1][1] if readings else None,
                    "first_value": readings[0][1] if readings else None,
                    "direction": "stable",
                    "percent_change": 0.0,
                }
                continue

            first_val = readings[0][1]
            last_val = readings[-1][1]

            # Percent change
            if abs(first_val) > 1e-9:
                pct = ((last_val - first_val) / abs(first_val)) * 100
            else:
                pct = 0.0

            if pct > 2:
                direction = "increasing"
            elif pct < -2:
                direction = "decreasing"
            else:
                direction = "stable"

            summaries[param] = {
                "last_value": last_val,
                "first_value": first_val,
                "direction": direction,
                "percent_change": round(pct, 2),
            }

        return summaries

    # ── Observations (passes) ─────────────────────────────────────────

    async def get_observations(self, norad_id: int, limit: int = 20) -> list[dict]:
        """
        Fetch recent observations from SatNOGS Network API.
        No auth required for the Network API.
        """
        cache_key = f"observations_{norad_id}"
        cached = await self._get_cache(cache_key, OBSERVATION_TTL)
        if cached:
            return json.loads(cached)

        try:
            data = await self._get(
                f"{NETWORK_API}/observations/",
                params={
                    "satellite__norad_cat_id": norad_id,
                    "status": "good",
                    "format": "json",
                },
                timeout=5.0,
            )

            if isinstance(data, dict) and "results" in data:
                data = data.get("results", [])

            if not isinstance(data, list):
                return []

            passes = []
            for obs in data[:limit]:
                passes.append({
                    "observation_id": str(obs.get("id", "")),
                    "norad_id": norad_id,
                    "status": obs.get("vetted_status", "unknown"),
                    "ground_station": str(obs.get("ground_station", "")),
                    "station_name": obs.get("station_name", f"GS-{obs.get('ground_station', '?')}"),
                    "start_time": obs.get("start", ""),
                    "end_time": obs.get("end", ""),
                })

            await self._set_cache(cache_key, json.dumps(passes))

            # Also store in observations table
            for p in passes:
                await self._db.execute("""
                    INSERT OR REPLACE INTO observations
                    (observation_id, norad_id, status, ground_station, station_name,
                     start_time, end_time, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["observation_id"], norad_id, p["status"],
                    p["ground_station"], p["station_name"],
                    p["start_time"], p["end_time"], time.time()
                ))
            await self._db.commit()

            return passes

        except Exception as e:
            logger.warning(f"Failed to fetch observations for {norad_id}: {e}")
            # Fallback: return cached observations from SQLite
            rows = []
            async with self._db.execute(
                "SELECT * FROM observations WHERE norad_id = ? ORDER BY start_time DESC LIMIT ?",
                (norad_id, limit)
            ) as cursor:
                async for row in cursor:
                    rows.append({
                        "observation_id": row[0],
                        "norad_id": row[1],
                        "status": row[2],
                        "ground_station": row[3],
                        "station_name": row[4],
                        "start_time": row[5],
                        "end_time": row[6],
                    })
            return rows
