from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
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

EXECUTOR=ThreadPoolExecutor(max_workers=2)
LOCK=threading.Lock()
QUOTE_CACHE={}; ANALYSIS_CACHE={}; JOBS=set(); MAX_CACHE=8
QUOTE_TTL=8; ANALYSIS_TTL=45

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

def build_analysis(symbol):
    s=canonical_symbol(symbol)
    try:
        data=get_multi_timeframe_history(s,limit=220)
        tech=technical_analyze(data)
        q=quote(s).get("price")
        spot=float(q) if q else next((x.get("price") for x in tech["timeframes"].values() if x.get("price")),0)
        oc=option_analyze(s,spot)
        fut=get_futures_intelligence(s,spot)
        ast=analyze_astrology(datetime.now())
        num=analyze_numerology(datetime.now(),s)
        dirs=[tech.get("direction"), oc.get("signal")]
        if fut.get("buildup") in ("LONG BUILDUP","SHORT COVERING"): dirs.append("BUY")
        elif fut.get("buildup") in ("SHORT BUILDUP","LONG UNWINDING"): dirs.append("SELL")
        bullish=sum(1 for d in dirs if str(d).upper() in ("BUY","BULLISH")); bearish=sum(1 for d in dirs if str(d).upper() in ("SELL","BEARISH"))
        if bullish>bearish and bullish>=2: decision="BUY"
        elif bearish>bullish and bearish>=2: decision="SELL"
        else: decision="WAIT"
        sentiment="BULLISH" if bullish>bearish else "BEARISH" if bearish>bullish else "NEUTRAL"
        return safe({"status":"OK","symbol":s,"technical":tech,"futures":fut,"options":oc,"futures_options":combine_futures_options(fut,oc),"astrology":ast,"numerology":num,"sentiment":{"status":"OK","bias":sentiment,"technical":tech.get("direction"),"options":oc.get("signal"),"futures":fut.get("buildup")},"decision":{"action":decision,"strength":min(100,50+abs(bullish-bearish)*15),"agreement":"CONFIRMED" if (bullish>=2 or bearish>=2) else "NO AGREEMENT"}})
    except Exception as e:
        logger.exception("INDEX ANALYSIS ERROR %s",s)
        return {"status":"ERROR","symbol":s,"message":str(e)}

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

app=FastAPI(title="NAKSHATRA INDEX v1",version="1.0",lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")

@app.get("/",response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"request": request})
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
