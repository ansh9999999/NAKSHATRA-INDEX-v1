"""NAKSHATRA INDEX v1 - only Indian index markets."""
MARKETS = {
    "NIFTY50": {
        "name": "NIFTY 50", "display": "NIFTY 50", "asset_class": "INDEX",
        "exchange": "NSE", "provider": "kotak_neo", "data_symbol": "Nifty 50",
        "neo_exchange_segment": "nse_cm", "neo_symbol_candidates": ["Nifty 50", "NIFTY", "NIFTY50"],
        "option_chain": True,
    },
    "BANKNIFTY": {
        "name": "BANKNIFTY", "display": "BANKNIFTY", "asset_class": "INDEX",
        "exchange": "NSE", "provider": "kotak_neo", "data_symbol": "Nifty Bank",
        "neo_exchange_segment": "nse_cm", "neo_symbol_candidates": ["Nifty Bank", "BANKNIFTY", "NIFTYBANK"],
        "option_chain": True,
    },
    "NIFTYIT": {
        "name": "NIFTY IT", "display": "NIFTY IT", "asset_class": "INDEX",
        "exchange": "NSE", "provider": "kotak_neo", "data_symbol": "Nifty IT",
        "neo_exchange_segment": "nse_cm", "neo_symbol_candidates": ["Nifty IT", "NIFTY IT", "NIFTYIT", "CNXIT"],
        "option_chain": True,
    },
    "SENSEX": {
        "name": "SENSEX", "display": "SENSEX", "asset_class": "INDEX",
        "exchange": "BSE", "provider": "kotak_neo", "data_symbol": "SENSEX",
        "neo_exchange_segment": "bse_cm", "neo_symbol_candidates": ["SENSEX"],
        "option_chain": True,
    },
}
ALIASES = {
    "NIFTY":"NIFTY50", "NIFTY50":"NIFTY50", "NIFTY 50":"NIFTY50",
    "BANK NIFTY":"BANKNIFTY", "NIFTY BANK":"BANKNIFTY", "NIFTY_BANK":"BANKNIFTY", "BANKNIFTY":"BANKNIFTY",
    "NIFTY IT":"NIFTYIT", "NIFTY_IT":"NIFTYIT", "NIFTYIT":"NIFTYIT", "CNXIT":"NIFTYIT",
    "SENSEX":"SENSEX",
}
def canonical_symbol(value, default="NIFTY50"):
    s=str(value or "").strip().upper()
    if s in ("", "UNDEFINED", "NULL", "NONE", "NAN"): return default
    return ALIASES.get(s, s)
def get_market(value, default=None): return MARKETS.get(canonical_symbol(value), default)
def is_supported(value): return canonical_symbol(value, "") in MARKETS
def symbols(): return list(MARKETS)
