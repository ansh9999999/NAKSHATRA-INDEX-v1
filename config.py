"""
NAKSHATRA AI - Configuration
Kotak Neo integration keeps Indian markets separate from Delta crypto.
"""

import os

PROJECT_NAME = "NAKSHATRA AI"
VERSION = "5.2"

BROKER_TYPE = "paper"

# Delta Exchange - BTC/ETH only
DELTA_BASE_URL = "https://api.india.delta.exchange"
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")

# Kotak Neo - Indian market data
# The adapter accepts the KOTAK_* names used by NAKSHATRA and a few
# official NEO_* aliases for compatibility.
KOTAK_CONSUMER_KEY = (
    os.getenv("KOTAK_CONSUMER_KEY")
    or os.getenv("KOTAK_API_KEY")
    or os.getenv("NEO_CONSUMER_KEY")
    or ""
)

KOTAK_ACCESS_TOKEN = (
    os.getenv("KOTAK_ACCESS_TOKEN")
    or os.getenv("NEO_ACCESS_TOKEN")
    or ""
)

KOTAK_MOBILE_NUMBER = (
    os.getenv("KOTAK_MOBILE_NUMBER")
    or os.getenv("KOTAK_MOBILE")
    or os.getenv("NEO_MOBILE_NUMBER")
    or ""
)

KOTAK_UCC = (
    os.getenv("KOTAK_UCC")
    or os.getenv("NEO_UCC")
    or ""
)

KOTAK_MPIN = (
    os.getenv("KOTAK_MPIN")
    or os.getenv("NEO_MPIN")
    or ""
)

# Optional. Only needed if unattended TOTP login is configured.
# Never expose this value in logs or source control.
KOTAK_TOTP_SECRET = (
    os.getenv("KOTAK_TOTP_SECRET")
    or os.getenv("NEO_TOTP_SECRET")
    or ""
)

KOTAK_ENVIRONMENT = os.getenv("KOTAK_ENVIRONMENT", "prod")
KOTAK_NEO_FIN_KEY = os.getenv("KOTAK_NEO_FIN_KEY", "neotradeapi")

# Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nakshatra-ai")

# Database / scanner
DATABASE_NAME = "trades.db"
SCAN_INTERVAL = 5
MONITOR_INTERVAL = 1
MAX_HOLD_CANDLES = 20

# Risk
STARTING_CAPITAL = 100000
RISK_PER_TRADE = 2
MAX_OPEN_TRADES = 5
ATR_MULTIPLIER = 2
MIN_RISK_REWARD = 2

# Backtest
BACKTEST_LIMIT = 1000

# Scanner markets. BTC/ETH and Indian markets remain provider-separated.
SYMBOLS = [
    "BTCUSD",
    "ETHUSD",
    "NIFTY50",
    "BANKNIFTY",
    "SENSEX",
    "NIFTYIT",
    "GOLD",
    "SILVER",
    "CRUDEOIL",
]
