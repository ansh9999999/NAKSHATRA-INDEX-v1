from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
import math, threading, time
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from logger import logger
from market_registry import canonical_symbol, get_market, symbols
from kotak_neo import get_quote, get_index_future_quote
from history import get_multi_timeframe_history
from futures_intelligence import get_futures_intelligence, combine_futures_options
from analysis.technical import analyze as technical_analyze
from analysis.astrology_engine import analyze_astrology
from analysis.numerology_engine import analyze_numerology
from option_chain import analyze as option_analyze

# Render Free has only 512 MB RAM. Keep background concurrency deliberately low.
# Analysis jobs are single-flight per symbol; one worker prevents several pandas/Kotak
# analysis pipelines from running in parallel and exhausting memory.
EXECUTOR=ThreadPoolExecutor(max_workers=1)
HISTORY_EXECUTOR=ThreadPoolExecutor(max_workers=1)
AUX_EXECUTOR=ThreadPoolExecutor(max_workers=1)
LOCK=threading.Lock()
QUOTE_CACHE={}; ANALYSIS_CACHE={}; JOBS=set(); MAX_CACHE=4
QUOTE_TTL=15; ANALYSIS_TTL=90
_STAGE_LOCK=threading.Lock(); _STAGE_FUTURES={}

def safe(v):
    if v is None or isinstance(v,(str,bool,int)): return v
    if isinstance(v,float): return v if math.isfinite(v) else None
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if hasattr(v,"item"):
        try:return safe(v.item())
        except:pass
    return str(v)

def bounded_put(cache,key,value):
    cache[key]=value
    while len(cache)>MAX_CACHE:
        oldest=min(cache,key=lambda k:cache[k][0]); cache.pop(oldest,None)

def quote(symbol, force=False):
    s=canonical_symbol(symbol); now=time.time()
    with LOCK:
        c=QUOTE_CACHE.get(s)
        if c and not force and now-c[0]<QUOTE_TTL:return c[1]
    q=get_quote(s)
    if not q:return {"status":"NO DATA","symbol":s,"message":"Kotak Neo quote unavailable."}
    out={"status":"OK","symbol":s,"name":get_market(s)["name"],**q,"server_time":time.time()}
    with LOCK: bounded_put(QUOTE_CACHE,s,(time.time(),out))
    return out

def _empty_history():
    return {tf: None for tf in ("5m", "15m", "1h", "1d")}


def _limited_result(pool, fn, args, timeout, label, fallback):
    """Run a slow provider call without letting it hold the full dashboard analysis."""
    # Never enqueue repeated timed-out work behind a stuck provider request.
    with _STAGE_LOCK:
        old = _STAGE_FUTURES.get(label)
        if old is not None and not old.done():
            logger.warning("ANALYSIS STAGE SKIP stage=%s reason=previous_call_still_running", label)
            return fallback
        future = pool.submit(fn, *args)
        _STAGE_FUTURES[label] = future
    try:
        result = future.result(timeout=timeout)
        return result
    except FuturesTimeoutError:
        logger.warning("ANALYSIS STAGE TIMEOUT stage=%s timeout=%ss", label, timeout)
    except Exception:
        logger.exception("ANALYSIS STAGE FAILED stage=%s", label)
    finally:
        with _STAGE_LOCK:
            if _STAGE_FUTURES.get(label) is future and future.done():
                _STAGE_FUTURES.pop(label, None)
    return fallback


