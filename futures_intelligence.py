from __future__ import annotations
import threading, time
from kotak_neo import get_index_future_quote

_LOCK=threading.Lock(); _CACHE={}; _PREV={}; TTL=30

def _n(v):
    try:
        x=float(v); return x if x==x else None
    except Exception:return None

def get_futures_intelligence(symbol, spot=None):
    now=time.time()
    with _LOCK:
        c=_CACHE.get(symbol)
        if c and now-c[0] < TTL:return c[1]
    q=get_index_future_quote(symbol)
    if not q or q.get("status") not in ("OK",):
        out={"status":q.get("status","NO DATA") if isinstance(q,dict) else "NO DATA","symbol":symbol,"reason":(q or {}).get("reason","Near-month futures live quote unavailable; no spot value substituted.")}
    else:
        price=_n(q.get("price")); oi=_n(q.get("oi")); vol=_n(q.get("volume")); sp=_n(spot)
        with _LOCK: prev=_PREV.get(symbol)
        oi_delta=(oi-prev.get("oi")) if (prev and oi is not None and prev.get("oi") is not None) else None
        px_delta=(price-prev.get("price")) if (prev and price is not None and prev.get("price") is not None) else None
        buildup="WARMING UP"
        if oi_delta is not None and px_delta is not None:
            if px_delta>0 and oi_delta>0:buildup="LONG BUILDUP"
            elif px_delta<0 and oi_delta>0:buildup="SHORT BUILDUP"
            elif px_delta>0 and oi_delta<0:buildup="SHORT COVERING"
            elif px_delta<0 and oi_delta<0:buildup="LONG UNWINDING"
            else:buildup="NEUTRAL"
        basis=(price-sp) if price is not None and sp is not None else None
        out={"status":"OK","symbol":symbol,"contract":q.get("contract"),"expiry":q.get("expiry"),"price":price,"oi":oi,"volume":vol,"snapshot_oi_change":oi_delta,"snapshot_price_change":px_delta,"basis":basis,"buildup":buildup,"source":"Kotak Neo near-month futures quote","note":"ΔOI is change between dashboard snapshots, not exchange EOD OI change."}
        with _LOCK:_PREV[symbol]={"oi":oi,"price":price,"time":now}
    with _LOCK:_CACHE[symbol]=(now,out)
    return out

def combine_futures_options(fut,opt):
    fb=str((fut or {}).get("buildup") or "").upper(); ob=str((opt or {}).get("signal") or "").upper()
    fdir="BULLISH" if fb in ("LONG BUILDUP","SHORT COVERING") else "BEARISH" if fb in ("SHORT BUILDUP","LONG UNWINDING") else "NEUTRAL"
    odir="BULLISH" if ob in ("BULLISH","BUY") else "BEARISH" if ob in ("BEARISH","SELL") else "NEUTRAL"
    if fdir==odir and fdir!="NEUTRAL": view=f"{fdir} CONFIRMED"; action="CE BUY WATCH" if fdir=="BULLISH" else "PE BUY WATCH"
    elif fdir!="NEUTRAL" and odir!="NEUTRAL": view="CONFLICT"; action="WAIT"
    else:view="WAIT FOR CONFIRMATION"; action="WAIT"
    return {"status":"OK" if (fut or {}).get("status")=="OK" and (opt or {}).get("status")=="OK" else "PARTIAL","futures_bias":fdir,"options_bias":odir,"view":view,"action":action}
    
