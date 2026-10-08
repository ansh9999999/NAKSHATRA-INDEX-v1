"""
NAKSHATRA AI
Rahu Kaal Engine v5.1
"""

from datetime import datetime, time


def get_rahu_kaal(timestamp):

    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    current_time = timestamp.time()

    # Placeholder Rahu Kaal
    # Future: Replace with location-based calculation

    rahu_start = time(13, 30)
    rahu_end = time(15, 0)

    active = rahu_start <= current_time <= rahu_end

    if active:
        score = 20
        bullish = False
        reason = "Rahu Kaal active. Avoid fresh entries."
    else:
        score = 80
        bullish = True
        reason = "Outside Rahu Kaal."

    return {
        "active": active,
        "bullish": bullish,
        "score": score,
        "reason": reason,
        "reasons": [reason]
        }
