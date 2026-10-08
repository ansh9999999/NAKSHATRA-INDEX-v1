# NAKSHATRA INDEX v1

Lightweight Indian-index-only dashboard for Render free 512 MB instances.

## Supported markets
- NIFTY 50
- BANKNIFTY
- NIFTY IT
- SENSEX

## Design goals
- No APScheduler inside the web process
- No scanner background job
- No crypto/commodity code
- Bounded in-memory caches
- Quote endpoint separated from heavy analysis
- Single-flight background analysis per symbol
- Option chain via Kotak Neo only in this build

## Render start command
`uvicorn main:app --host 0.0.0.0 --port $PORT`

## Required environment
`KOTAK_CONSUMER_KEY`
`KOTAK_ACCESS_TOKEN` (if using access-token auth)
`KOTAK_MOBILE_NUMBER`
`KOTAK_UCC`
`KOTAK_MPIN`
`KOTAK_TOTP_SECRET` (if unattended TOTP login is used)
`KOTAK_ENVIRONMENT=prod`
`KOTAK_NEO_FIN_KEY=neotradeapi`

Do not enable a scheduler variable. This project intentionally has no scheduler.
