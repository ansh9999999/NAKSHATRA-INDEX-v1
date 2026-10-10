# NAKSHATRA INDEX — restored dashboard build

This build restores the premium dark/neon dashboard layout and the key v3.5-style sections while retaining the INDEX-only Kotak Neo backend.

## Sections
- Live market and multi-timeframe technical trends
- AI final agreement and reasons
- Futures × options cross-check and top-5 OI tables
- ATR-based illustrative Trade Plan (entry, stop, T1/T2/T3, R:R) only when a directional signal and ATR are available
- Astrology, Nakshatra/Moon/Tithi/Rahu context, numerology and sentiment
- Scanner and explicit status panels for gamma, institutional flows, catalysts and trade journal/equity curve (these are not connected in this INDEX backend and are not fabricated)

## Render start command
`uvicorn main:app --host 0.0.0.0 --port $PORT`

## Environment
Configure the existing Kotak Neo credentials in Render Environment. Do not commit credentials.

## Resource safeguards
- Single-flight analysis by symbol
- Limited thread pools
- Cache TTLs and bounded top-level caches
- Timed-out auxiliary calls are not repeatedly queued while an earlier call is still running
- Dashboard polls quotes every 20 seconds and scanner every 120 seconds; analysis is polled only while loading

## Important
Render Free's 512 MB limit is a hard limit. Provider SDKs and pandas can still exceed it depending on the runtime and API responses; verify Render Events after deployment. A `Service recovered` event means the instance became healthy again, not that a memory issue has been permanently resolved.