def build_analysis(symbol):
    s=canonical_symbol(symbol)
    now=datetime.now()
    errors=[]

    # Historical calls are sequential/rate-limited. Bound their wait so one
    # delayed Kotak response cannot keep every dashboard card on Loading forever.
    data=_limited_result(
        HISTORY_EXECUTOR, get_multi_timeframe_history, (s, 220), 18,
        "history", _empty_history(),
    )
    if not isinstance(data, dict):
        data=_empty_history()
        errors.append("history unavailable")

    try:
        tech=technical_analyze(data)
    except Exception as exc:
        logger.exception("ANALYSIS STAGE FAILED stage=technical symbol=%s", s)
        tech={"status":"ERROR","direction":"WAIT","score":0,"timeframes":{}}
        errors.append("technical unavailable")

    qdata=_limited_result(AUX_EXECUTOR, quote, (s,), 4, "quote", {}) or {}
    q=qdata.get("price") if isinstance(qdata,dict) else None
    spot=float(q) if q else next((x.get("price") for x in (tech.get("timeframes") or {}).values() if x.get("price")),0)

    # Option-chain and futures calls run independently. A slow/unsupported
    # provider call becomes PARTIAL data instead of blocking astrology and AI.
    oc=_limited_result(AUX_EXECUTOR, option_analyze, (s,spot), 5, "option_chain",
        {"status":"NO DATA","symbol":s,"rows":[],"row_count":0,"reason":"Option-chain request timed out."})
    fut=_limited_result(AUX_EXECUTOR, get_futures_intelligence, (s,spot), 5, "futures",
        {"status":"NO DATA","symbol":s,"reason":"Futures quote request timed out."})

    try: ast=analyze_astrology(now)
    except Exception:
        logger.exception("ANALYSIS STAGE FAILED stage=astrology symbol=%s",s)
        ast={"status":"ERROR","bias":"UNAVAILABLE"}; errors.append("astrology unavailable")
    try: num=analyze_numerology(now,s)
    except Exception:
        logger.exception("ANALYSIS STAGE FAILED stage=numerology symbol=%s",s)
        num={"status":"ERROR","bias":"UNAVAILABLE"}; errors.append("numerology unavailable")

    # Weighted agreement, following the v3.5 model: Technical 50%, Options 20%,
    # Astrology 15%, Numerology 15%. Missing inputs are excluded and weights renormalized.
    components=[]
    tscore=tech.get("score")
    if isinstance(tscore,(int,float)) and tech.get("status")=="OK": components.append((0.50,max(-100,min(100,float(tscore)))))
    osig=str(oc.get("signal") or "").upper()
    if oc.get("status")=="OK": components.append((0.20,100 if osig in ("BULLISH","BUY") else -100 if osig in ("BEARISH","SELL") else 0))
    abias=str(ast.get("bias") or "").upper()
    if abias in ("BULLISH","BEARISH","NEUTRAL"):
        av=float(ast.get("score",50)); components.append((0.15,max(-100,min(100,(av-50)*2))))
    nbias=str(num.get("bias") or "").upper()
    if nbias in ("BUY","SELL","NEUTRAL"):
        nv=float(num.get("score",50)); components.append((0.15,max(-100,min(100,(nv-50)*2))))
    total_weight=sum(w for w,_ in components)
    combined_score=(sum(w*v for w,v in components)/total_weight) if total_weight else 0
    decision="BUY" if combined_score>=20 else "SELL" if combined_score<=-20 else "WAIT"
    strength=round(min(95,abs(combined_score))) if components else 0
    sentiment="BULLISH" if combined_score>=15 else "BEARISH" if combined_score<=-15 else "NEUTRAL"
    partial=bool(errors) or tech.get("status")!="OK" or oc.get("status")!="OK" or fut.get("status")!="OK"
    tf5=(tech.get("timeframes") or {}).get("5m",{})
    entry=float(q) if q else float(tf5.get("price") or 0)
    atr=float(tf5.get("atr") or 0)
    trade_plan={"status":"WAIT","action":"WAIT","reason":"Signals do not have enough agreement for a trade."}
    if decision in ("BUY","SELL") and entry>0 and atr>0:
        risk=atr*1.5; reward1=atr*2.0; reward2=atr*3.0; reward3=atr*4.0
        trade_plan={"status":"READY","action":decision,"entry":round(entry,2),
            "stop_loss":round(entry-risk if decision=="BUY" else entry+risk,2),
            "target1":round(entry+reward1 if decision=="BUY" else entry-reward1,2),
            "target2":round(entry+reward2 if decision=="BUY" else entry-reward2,2),
            "target3":round(entry+reward3 if decision=="BUY" else entry-reward3,2),
            "risk_reward":round(reward1/risk,2) if risk else None,"atr":round(atr,2),
            "invalidation":"Price crosses stop-loss; reassess before any re-entry.",
            "reason":"ATR-based illustrative levels; confirm liquidity and position size before trading."}
    why=[]
    if tech.get("direction"): why.append("Technical: "+str(tech.get("direction")))
    if oc.get("signal"): why.append("Options: "+str(oc.get("signal")))
    if abias: why.append("Astrology: "+abias+" (context only)")
    if nbias: why.append("Numerology: "+nbias+" (context only)")
    if fut.get("buildup"): why.append("Futures: "+str(fut.get("buildup")))
    result={"status":"PARTIAL" if partial else "OK","symbol":s,"technical":tech,"futures":fut,"options":oc,
        "futures_options":combine_futures_options(fut,oc),"astrology":ast,"numerology":num,"trade_plan":trade_plan,
        "sentiment":{"status":"OK","bias":sentiment,"technical":tech.get("direction"),"options":oc.get("signal"),"futures":fut.get("buildup")},
        "decision":{"action":decision,"strength":strength,"score":round(combined_score,1),"agreement":"CONFIRMED" if len(components)>=2 and abs(combined_score)>=20 else "NO AGREEMENT","reasons":why},
        "message":"Partial data: " + ", ".join(errors) if errors else None,"updated_at":time.time()}
    return safe(result)

