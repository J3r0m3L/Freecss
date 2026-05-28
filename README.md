# Deleveraging Watch

A single-user, always-on market-awareness dashboard. It tracks ~10–20 instruments
through the trading day and pushes notifications when price/volume/spread,
news/social, or factor signals suggest a **deleveraging event against your stated
thesis**. Purely informational — no order routing, paper trading, or backtesting.

Full architecture: [DESIGN.md](DESIGN.md). Phased roadmap: DESIGN.md §16.

## Status — Phase 0 (Skeleton) ✅

What runs today:
- Flask + Flask-SocketIO + APScheduler single process (`server/`).
- SQLite schema (full §6) with WAL, seeded with the 80-bucket factor universe
  (§9) and the default curated X accounts (§10.3).
- Watchlist CRUD (`/api/watchlist`), instrument detail + 1m bars, settings, and
  `/api/health`.
- A **stub data adapter** streaming synthetic quotes over the `tick:<symbol>`
  Socket.IO channel, and a **console notifier** — both swappable seams for the
  Phase 1 Massive feed and Pushover notifier.
- React + Vite watchlist grid (`web/`) with live price updates.

Not yet wired (later phases): live Massive feed + threshold alerts (Phase 1),
FinBERT news/X pipeline + earnings (Phase 2), factor exposures (Phase 3), notes
+ liquidity + ops polish (Phase 4).

## Run the backend

```bash
# from the repo root (Freecss/), using the project venv
../bin/pip install -e .          # Phase 0 deps
cp .env.example .env             # optional; Phase 0 runs with no keys
../bin/python -m server          # serves http://127.0.0.1:5000
```

Quick check:

```bash
curl 127.0.0.1:5000/api/health
curl -X POST 127.0.0.1:5000/api/watchlist \
  -H 'Content-Type: application/json' -d '{"symbol":"AAPL","direction":"BULL"}'
curl 127.0.0.1:5000/api/watchlist
```

> Bind address is IPv4 `127.0.0.1`. On macOS, `localhost` may resolve to IPv6
> `::1` first — use `127.0.0.1` explicitly with curl.

## Run the frontend (needs Node ≥ 18)

```bash
cd web
npm install
npm run dev        # http://localhost:5173, proxies /api + Socket.IO to :5000
# or: npm run build  → emits web/dist, which the Flask server serves at /
```

## Configuration

All config is environment-sourced (`.env`, loaded by python-dotenv). See
`.env.example`. Phase 0 needs nothing set: `DW_DATA_ADAPTER=stub` and
`DW_NOTIFIER=console`. Credentials are surfaced to the UI only as present/absent,
never echoed back.

## Layout

```
server/   Flask app, SQLite schema + seeds, adapters, jobs, alerts, REST API
web/      React + Vite + TS SPA
DESIGN.md full design document (source of truth)
```
