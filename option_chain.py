from datetime import datetime
import threading, time
from kotak_neo_adaptor import get_option_chain as neo_get_option_chain
from market_registry import canonical_symbol

_CACHE={}; LOCK=threading.Lock(); TTL=30

def _num(v):
    try:return float(str(v).replace(",",""))
    except:return 0.0

def analyze(symbol, spot=None):
    symbol=canonical_symbol(symbol); now=time.time(); key=symbol
    with LOCK:
        x=_CACHE.get(key)
        if x and now-x[0]<TTL:return x[1]
    if symbol not in ("NIFTY50","BANKNIFTY","NIFTYIT","SENSEX"):
        return {"status":"NOT_REQUIRED","rows":[]}
    try: rows=neo_get_option_chain(symbol)
    except Exception as e: rows=[]
    if not rows:
        out={"status":"NO DATA","symbol":symbol,"rows":[],"row_count":0,"reason":"Kotak Neo option-chain returned no rows."}
    else:
        calls=[r for r in rows if r.get("type")=="CALL"]; puts=[r for r in rows if r.get("type")=="PUT"]
        coi=sum(_num(r.get("oi")) for r in calls); poi=sum(_num(r.get("oi")) for r in puts)
        cvol=sum(_num(r.get("volume")) for r in calls); pvol=sum(_num(r.get("volume")) for r in puts)
        pcr=poi/coi if coi else None
        signal="BULLISH" if pcr and pcr>=1.10 else "BEARISH" if pcr and pcr<=0.90 else "SIDEWAYS"
        topc=sorted(calls,key=lambda r:_num(r.get("oi")),reverse=True)[:5]; topp=sorted(puts,key=lambda r:_num(r.get("oi")),reverse=True)[:5]
        out={"status":"OK","symbol":symbol,"expiry":rows[0].get("expiry"),"rows":rows,"row_count":len(rows),"call_oi":coi,"put_oi":poi,"call_volume":cvol,"put_volume":pvol,"pcr":round(pcr,3) if pcr else None,"signal":signal,"top_call_oi":topc,"top_put_oi":topp}
    with LOCK:_CACHE[key]=(now,out)
    return out
