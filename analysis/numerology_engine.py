"""
NAKSHATRA AI
Numerology Engine v5.1
"""

from datetime import datetime


def reduce_number(n):
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(d) for d in str(n))
    return n


def symbol_number(symbol):
    total = 0
    for ch in symbol.upper():
        if ch.isalpha():
            total += ord(ch) - 64
    return reduce_number(total)


def analyze_numerology(timestamp, symbol):

    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    # Life Path Number
    dob_sum = (
        timestamp.day
        + timestamp.month
        + timestamp.year
    )
    life_path = reduce_number(dob_sum)

    # Universal Day Number
    universal_day = reduce_number(
        timestamp.day
        + timestamp.month
        + timestamp.year
    )

    # Symbol Number
    sym_num = symbol_number(symbol)

    score = 50
    bullish = False
    reasons = []

    if life_path in [1, 3, 5, 6, 8]:
        score += 15
        bullish = True
        reasons.append(f"Life Path {life_path} is supportive.")

    if universal_day in [1, 3, 5, 6, 8]:
        score += 20
        bullish = True
        reasons.append(f"Universal Day {universal_day} is positive.")

    if sym_num in [1, 5, 8]:
        score += 15
        bullish = True
        reasons.append(f"{symbol} number {sym_num} is favourable.")

    score = max(0, min(score, 100))

    if score >= 70:
        bias = "BUY"
    elif score <= 35:
        bias = "SELL"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "bullish": bullish,
        "score": score,
        "life_path": life_path,
        "universal_day": universal_day,
        "symbol_number": sym_num,
        "reasons": reasons
    }
