"""
NAKSHATRA AI
Astrology Engine v5.1
"""

from analysis.moon_phase import get_moon_phase
from analysis.nakshatra import get_nakshatra
from analysis.tithi import get_tithi
from analysis.rahu import get_rahu_kaal


def analyze_astrology(timestamp):

    moon = get_moon_phase(timestamp)
    nakshatra = get_nakshatra(timestamp)
    tithi = get_tithi(timestamp)
    rahu = get_rahu_kaal(timestamp)

    score = 0
    reasons = []

    # Moon
    if moon.get("bullish", False):
        score += 25
    reasons.append(moon.get("reason", ""))

    # Nakshatra
    if nakshatra.get("bullish", False):
        score += 25
    reasons.append(nakshatra.get("reason", ""))

    # Tithi
    if tithi.get("bullish", False):
        score += 25
    reasons.append(tithi.get("reason", ""))

    # Rahu
    if not rahu.get("active", False):
        score += 25
        reasons.append("Outside Rahu Kaal")
    else:
        reasons.append("Rahu Kaal Active")

    reasons = [r for r in reasons if r]

    if score >= 70:
        bias = "BULLISH"
    elif score <= 30:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "score": score,
        "moon": moon,
        "nakshatra": nakshatra,
        "tithi": tithi,
        "rahu": rahu,
        "reasons": reasons
    }
