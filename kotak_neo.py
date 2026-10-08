"""
NAKSHATRA AI - Kotak Neo market-data adapter.

Drop-in replacement for kotak_neo.py.

Supports:
- Indian live quotes
- NSE/BSE indices
- NSE/BSE/derivative instrument discovery
- Historical candles using Kotak Neo SDK v3.x
- MCX front-contract discovery for live quotes

No order placement is implemented here.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from config import (
    KOTAK_ACCESS_TOKEN,
    KOTAK_CONSUMER_KEY,
    KOTAK_ENVIRONMENT,
    KOTAK_MOBILE_NUMBER,
    KOTAK_MPIN,
    KOTAK_NEO_FIN_KEY,
    KOTAK_TOTP_SECRET,
    KOTAK_UCC,
)
from logger import logger
from market_registry import canonical_symbol, get_market

try:
    from neo_api_client import NeoAPI
except Exception as exc:
    NeoAPI = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

_CLIENT = None
_CLIENT_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_TTL = 6 * 60 * 60


def _require_sdk():
    if NeoAPI is None:
        raise RuntimeError(
            "Kotak Neo SDK is not installed. Add kotakneoapi to requirements.txt."
        ) from _IMPORT_ERROR


def _make_client():
    _require_sdk()

    kwargs = {
        "consumer_key": KOTAK_CONSUMER_KEY,
        "environment": KOTAK_ENVIRONMENT or "prod",
    }

    if KOTAK_ACCESS_TOKEN:
        kwargs["access_token"] = KOTAK_ACCESS_TOKEN

    if KOTAK_NEO_FIN_KEY:
        kwargs["neo_fin_key"] = KOTAK_NEO_FIN_KEY

    return NeoAPI(**kwargs)


def _client():
    global _CLIENT

    if not KOTAK_CONSUMER_KEY:
        raise RuntimeError(
            "KOTAK_CONSUMER_KEY is missing in Render Environment."
        )

    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = _make_client()
        return _CLIENT


def _maybe_authenticate():
    client = _client()

    if KOTAK_ACCESS_TOKEN:
        return client

    if not (
        KOTAK_TOTP_SECRET
        and KOTAK_MOBILE_NUMBER
        and KOTAK_UCC
        and KOTAK_MPIN
    ):
        return client

    try:
        import pyotp

        totp = pyotp.TOTP(KOTAK_TOTP_SECRET).now()

        client.totp_login(
            mobile_number=KOTAK_MOBILE_NUMBER,
            ucc=KOTAK_UCC,
            totp=totp,
        )
        client.totp_validate(mpin=KOTAK_MPIN)

        logger.info("KOTAK NEO authentication successful")

    except Exception as exc:
        logger.warning(
            "KOTAK NEO authentication unavailable: %s",
            exc,
        )

    return client


# ==========================================================
# GENERIC RESPONSE HELPERS
# ==========================================================

def _walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_objects(child)


def _text(value):
    return str(value or "").strip()


def _first(record: dict, *keys):
    lower = {str(k).lower(): v for k, v in record.items()}

    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]

        value = lower.get(str(key).lower())
        if value not in (None, ""):
            return value

    return None


def _to_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


# ==========================================================
# SCRIPT / INSTRUMENT DISCOVERY
# ==========================================================

def _normalise_record(record: dict) -> dict:
    return {
        "instrument_token": _first(
            record,
            "instrument_token",
            "instrumentToken",
            "token",
            "exchange_token",
            "exchangeToken",
            "scrip_token",
            "scripToken",
            "pSymbol",
            "pScripCode",
        ),
        "exchange_segment": _first(
            record,
            "exchange_segment",
            "exchangeSegment",
            "exchange",
            "pExchSeg",
        ),
        "trading_symbol": _first(
            record,
            "trading_symbol",
            "tradingSymbol",
            "display_symbol",
            "displaySymbol",
            "pTrdSymbol",
            "symbol",
            "name",
        ),
        "expiry": _first(
            record,
            "expiry",
            "expiryDate",
            "pExpiryDate",
            "pExpiry",
        ),
        "instrument_type": _first(
            record,
            "instrument_type",
            "instrumentType",
            "pInstType",
        ),
    }


def _looks_like_symbol(record: dict, candidates: list[str]) -> bool:
    values = [
        _text(
            _first(
                record,
                "trading_symbol",
                "tradingSymbol",
                "display_symbol",
            )
        ),
        _text(_first(record, "symbol", "name")),
    ]

    wanted = [
        re.sub(r"[^A-Z0-9]", "", x.upper())
        for x in candidates
    ]

    for value in values:
        normal = re.sub(r"[^A-Z0-9]", "", value.upper())

        for wanted_symbol in wanted:
            if (
                normal == wanted_symbol
                or normal.startswith(wanted_symbol)
            ):
                return True

    return False


def _extract_search_records(response):
    records = []

    for obj in _walk_objects(response):
        token = _first(
            obj,
            "instrument_token",
            "instrumentToken",
            "exchange_token",
            "exchangeToken",
            "scrip_token",
            "scripToken",
            "pSymbol",
            "pScripCode",
        )

        symbol = _first(
            obj,
            "trading_symbol",
            "tradingSymbol",
            "display_symbol",
            "displaySymbol",
            "pTrdSymbol",
            "symbol",
            "name",
        )

        if token is not None and symbol is not None:
            records.append(_normalise_record(obj))

    return records


def _expiry_key(value):
    text = _text(value)

    if not text:
        return datetime.max.replace(tzinfo=timezone.utc)

    for fmt in (
        "%d-%b-%Y",
        "%d%b%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(
                text.upper(),
                fmt,
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return datetime.max.replace(tzinfo=timezone.utc)


def _choose_record(records, market):
    if not records:
        return None

    segment = market["neo_exchange_segment"]
    candidates = market.get("neo_symbol_candidates", [])

    filtered = [
        r
        for r in records
        if (
            not r.get("exchange_segment")
            or _text(r["exchange_segment"]).lower()
            == segment.lower()
        )
    ] or records

    if segment == "mcx_fo":
        futures = [
            r
            for r in filtered
            if (
                "FUT"
                in _text(r.get("instrument_type")).upper()
                or _text(r.get("trading_symbol")).upper().endswith("FUT")
            )
        ]

        if futures:
            filtered = futures

        filtered.sort(
            key=lambda r: _expiry_key(r.get("expiry"))
        )

    wanted = {
        re.sub(r"[^A-Z0-9]", "", candidate.upper())
        for candidate in candidates
    }

    exact = []

    for r in filtered:
        symbol = re.sub(
            r"[^A-Z0-9]",
            "",
            _text(r.get("trading_symbol")).upper(),
        )

        if symbol in wanted:
            exact.append(r)

    return (exact or filtered)[0]


def _search_scrip_master(client, market):
    segment = market["neo_exchange_segment"]
    candidates = market.get("neo_symbol_candidates", [])

    fn = getattr(client, "scrip_master", None)

    if not callable(fn):
        return None

    try:
        response = fn(exchange_segment=segment)
    except TypeError:
        response = fn()

    urls = []

    if isinstance(response, str):
        urls = [response]
    else:
        for obj in _walk_objects(response):
            for key in ("filePath", "file_path", "url", "path"):
                value = obj.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    urls.append(value)

            for key in ("filesPaths", "filePaths"):
                value = obj.get(key)
                if isinstance(value, list):
                    urls.extend(
                        str(x)
                        for x in value
                        if str(x).startswith("http")
                    )

    urls = list(dict.fromkeys(urls))

    if not urls:
        return None

    for url in urls:
        try:
            df = pd.read_csv(url, low_memory=False)

            if df.empty:
                continue

            records = []

            for _, row in df.iterrows():
                raw = {str(k): row[k] for k in df.columns}
                normal = _normalise_record(raw)

                if normal["instrument_token"] is None:
                    continue

                if _looks_like_symbol(raw, candidates):
                    records.append(normal)

            if records:
                return _choose_record(records, market)

        except Exception as exc:
            logger.warning(
                "KOTAK scrip master read failed: %s",
                exc,
            )

    return None


def _search_scrip(market):
    client = _client()

    segment = market["neo_exchange_segment"]
    candidates = market.get("neo_symbol_candidates", [])

    search = getattr(client, "search_scrip", None)

    if callable(search):
        for candidate in candidates:
            attempts = [
                {
                    "exchange_segment": segment,
                    "symbol": candidate,
                    "expiry": "",
                    "option_type": "FUT" if segment == "mcx_fo" else "",
                    "strike_price": "",
                },
                {
                    "exchange_segment": segment,
                    "symbol": candidate,
                },
            ]

            for kwargs in attempts:
                try:
                    response = search(**kwargs)
                    records = _extract_search_records(response)

                    if records:
                        return _choose_record(records, market)

                except TypeError:
                    continue

                except Exception as exc:
                    logger.debug(
                        "KOTAK search_scrip failed %s: %s",
                        candidate,
                        exc,
                    )

    return _search_scrip_master(client, market)


def resolve_instrument(symbol):
    canonical = canonical_symbol(symbol)

    cached = _TOKEN_CACHE.get(canonical)

    if (
        cached
        and time.time() - cached["time"] < _TOKEN_TTL
    ):
        return cached["record"]

    market = get_market(canonical)

    if (
        not market
        or market.get("provider") != "kotak_neo"
    ):
        return None

    record = _search_scrip(market)

    if (
        record is None
        and market.get("asset_class") == "INDEX"
    ):
        record = {
            "instrument_token": market["data_symbol"],
            "exchange_segment": market["neo_exchange_segment"],
            "trading_symbol": market["data_symbol"],
            "expiry": None,
            "instrument_type": "INDEX",
        }

    if record:
        _TOKEN_CACHE[canonical] = {
            "time": time.time(),
            "record": record,
        }

    return record


# ==========================================================
# LIVE QUOTES
# ==========================================================

def _quote_candidates(record, market):
    token = _text(record.get("instrument_token"))
    segment = (
        record.get("exchange_segment")
        or market["neo_exchange_segment"]
    )

    candidates = []

    # Kotak Neo identifies exchange indices by their display name, not the
    # numeric pSymbol found in the scrip master (e.g. SENSEX has pSymbol=1).
    if market.get("asset_class") == "INDEX":
        candidates.append(
            {
                "instrument_token": market["data_symbol"],
                "exchange_segment": market["neo_exchange_segment"],
            }
        )
    elif token:
        candidates.append(
            {
                "instrument_token": token,
                "exchange_segment": segment,
            }
        )

    output = []
    seen = set()

    for item in candidates:
        key = (item["instrument_token"], item["exchange_segment"])
        if key not in seen:
            seen.add(key)
            output.append(item)

    return output


def _extract_quote(response):
    candidates = []

    for obj in _walk_objects(response):
        price = _first(
            obj,
            "ltp",
            "last_traded_price",
            "lastTradedPrice",
            "lastPrice",
            "close",
        )

        if price is None:
            continue

        ohlc = _first(obj, "ohlc", "OHLC") or {}

        if not isinstance(ohlc, dict):
            ohlc = {}

        def value(*keys):
            direct = _first(obj, *keys)
            if direct is not None:
                return direct
            return _first(ohlc, *keys)

        candidates.append(
            {
                "price": _to_float(price),
                "open": _to_float(value("open")),
                "high": _to_float(value("high")),
                "low": _to_float(value("low")),
                "close": _to_float(value("close")),
                "volume": _to_float(
                    _first(
                        obj,
                        "volume",
                        "last_volume",
                        "volumeTraded",
                    )
                ),
                "change": _to_float(
                    _first(
                        obj,
                        "change",
                        "net_change",
                        "netChange",
                    )
                ),
                "percent_change": _to_float(
                    _first(
                        obj,
                        "per_change",
                        "perChange",
                        "net_change_percentage",
                    )
                ),
                "instrument_token": _first(
                    obj,
                    "instrument_token",
                    "instrumentToken",
                    "exchange_token",
                ),
                "trading_symbol": _first(
                    obj,
                    "trading_symbol",
                    "tradingSymbol",
                    "display_symbol",
                ),
            }
        )

    return next(
        (
            x
            for x in candidates
            if (
                x["price"] is not None
                and x["price"] > 0
            )
        ),
        None,
    )


def get_quote(symbol):
    canonical = canonical_symbol(symbol)
    market = get_market(canonical)

    if (
        not market
        or market.get("provider") != "kotak_neo"
    ):
        return None

    record = resolve_instrument(canonical)

    if not record:
        logger.warning(
            "KOTAK instrument not found for %s",
            canonical,
        )
        return None

    client = _client()

    for token in _quote_candidates(record, market):
        try:
            response = client.quotes(
                instrument_tokens=[token],
                quote_type="all",
            )

            quote = _extract_quote(response)

            if quote:
                quote["symbol"] = canonical
                quote["source"] = "kotak_neo"
                return quote

        except Exception as exc:
            logger.warning(
                "KOTAK quote failed %s: %s",
                canonical,
                exc,
            )

    return None


def get_current_price(symbol):
    quote = get_quote(symbol)

    if not quote:
        return None

    return quote.get("price")


# ==========================================================
# HISTORICAL DATA
# ==========================================================

def _interval_for_resolution(resolution):
    """
    Current Kotak Neo SDK v3.x intervals:
    1min, 3min, 5min, 10min, 15min,
    30min, 60min, D, W
    """
    return {
        "5m": "5min",
        "15m": "15min",
        "1h": "60min",
        "1d": "D",
        "1w": "W",
    }.get(
        str(resolution).lower().strip()
    )


def _max_history_days(resolution):
    # Backend date ranges are inclusive. Keep one day of headroom so a
    # nominal 180-day request cannot become 181 calendar dates.
    return {
        "5m": 29,
        "15m": 59,
        "1h": 89,
        "1d": 179,
        "1w": 179,
    }.get(
        str(resolution).lower().strip(),
        29,
    )


def _call_historical(
    client,
    segment,
    token,
    from_dt,
    to_dt,
    resolution,
):
    """
    Kotak Neo SDK v3.x signature:

        client.historical_data(
            neosymbol,
            interval,
            from_date,
            to_date
        )

    Example:
        neosymbol="nse_cm|1333"
        interval="5min"
    """
    fn = getattr(client, "historical_data", None)

    if not callable(fn):
        raise RuntimeError(
            "Installed Kotak Neo SDK has no historical_data()."
        )

    interval = _interval_for_resolution(resolution)

    if not interval:
        raise RuntimeError(
            f"Unsupported Kotak historical interval: {resolution}"
        )

    token_text = _text(token)

    if not token_text:
        raise RuntimeError(
            "Kotak instrument token is missing."
        )

    neosymbol = f"{segment}|{token_text}"

    return fn(
        neosymbol=neosymbol,
        interval=interval,
        from_date=from_dt.strftime("%Y-%m-%d"),
        to_date=to_dt.strftime("%Y-%m-%d"),
    )


def _extract_candle_rows(response):
    sequences = []

    if isinstance(response, list):
        sequences.append(response)

    for obj in _walk_objects(response):
        for key in (
            "candles",
            "data",
            "result",
            "historicalData",
            "historical_data",
        ):
            value = obj.get(key)

            if isinstance(value, list):
                sequences.append(value)

    for sequence in sequences:
        if not sequence:
            continue

        first = sequence[0]

        if isinstance(first, dict):
            rows = []

            for item in sequence:
                rows.append(
                    {
                        "timestamp": _first(
                            item,
                            "timestamp",
                            "time",
                            "date",
                            "datetime",
                            "candle_time",
                        ),
                        "open": _first(item, "open", "o"),
                        "high": _first(item, "high", "h"),
                        "low": _first(item, "low", "l"),
                        "close": _first(item, "close", "c"),
                        "volume": _first(item, "volume", "v"),
                    }
                )

            return rows

        if (
            isinstance(first, (list, tuple))
            and len(first) >= 5
        ):
            return [
                {
                    "timestamp": row[0],
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5] if len(row) > 5 else 0,
                }
                for row in sequence
                if (
                    isinstance(row, (list, tuple))
                    and len(row) >= 5
                )
            ]

    return []


def _candles_to_df(response):
    rows = _extract_candle_rows(response)

    if not rows:
        return pd.DataFrame(
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

    df = pd.DataFrame(rows)

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    raw_timestamp = df["timestamp"]

    ts = pd.to_datetime(
        raw_timestamp,
        errors="coerce",
        utc=True,
    )

    if ts.isna().all():
        numeric = pd.to_numeric(
            raw_timestamp,
            errors="coerce",
        )

        if numeric.notna().any():
            unit = (
                "ms"
                if numeric.dropna().median()
                > 10_000_000_000
                else "s"
            )

            ts = pd.to_datetime(
                numeric,
                errors="coerce",
                unit=unit,
                utc=True,
            )

    df["timestamp"] = ts

    df.dropna(
        subset=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
        ],
        inplace=True,
    )

    if df.empty:
        return pd.DataFrame(
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

    df.sort_values("timestamp", inplace=True)

    df.drop_duplicates(
        subset=["timestamp"],
        keep="last",
        inplace=True,
    )

    df.set_index("timestamp", inplace=True)

    if "volume" not in df.columns:
        df["volume"] = 0.0

    return df[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    ]


def get_history(
    symbol,
    resolution="5m",
    limit=200,
):
    """Return up to ``limit`` Kotak candles using market-hours-aware fetching.

    The old implementation converted ``limit * candle_interval`` directly to
    calendar days.  That under-fetched Indian-market data because weekends,
    holidays and the NSE/BSE trading session mean that a calendar day contains
    far fewer candles than a 24-hour market.

    We therefore fetch backward in safe calendar chunks, merge/deduplicate the
    results, and stop once enough candles are available.  This is especially
    important for NIFTY/BANKNIFTY 5m/15m/1h data, where the technical engine
    needs a meaningful EMA200 history.
    """
    canonical = canonical_symbol(symbol)
    market = get_market(canonical)

    empty = pd.DataFrame(
        columns=[
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    if (
        not market
        or market.get("provider") != "kotak_neo"
    ):
        return empty

    record = resolve_instrument(canonical)

    if not record:
        logger.warning(
            "KOTAK instrument not found for %s",
            canonical,
        )
        return empty

    client = _maybe_authenticate()

    resolution_key = (
        str(resolution)
        .lower()
        .strip()
    )

    if resolution_key not in {
        "5m",
        "15m",
        "1h",
        "1d",
        "1w",
    }:
        logger.warning(
            "Unsupported Kotak timeframe %s",
            resolution,
        )
        return empty

    max_days = _max_history_days(resolution_key)
    target = max(1, int(limit))

    # Safe request chunks.  These are deliberately smaller than Kotak's
    # documented maximum windows so a single bad boundary/date does not lose
    # the whole history request.
    chunk_days = {
        "5m": 7,
        "15m": 15,
        "1h": 60,
        "1d": 179,
        "1w": 179,
    }[resolution_key]
    chunk_days = min(chunk_days, max_days)

    # Historical data for indices expects the display/index name, e.g.
    # nse_cm|Nifty 50 or bse_cm|SENSEX, rather than a numeric scrip token.
    if market.get("asset_class") == "INDEX":
        token = market.get("data_symbol")
        segment = market["neo_exchange_segment"]
    else:
        token = record.get("instrument_token")
        segment = (
            record.get("exchange_segment")
            or market["neo_exchange_segment"]
        )

    # Fetch from newest -> oldest.  We keep a little overlap between chunks;
    # _candles_to_df + concat/drop_duplicates below makes the overlap harmless.
    now_dt = datetime.now(timezone.utc)
    earliest_dt = now_dt - timedelta(days=max_days)
    cursor_to = now_dt
    frames = []
    calls = 0
    max_calls = max(1, (max_days + chunk_days - 1) // chunk_days)

    while cursor_to > earliest_dt and calls < max_calls:
        cursor_from = max(
            earliest_dt,
            cursor_to - timedelta(days=chunk_days),
        )
        calls += 1

        try:
            response = _call_historical(
                client,
                segment,
                token,
                cursor_from,
                cursor_to,
                resolution_key,
            )
            frame = _candles_to_df(response)

            if not frame.empty:
                frames.append(frame)

                merged_now = pd.concat(frames, axis=0)
                merged_now = merged_now[~merged_now.index.duplicated(keep="last")]

                logger.info(
                    "KOTAK HISTORY CHUNK %s %s rows=%s window=%s..%s",
                    canonical,
                    resolution_key,
                    len(frame),
                    cursor_from.date(),
                    cursor_to.date(),
                )

                if len(merged_now) >= target:
                    break
            else:
                logger.warning(
                    "KOTAK history chunk empty %s %s window=%s..%s",
                    canonical,
                    resolution_key,
                    cursor_from.date(),
                    cursor_to.date(),
                )

        except Exception as exc:
            error_text = str(exc)
            logger.warning(
                "KOTAK history chunk failed %s %s window=%s..%s: %s",
                canonical,
                resolution_key,
                cursor_from.date(),
                cursor_to.date(),
                exc,
            )

            # A 429 means Kotak is actively rate-limiting us. Do not walk
            # backwards through every historical chunk immediately; that only
            # creates another burst of 429s. Leave the cache intact and let the
            # next scheduled refresh retry after the history-layer TTL.
            if "429" in error_text or "rate limit" in error_text.lower() or "too many request" in error_text.lower():
                logger.warning(
                    "KOTAK HISTORY RATE LIMITED %s %s; stopping remaining chunks",
                    canonical,
                    resolution_key,
                )
                break

        # Move backward by one small overlap interval to avoid losing a candle
        # at the boundary.  The final merge removes the duplicate.
        cursor_to = cursor_from - timedelta(seconds=1)

    if not frames:
        logger.warning(
            "KOTAK returned no candles for %s %s",
            canonical,
            resolution_key,
        )
        return empty

    df = pd.concat(frames, axis=0)
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)
    df = df.tail(target)

    logger.info(
        "KOTAK HISTORY OK %s %s rows=%s chunks=%s",
        canonical,
        resolution_key,
        len(df),
        calls,
    )

    return df


def reset_client():
    global _CLIENT

    with _CLIENT_LOCK:
        _CLIENT = None

    _TOKEN_CACHE.clear()


# ==========================================================
# REQUEST THROTTLE / INDEX FUTURE COMPATIBILITY
# ==========================================================
_KOTAK_THROTTLE_LOCK = threading.Lock()
_KOTAK_LAST_REQUEST = 0.0
_KOTAK_MIN_REQUEST_GAP = 0.35


def _kotak_throttle():
    """Serialize lightweight Kotak REST calls to reduce burst/rate-limit risk."""
    global _KOTAK_LAST_REQUEST
    with _KOTAK_THROTTLE_LOCK:
        now = time.time()
        wait = _KOTAK_MIN_REQUEST_GAP - (now - _KOTAK_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _KOTAK_LAST_REQUEST = time.time()


_INDEX_FUTURE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_INDEX_FUTURE_CACHE_TTL = 15.0


def get_index_future_quote(symbol):
    """Return nearest NSE index-future quote; never substitute spot index data."""
    canonical = canonical_symbol(symbol)
    aliases = {
        "NIFTY50": ("NIFTY 50", "NIFTY", "NIFTY50"),
        "BANKNIFTY": ("NIFTY BANK", "BANKNIFTY", "NIFTYBANK"),
        "NIFTYIT": ("NIFTY IT", "NIFTYIT", "CNXIT"),
    }
    candidates = aliases.get(canonical)
    if not candidates:
        return {"status": "NOT_REQUIRED", "symbol": canonical}

    cached = _INDEX_FUTURE_CACHE.get(canonical)
    if cached and time.time() - cached[0] < _INDEX_FUTURE_CACHE_TTL:
        return dict(cached[1])

    try:
        client = _client()
        search = getattr(client, "search_scrip", None)
        if not callable(search):
            return {"status": "NO_DATA", "symbol": canonical, "reason": "Kotak search_scrip unavailable"}

        records = []
        for candidate in candidates:
            _kotak_throttle()
            attempts = [
                {"exchange_segment": "nse_fo", "symbol": candidate, "expiry": "", "option_type": "FUT", "strike_price": ""},
                {"exchange_segment": "nse_fo", "symbol": candidate},
            ]
            for kwargs in attempts:
                try:
                    response = search(**kwargs)
                    records.extend(_extract_search_records(response))
                    if records:
                        break
                except TypeError:
                    continue
                except Exception:
                    continue
            if records:
                break

        if not records:
            result = {"status": "NO_DATA", "symbol": canonical, "reason": "No NSE index future mapping found"}
            _INDEX_FUTURE_CACHE[canonical] = (time.time(), result)
            return dict(result)

        # Keep NSE futures only and prefer FUT instruments with a valid expiry.
        futures = [r for r in records if "FUT" in _text(r.get("instrument_type")).upper()
                   or "FUT" in _text(r.get("trading_symbol")).upper()]
        records = futures or records
        records.sort(key=lambda r: _expiry_key(r.get("expiry")))
        record = records[0]

        token = record.get("instrument_token")
        if token is None:
            result = {"status": "NO_DATA", "symbol": canonical, "reason": "Future instrument token missing"}
            _INDEX_FUTURE_CACHE[canonical] = (time.time(), result)
            return dict(result)

        _kotak_throttle()
        response = client.quotes(
            instrument_tokens=[{"instrument_token": str(token), "exchange_segment": "nse_fo"}],
            quote_type="all",
        )
        quote = _extract_quote(response) or {}
        if not quote:
            result = {"status": "NO_DATA", "symbol": canonical, "reason": "No future quote returned"}
        else:
            result = {
                "status": "OK",
                "symbol": canonical,
                "source": "kotak_neo",
                "exchange_segment": "nse_fo",
                "instrument_token": str(token),
                "trading_symbol": record.get("trading_symbol"),
                "expiry": record.get("expiry"),
                "instrument_type": record.get("instrument_type"),
                **quote,
            }
        _INDEX_FUTURE_CACHE[canonical] = (time.time(), result)
        return dict(result)
    except Exception as exc:
        logger.warning("KOTAK index future quote failed %s: %s", canonical, exc)
        result = {"status": "ERROR", "symbol": canonical, "source": "kotak_neo", "reason": str(exc)}
        _INDEX_FUTURE_CACHE[canonical] = (time.time(), result)
        return dict(result)
