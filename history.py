"""
NAKSHATRA AI - Provider-aware history layer.

Delta is used ONLY for BTC/ETH.
Kotak Neo is used for Indian indices and MCX.

Public API kept compatible:
    get_history(symbol, resolution, limit)
    get_multi_timeframe_history(symbol, limit)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import threading
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd

from logger import logger
from market_registry import canonical_symbol, get_market
from kotak_neo import get_history as kotak_get_history

RESOLUTIONS = ("5m", "15m", "1h", "1d", "1w", "1mo")

# ---------------------------------------------------------------------------
# Provider-aware cache/config
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 200
_KOTAK_FETCH_LIMIT = 240
_CACHE_TTL = 30.0
# Keep a usable historical snapshot available between live refreshes.  Kotak
# historical endpoints are rate-limited, so these TTLs are deliberately much
# longer than the dashboard polling interval.
_STALE_FALLBACK_SECONDS = 300.0

# Historical candles for MCX are intentionally not requested through this
# layer; live MCX quotes are handled by kotak_neo.py.
MCX_SYMBOLS = {"GOLD", "SILVER", "CRUDEOIL"}

_TIMEFRAME_TTL = {
    "5m": 60.0,
    "15m": 180.0,
    "1h": 600.0,
    "1d": 1800.0,
    "1w": 3600.0,
    "1mo": 7200.0,
}

_CACHE = {}
_KOTAK_LOCKS = {}


def _empty():
    return pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )


def _kotak_lock(symbol, timeframe):
    key = (str(symbol).upper(), str(timeframe).lower())
    lock = _KOTAK_LOCKS.get(key)
    if lock is None:
        lock = threading.Lock()
        _KOTAK_LOCKS[key] = lock
    return lock


def _market_is_open_now():
    """Return True during the normal NSE cash/index session (IST)."""
    try:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        if now.weekday() >= 5:
            return False
        return dt_time(9, 15) <= now.time() <= dt_time(15, 30)
    except Exception:
        # If timezone support ever fails, retain the conservative behaviour.
        return True


def _timeframe_max_age_seconds(timeframe):
    """Normal freshness limits while the market is open."""
    return {
        "5m": 15 * 60,
        "15m": 45 * 60,
        "1h": 3 * 60 * 60,
        "1d": 3 * 24 * 60 * 60,
        "1w": 14 * 24 * 60 * 60,
        "1mo": 62 * 24 * 60 * 60,
    }.get(str(timeframe).lower(), 24 * 60 * 60)


def _closed_market_max_age_seconds(timeframe):
    """Allow the last completed NSE session after market close/weekends.

    Historical candles do not advance while the cash/index market is closed.
    Treating a 3:25 PM candle as 'stale' at 7 PM incorrectly turned the whole
    technical/MTF engine into UNKNOWN.  These limits are intentionally bounded
    so genuinely old data is still rejected.
    """
    return {
        "5m": 72 * 60 * 60,
        "15m": 96 * 60 * 60,
        "1h": 7 * 24 * 60 * 60,
        "1d": 14 * 24 * 60 * 60,
        "1w": 30 * 24 * 60 * 60,
        "1mo": 90 * 24 * 60 * 60,
    }.get(str(timeframe).lower(), 72 * 60 * 60)


def _last_candle_age_seconds(df):
    if df is None or df.empty:
        return None

    try:
        ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else df.index[-1]
        ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return max(0.0, time.time() - ts.timestamp())
    except Exception:
        return None


def _is_reasonably_fresh(df, timeframe):
    age = _last_candle_age_seconds(df)
    if age is None:
        return False

    normal_max = _timeframe_max_age_seconds(timeframe)
    if age <= normal_max:
        return True

    # After the NSE session closes there is no new index candle to fetch.
    # Keep the latest completed session usable instead of forcing UNKNOWN/WAIT.
    if not _market_is_open_now():
        return age <= _closed_market_max_age_seconds(timeframe)

    return False

def get_history(symbol="BTCUSD", resolution="5m", limit=200):
    canonical = canonical_symbol(symbol)
    market = get_market(canonical)

    if not market:
        logger.warning("Unsupported market: %s", symbol)
        return _empty()

    provider = market.get("provider")

    if provider == "kotak_neo":
        if canonical in MCX_SYMBOLS:
            logger.info(
                "HISTORY SKIP provider=kotak_neo symbol=%s tf=%s reason=MCX_HISTORY_UNSUPPORTED",
                canonical, resolution,
            )
            return _empty()

        tf = str(resolution).lower()
        # IMPORTANT: no limit in cache key. A 200-row and 220-row caller now
        # share the same 240-row upstream fetch.
        key = ("kotak", canonical, tf)
        now = time.time()
        ttl = _TIMEFRAME_TTL.get(tf, _CACHE_TTL)

        cached = _CACHE.get(key)
        if cached and now - cached[0] < ttl:
            df = cached[1]
            if _is_reasonably_fresh(df, tf):
                logger.info(
                    "HISTORY CACHE HIT provider=kotak_neo symbol=%s tf=%s age=%.1fs rows=%s",
                    canonical, tf, now - cached[0], min(len(df), int(limit)),
                )
                return df.tail(int(limit)).copy()

        lock = _kotak_lock(canonical, tf)
        with lock:
            # Another request may have populated the cache while we waited.
            now = time.time()
            cached = _CACHE.get(key)
            if cached and now - cached[0] < ttl and _is_reasonably_fresh(cached[1], tf):
                logger.info(
                    "HISTORY CACHE HIT AFTER WAIT provider=kotak_neo symbol=%s tf=%s rows=%s",
                    canonical, tf, min(len(cached[1]), int(limit)),
                )
                return cached[1].tail(int(limit)).copy()

            # Fetch one common superset so all consumers reuse it.
            fetch_limit = max(_KOTAK_FETCH_LIMIT, int(limit))
            df = kotak_get_history(canonical, tf, fetch_limit)

            if df is not None and not df.empty and _is_reasonably_fresh(df, tf):
                _CACHE[key] = (time.time(), df.copy())
                age = _last_candle_age_seconds(df)
                freshness_note = "market_closed_snapshot" if age is not None and age > _timeframe_max_age_seconds(tf) else "fresh"
                logger.info(
                    "HISTORY OK provider=kotak_neo symbol=%s tf=%s rows=%s cached_rows=%s freshness=%s age=%.1fs",
                    canonical, tf, min(len(df), int(limit)), len(df), freshness_note, age or 0.0,
                )
                return df.tail(int(limit)).copy()

            if df is not None and not df.empty:
                logger.warning(
                    "HISTORY STALE REJECTED provider=kotak_neo symbol=%s tf=%s last_age=%s",
                    canonical, tf, _last_candle_age_seconds(df),
                )

            # If Kotak is temporarily rate-limited, use the last GOOD cache for
            # a bounded period rather than falling back to arbitrary old chunks.
            cached = _CACHE.get(key)
            if cached and now - cached[0] <= _STALE_FALLBACK_SECONDS and _is_reasonably_fresh(cached[1], tf):
                logger.warning(
                    "HISTORY STALE-CACHE FALLBACK provider=kotak_neo symbol=%s tf=%s cache_age=%.1fs",
                    canonical, tf, now - cached[0],
                )
                return cached[1].tail(int(limit)).copy()

            logger.warning(
                "HISTORY FAILED provider=kotak_neo symbol=%s tf=%s no_safe_cache=1",
                canonical, tf,
            )
            return _empty()

    logger.warning("No Kotak Neo history provider configured for %s (provider=%s)", canonical, provider)
    return _empty()


def get_multi_timeframe_history(symbol, limit=DEFAULT_LIMIT):
    canonical = canonical_symbol(symbol)
    result = {tf: _empty() for tf in RESOLUTIONS}

    # For Indian markets only the four timeframes used by the signal engine
    # are requested. Crypto keeps the original extended set.
    market = get_market(canonical)
    if market and market.get("provider") == "kotak_neo":
        resolutions = ("5m", "15m", "1h", "1d")
    else:
        resolutions = RESOLUTIONS

    # Kotak rate-limits historical requests. Parallel requests for 5m/15m/1h/1d
    # can trigger HTTP 429, especially on Render cold starts. Fetch sequentially
    # and rely on the per-timeframe cache above.
    if market and market.get("provider") == "kotak_neo":
        for tf in resolutions:
            try:
                result[tf] = get_history(canonical, tf, limit)
                time.sleep(0.35)
            except Exception:
                logger.exception(
                    "TIMEFRAME ERROR symbol=%s tf=%s",
                    canonical,
                    tf,
                )
                result[tf] = _empty()
        return result

    with ThreadPoolExecutor(max_workers=len(resolutions)) as pool:
        jobs = {pool.submit(get_history, canonical, tf, limit): tf for tf in resolutions}
        for job in as_completed(jobs):
            tf = jobs[job]
            try:
                result[tf] = job.result()
            except Exception:
                logger.exception("TIMEFRAME ERROR symbol=%s tf=%s", canonical, tf)
                result[tf] = _empty()

    return result
                
