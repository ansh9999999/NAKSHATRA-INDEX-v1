"""
NAKSHATRA AI
Moon Phase Engine v5.1
"""

from datetime import datetime


def get_moon_phase(timestamp):

    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    day = timestamp.day

    # Approximate Moon Cycle
    if 1 <= day <= 3:
        phase = "New Moon"
        bullish = False
        score = 20
        reason = "Weak market energy near New Moon"

    elif 4 <= day <= 7:
        phase = "Waxing Crescent"
        bullish = True
        score = 70
        reason = "Bullish momentum building"

    elif 8 <= day <= 10:
        phase = "First Quarter"
        bullish = True
        score = 80
        reason = "Strong directional movement"

    elif 11 <= day <= 15:
        phase = "Full Moon"
        bullish = False
        score = 40
        reason = "High volatility around Full Moon"

    elif 16 <= day <= 20:
        phase = "Waning Gibbous"
        bullish = False
        score = 45
        reason = "Profit booking possible"

    elif 21 <= day <= 24:
        phase = "Last Quarter"
        bullish = False
        score = 35
        reason = "Trend weakening"

    else:
        phase = "Waning Crescent"
        bullish = False
        score = 25
        reason = "Low momentum before New Moon"

    return {
        "phase": phase,
        "bullish": bullish,
        "score": score,
        "reason": reason,
        "reasons": [reason]
    }
