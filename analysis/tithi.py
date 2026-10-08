"""
NAKSHATRA AI
Tithi Engine v5.1
"""

from datetime import datetime


TITHIS = [
    "Pratipada",
    "Dwitiya",
    "Tritiya",
    "Chaturthi",
    "Panchami",
    "Shashthi",
    "Saptami",
    "Ashtami",
    "Navami",
    "Dashami",
    "Ekadashi",
    "Dwadashi",
    "Trayodashi",
    "Chaturdashi",
    "Purnima",
    "Pratipada Krishna",
    "Dwitiya Krishna",
    "Tritiya Krishna",
    "Chaturthi Krishna",
    "Panchami Krishna",
    "Shashthi Krishna",
    "Saptami Krishna",
    "Ashtami Krishna",
    "Navami Krishna",
    "Dashami Krishna",
    "Ekadashi Krishna",
    "Dwadashi Krishna",
    "Trayodashi Krishna",
    "Chaturdashi Krishna",
    "Amavasya"
]

BULLISH = [
    "Panchami",
    "Saptami",
    "Dashami",
    "Ekadashi",
    "Dwadashi"
]


def get_tithi(timestamp):

    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    index = (timestamp.day - 1) % 30
    tithi = TITHIS[index]

    bullish = tithi in BULLISH

    if bullish:
        score = 80
        reason = f"{tithi} is considered supportive."
    else:
        score = 40
        reason = f"{tithi} is neutral/bearish."

    return {
        "tithi": tithi,
        "bullish": bullish,
        "score": score,
        "reason": reason,
        "reasons": [reason]
    }
