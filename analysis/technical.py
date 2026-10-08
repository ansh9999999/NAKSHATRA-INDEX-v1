import math
import pandas as pd

def num(v, default=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def _tf(df):
    if df is None or df.empty or len(df)<20: return {"trend":"NO DATA","score":0,"rsi":None,"ema9":None,"ema20":None}
    c=df["close"].astype(float); e9=c.ewm(span=9,adjust=False).mean(); e20=c.ewm(span=20,adjust=False).mean()
    d=c.diff(); gain=d.clip(lower=0).rolling(14).mean(); loss=(-d.clip(upper=0)).rolling(14).mean(); rs=gain/loss.replace(0,pd.NA); rsi=(100-(100/(1+rs))).fillna(50)
    last=float(c.iloc[-1]); a=float(e9.iloc[-1]); b=float(e20.iloc[-1]); r=float(rsi.iloc[-1])
    score=0
    if a>b: score+=35
    else: score-=35
    if r>=60: score+=25
    elif r<=40: score-=25
    if len(c)>=2 and float(c.iloc[-1])>float(c.iloc[-2]): score+=10
    else: score-=10
    trend="BULLISH" if score>=25 else "BEARISH" if score<=-25 else "SIDEWAYS"
    return {"trend":trend,"score":score,"price":last,"ema9":round(a,2),"ema20":round(b,2),"rsi":round(r,2)}

def analyze(data):
    out={}; scores=[]
    for tf in ("5m","15m","1h","1d"):
        x=_tf(data.get(tf)); out[tf]=x; scores.append(x.get("score",0))
    avg=sum(scores)/len(scores) if scores else 0
    direction="BUY" if avg>=20 else "SELL" if avg<=-20 else "WAIT"
    return {"status":"OK" if any(x.get("price") for x in out.values()) else "NO DATA","direction":direction,"score":round(avg,1),"timeframes":out}
