"""
NAKSHATRA AI
Nakshatra Engine v5.1
"""

from datetime import datetime

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini",
    "Mrigashira", "Ardra", "Punarvasu", "Pushya",
    "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha",
    "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

BULLISH = [
    "Rohini",
    "Pushya",
    "Hasta",
    "Anuradha",
    "Shravana",
    "Revati"
]


def get_nakshatra(timestamp):

    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    index = (timestamp.day - 1) % 27
    nakshatra = NAKSHATRAS[index]

    bullish = nakshatra in BULLISH

    if bullish:
        score = 80
        reason = f"{nakshatra} supports bullish trading."
    else:
        score = 40
        reason = f"{nakshatra} is neutral/bearish."

    return {
        "nakshatra": nakshatra,
        "bullish": bullish,
        "score": score,
        "reason": reason,
        "reasons": [reason]
    }