def ensure_analysis(symbol, force=False):
    s=canonical_symbol(symbol); now=time.time()
    with LOCK:
        c=ANALYSIS_CACHE.get(s)
        if c and not force and now-c[0]<ANALYSIS_TTL:return c[1]
        if s in JOBS:return {"status":"LOADING","symbol":s}
        JOBS.add(s)
    EXECUTOR.submit(_analysis_job,s)
    return {"status":"LOADING","symbol":s}

def _analysis_job(s):
    try:
        out=build_analysis(s)
        with LOCK: bounded_put(ANALYSIS_CACHE,s,(time.time(),out))
    finally:
        with LOCK:JOBS.discard(s)

@asynccontextmanager
async def lifespan(app):
    logger.info("NAKSHATRA INDEX v1 started — scheduler/scanner disabled")
    yield
    EXECUTOR.shutdown(wait=False,cancel_futures=True)
    HISTORY_EXECUTOR.shutdown(wait=False,cancel_futures=True)
    AUX_EXECUTOR.shutdown(wait=False,cancel_futures=True)

app=FastAPI(title="NAKSHATRA INDEX v1",version="1.0",lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")

@app.get("/",response_class=HTMLResponse)
def home(request:Request):return templates.TemplateResponse(request=request, name="dashboard.html", context={"request":request})
@app.get("/health")
def health():return {"status":"OK","service":"nakshatra-index","markets":symbols(),"scheduler":"disabled"}
@app.get("/api/quote")
def api_quote(symbol:str="NIFTY50",force:bool=False):return quote(symbol,force)
@app.get("/api/analysis")
def api_analysis(symbol:str="NIFTY50",force:bool=False):
    s=canonical_symbol(symbol); now=time.time()
    with LOCK:
        c=ANALYSIS_CACHE.get(s)
        if c and not force and now-c[0]<ANALYSIS_TTL:return c[1]
    return ensure_analysis(s,force)
@app.get("/api/futures")
def api_futures(symbol:str="NIFTY50"):
    s=canonical_symbol(symbol); q=quote(s); return safe(get_futures_intelligence(s,q.get("price")))
@app.get("/api/options")
def api_options(symbol:str="NIFTY50"):
    s=canonical_symbol(symbol); q=quote(s); return safe(option_analyze(s,q.get("price")))
@app.get("/api/snapshot")
def api_snapshot(symbol:str="NIFTY50"):
    s=canonical_symbol(symbol); q=quote(s); a=ensure_analysis(s)
    return safe({"status":"OK","symbol":s,"quote":q,"analysis":a})
@app.get("/api/scanner")
def api_scanner():
    rows=[]
    for s in symbols():
        q=quote(s)
        rows.append({"symbol":s,"name":get_market(s)["name"],"price":q.get("price"),"change":q.get("change"),"percent_change":q.get("percent_change"),"status":q.get("status")})
    return {"status":"OK","rows":rows,"server_time":time.time()}
