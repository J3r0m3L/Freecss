# Deleveraging Watch — Design Document

A Flask + React dashboard for tracking ~10–20 instruments throughout the trading day, with **Pushover** push notifications triggered by signals that suggest a **deleveraging event** against the user's stated directional thesis.

---

## 1. Terminology

- **Watch instrument**: a tracked symbol (initially equities; later commodities/ETFs/futures).
- **Thesis direction**: user's stated bias on the instrument — `BULL` or `BEAR`.
- **Adverse move**: a price move *opposite* the thesis. Only adverse moves can trigger a deleveraging alert.
  - Bullish thesis + price crash → adverse.
  - Bearish thesis + price rip → adverse.
  - Aligned moves are still logged but do not page.
- **Deleveraging signal**: a price move large enough, fast enough, with confirming microstructure (volume spike, spread blow-out) that suggests forced unwinds rather than ordinary noise.
- **Update log**: human-written notes for post-hoc explanation. **Two scopes:** per-symbol notes pinned to a `(symbol, timestamp)`, and global market-wide notes pinned only to a `timestamp` (e.g., "Powell hawkish 2026-05-25"). Global notes auto-surface on per-symbol drill-downs via FinBERT cosine match against the watch's `profile_embedding`.

---

## 2. Goals and Non-Goals

**Goals**
- Single-user dashboard runnable 24/7 on a MacBook.
- Two views: aggregated watchlist grid + per-symbol drill-down.
- Persistent watchlist with thesis direction.
- Real-time-ish price, bid-ask, volume with hard-threshold alerting.
- News + social surfacing: per-symbol headlines via Massive's bundled `/v2/reference/news`, macro/policy/geopolitical via curated X accounts. FinBERT scores news + X. See §10.
- Correlated/factor/thematic context.
- Earnings calendar.
- Manually editable update log per symbol.
- Asset-class agnostic schema (extend to commodities later).

**Permanent Non-Goals** (will never be in scope)
- Order routing, paper trading, or any execution surface. This dashboard is **purely informational** — a personal market-awareness tool. No buttons that send orders, no simulated fills, no "what-if I had bought" UIs.
- Backtesting framework / historical strategy simulation. Historical data exists only to compute live context (factor β, intraday volume baselines, EOD correlations), never to evaluate hypothetical trades or P&L.

**v1 Non-Goals** (may revisit later)
- Multi-user/auth.
- Sub-second tick data or HFT-grade latency.

---

## 3. Foundational decisions

The decisions below shape every later section. Each has a `→ §X` pointer to where it's implemented in detail. §3.8 consolidates costs in one place.

### 3.1 Market data: Massive Stocks Advanced  →  §5, §7

**Massive Stocks Advanced at $199/mo flat.** Real-time SIP tape over WebSocket + REST, no per-symbol or volume charges. Polygon rebranded to Massive in 2026; the legacy `polygon.io` endpoints still work. **Finnhub** is used only for the earnings calendar and the `/stock/profile2` endpoint (sector/industry/cap/logo).

Lower Massive tiers (Basic free, Starter $29, Developer $79) are all 15-min delayed and unusable for spread alerts. yfinance is not used anywhere — Massive covers watched equities, ETF proxies, and commodity ETF proxies in one feed.

Alternatives considered and ruled out (kept for reference):

| Option | Cost | Why not |
|---|---|---|
| Tradier Pro | $10/mo + brokerage acct | Cheapest real-time NBBO; requires opening a brokerage account; 2026 reviews flag brokerage-side issues. Fallback if cost ever needs to drop. |
| Databento Standard | $199/mo flat | Same price as Massive Advanced; killed usage-based live equities Jan 2025. No cost win. |
| Alpaca free (IEX) | $0 | IEX only covers 2–3% of US equity volume; spread alerts would fire on artifacts. |
| Alpaca Algo Trader+ | $99/mo | Only worth it if also routing orders through Alpaca — we never will. |
| IBKR | ~$10–20/mo exchange fees | Requires IBKR account + TWS/Gateway; ops overhead too high. |

**Paid add-ons gated to later phases (not in v1):**

| Phase | Product | Cost | Adds |
|---|---|---|---|
| Phase 6 (v2) | Massive Options Advanced | ~$199/mo | OPRA L1, IV, Greeks, OI, unusual options volume |
| Phase 7 (v3) | Massive Futures Advanced | sales-quoted | ES/NQ/RTY/VX/CL/GC live for overnight context |

### 3.2 Notifications: Pushover (4 applications)  →  §12

**Pushover only.** $4.99 one-time iOS app, free account, 10,000 messages/month free quota. No SMS / Twilio — Pushover's `priority=2` emergency mode (repeats every 60s for up to 30 min until acknowledged) replaces SMS-as-escalation.

Pushover shows the *application's* icon on every notification (no per-message icon override). To get distinct lock-screen icons per alert type, we create **four Pushover applications** under one account, each with its own icon + token, all targeting the same User Key:

| Application | Icon | Used for |
|---|---|---|
| `Deleveraging Watch — Critical` | 🚨 | `severity='critical'` (combined adverse signal, critical-news bombshell, etc.) |
| `Deleveraging Watch — Warning` | ⚠️ | `severity='warn'` / `severity='high'` (single-rule warns, non-bombshell news) |
| `Deleveraging Watch — News` | 📰 | morning digest delivery |
| `Deleveraging Watch — Info` | ℹ️ | `severity='info'` reminders |

All four share the same 10k/month quota. **ntfy.sh** is the fallback if Pushover ever changes terms — kept as a swap target behind the `Notifier` interface, not shipped in v1.

### 3.3 Sentiment + relevance: FinBERT locally, Haiku for one-shot setup  →  §10

**Why sentiment at all.** Sentiment polarity (signed) gates the **adverse-to-thesis** check that drives every news alert in §8 — without a signed scalar, the bull/bear direction-aware filter collapses and the system can flag *topical* but not *directional* news. Sentiment magnitude (`|sentiment|`) then scales the **severity ladder** so a strong-but-relevant headline pages `critical` while a mild one queues to the morning digest, which is what keeps Pushover from spamming on ~6,000 headlines/day.

**Sentiment gates alerts, not display.** On the dashboard itself (§11.A cards, §11.B global feed, §11.C per-symbol News tab), every headline that clears the `relevance ≥ 0.5` floor is shown regardless of whether it's positive, negative, or neutral. Polarity is rendered as a chip/dot for at-a-glance scanning, never as a default visibility filter. The sentiment-polarity filter chip exists but defaults to **"all"**; the user opts in if they want to narrow the feed. The reason: positive news on a bull-thesis watch is still *information* the user wants to see; it just shouldn't *page* them.

**FinBERT** (`ProsusAI/finbert` or `yiyanghkust/finbert-tone`) runs locally on CPU. One forward pass per headline yields **both** the sentiment logits AND the last-hidden-state embedding (mean-pool → 768-dim, L2-normalized). ~440MB on disk, ~50–200ms per headline, no API cost. Loaded once at startup.

**Three derived signals per headline** (full pipeline in §10.3):

| Signal | How |
|---|---|
| `sentiment` ∈ [−1, 1] | `p_positive − p_negative` from the FinBERT softmax. Also stored: `sentiment_label`, `sentiment_conf`. |
| `tickers_json` | Regex against (watchlist symbols ∪ `factor_bucket_candidate` symbols), plus any `$XXX` cashtag mentions (which catch deliberate ticker references regardless of the known-symbol set — the main source for X posts, which arrive untagged). Word-boundary heuristics; common false-positive single/double-letter tickers (A, IT, BE) blocklisted. Massive news arrives pre-tagged, so `tickers_final = massive_tickers[] ∪ regex_extracted`. |
| `relevance` ∈ [0, 1] | **Hybrid: `max(rule_score, 0.85 × cosine_sim)`**. Rule pass: 1.0 explicit watchlist match, 0.7 sector/industry keyword, 0.4 macro-bucket match. Semantic pass: cosine between the headline's FinBERT embedding and the watch's `profile_embedding`. `relevance_source` records which path won. |

The rule floor (1.0 on explicit ticker match) is non-negotiable — if a headline says "NVDA" it must be max-relevant regardless of cosine. The semantic pass catches cases the rules miss ("TSMC fab capacity cut" → relevant to NVDA via embedding cosine even without "NVDA" in the headline).

**Profile generation — the one place we use Haiku.** Each watched stock's `profile_embedding` comes from FinBERT-embedding a Haiku-generated paragraph. At watchlist-add and monthly via `profile_text_refresh`, call Claude Haiku 4.5 (`temperature=0`) to write a 4–6 sentence economic-exposure paragraph using slow-moving inputs only (sector, industry, country, Finnhub description). Volatile fields (market cap, recent prices, current executives) are deliberately excluded so the profile stays stable for ~one month. Cost: ~$0.10/mo for 20 watches.

Haiku is used **only** for monthly `profile_text` generation. The earlier macro-query generator that fed Brave was removed when Brave was dropped — macro/policy coverage now comes from curated X government and journalist accounts (§10.3).

Prompt template (lives in `server/nlp/profile_text.py`):

```
Write a 4–6 sentence economic exposure profile for {symbol} ({display_name}).

The profile will be embedded with FinBERT and used to retrieve relevant news
headlines via cosine similarity, so:
- Use the vocabulary that financial news headlines use ("interest rates",
  "tariffs", "antitrust", "supply chain", "Fed policy", "discount rate",
  "forex", "OPEC", "regulation", etc.) wherever those categories apply.
- Enumerate every macro, regulatory, factor, sector, or geopolitical category
  whose news could move this stock's price.
- Use natural prose, not bullet lists.

Do NOT include:
- Investment opinions, price targets, or buy/sell language.
- Day-to-day volatile specifics (market cap figures, recent price moves,
  last quarter's earnings number, today's news, current executives by name).
  The profile is regenerated monthly and should remain stable across roughly
  that horizon — describe enduring exposure categories, not transient events.
- Proper-noun specifics beyond what's already in the inputs.

It IS fine to reflect medium-term realities (e.g., "exposed to AI capex" if
the industry inputs justify it, "EU antitrust scrutiny" for large platforms,
"China supply-chain dependency" for hardware names).

Inputs (slow-moving fields only):
- Sector:      {meta.sector}
- Industry:    {meta.industry}
- Country:     {meta.country}
- Description: {meta.description}

Output plain prose only, no headers, no markdown.
```

Settings: `model="claude-haiku-4-5"`, `temperature=0`, `max_tokens≈400`. Output stored in `instrument.profile_text` (audit + edit target); FinBERT-embedded and L2-normalized into `instrument.profile_embedding`. If the Anthropic API is unreachable at watchlist-add, falls back to embedding the raw Finnhub description and sets `meta.profile_pending=true` for a later retry.

Sentiment, ticker extraction, and per-headline relevance scoring use FinBERT-only — no LLM in the per-headline hot path. Haiku is strictly setup-time work (profile_text generation only; the prior macro-query generator was removed when Brave was dropped — see §10).

**FinBERT on X posts (§10.3).** Curated X account posts are scored by the same FinBERT pipeline as news headlines — same forward pass, same sentiment scalar, same embedding-cosine relevance against `profile_embedding`. Honest caveat: FinBERT was trained on Reuters-style financial news, not tweets. It handles news-adjacent prose well (Bloomberg journalists, central-bank communications, government statements) but is noisier on short/casual tweets. We accept that for v1 because (a) the curated account list is deliberately weighted toward news-adjacent voices and (b) running a second model just for X adds operational complexity for marginal gain. If quality becomes an issue, swap in `cardiffnlp/twitter-roberta-base-sentiment-latest` for `source='x'` rows specifically.

### 3.4 PCA: bucket-representative selection  →  §9

Each thematic/factor bucket (AI, Momentum, Semis, …) has many self-styled ETFs claiming to track the same concept — 100+ for AI alone. They're highly intra-correlated; tracking all of them spams alerts and adds zero information.

**PCA picks the one ETF that best represents each bucket's common variance.** For each bucket, run PCA over the candidate basket's daily returns over ~6 months; the ETF with the highest `|PC1 loading|` becomes the **representative**. `pc1_var_explained` is persisted as a cohesion diagnostic (broad indices ~99.9%, style factors ~80%, crowded thematics ~65%). Refresh quarterly.

PCA runs from v1 across **every** bucket — no hand-picked representatives anywhere. The seed file specifies only candidate baskets. v2 (optional) adds a per-user candidate-basket editor.

This is **distinct from "factor isolation"** (subtracting market beta from a factor return to get the orthogonal residual) — that's a separate technique potentially in v2+; not what PCA is doing here.

### 3.5 Quiet hours: 09–17 ET work, 08:00 ET digest  →  §12

Work hours Mon–Fri **09:00–17:00 ET** — everything pages. Outside work hours + weekends, **only `critical` pages**; `high` / `warn` queue to an **08:00 ET morning digest**; `info` drops entirely. Severity is 4-tier (`info` / `warn` / `high` / `critical`) used uniformly across all `kind`s. News has its own severity ladder (relevance × |sentiment| × ticker-match) where only a strict `critical-news` tier wakes you overnight.

Defaults are tuned for a US-based trader who works the regular session but watches non-US equities active overnight.

### 3.6 24/7 laptop ops  →  §14

- macOS sleeps lids-closed → use `caffeinate -d -i -m -s` or amphetamine.app.
- Wifi flaps → backend must reconnect and not double-alert on backfill.
- App crashes → wrap in `launchd` so it restarts; log to a rotating file.
- Scheduler is timezone-aware (NYSE session for equities, 24/7 for crypto).

### 3.7 "Deleveraging" naming convention  →  §6, §8

Every `alert` row carries an `adverse` boolean (1 if move opposite thesis) plus a `kind` enum (`px_jump`, `spread`, `volume`, `combined`, `news`, `social_x`, `earnings`; v2 adds `factor`). The UI labels `adverse=1 ∧ kind='combined' ∧ severity='critical'` as "Deleveraging Watch"; lower-tier adverse signals page with more specific labels (e.g., "AMZN volume z=4.2 vs 🐂 thesis", "AMZN @SecTreasury post: tariff exposure").

### 3.8 Cost summary  →  §16

| Item | Monthly recurring | One-time |
|---|---|---|
| Massive Stocks Advanced (quotes + `/v2/reference/news` included) | $199 | — |
| X API (curated account polling, per-post-read billing — see §10.3) | ~$10–30 | — |
| Pushover (iOS app) | — | $4.99 |
| Anthropic Haiku (profile_text only; macro-query job removed) | ~$0.10 | — |
| Finnhub (earnings + profile2) | $0 (free tier) | — |
| FinBERT (local) | $0 | — |
| **v1 total** | **~$210–230/mo** | **$5 one-time** |
| Phase 6 add: Massive Options Advanced | +$199/mo | — |
| Phase 7 add: Massive Futures Advanced | +sales-quoted | — |

Brave Search was removed: the per-symbol news job moved to Massive's bundled `/v2/reference/news` endpoint, and macro/policy/geopolitical coverage moved to curated X accounts (government + central banks + journalists). See §10 for the rewritten pipeline and §17 for the decision record.

---

## 4. High-level architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          MacBook (always-on)                          │
│                                                                       │
│  ┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐    │
│  │  React SPA  │◄──►│   Flask + Socket │◄──►│  SQLite (WAL)    │    │
│  │  (Vite)     │    │   .IO server     │    │                  │    │
│  └─────────────┘    └────────┬─────────┘    └──────────────────┘    │
│                              │                                        │
│                              │ in-process                            │
│                     ┌────────▼──────────┐                            │
│                     │  APScheduler      │                            │
│                     │  - quote stream   │                            │
│                     │  - massive news   │                            │
│                     │  - x account poll │                            │
│                     │  - factor refresh │                            │
│                     │  - earnings sync  │                            │
│                     └────────┬──────────┘                            │
│                              │                                        │
│   ┌──────────┬───────────────┼──────────────┐                       │
│   ▼          ▼               ▼              ▼                        │
│ ┌──────┐ ┌─────────┐  ┌────────────┐  ┌──────────┐                  │
│ │Massive│ │ Massive │  │  X API     │  │  Finnhub │                  │
│ │ WS+   │ │  /v2/   │  │ /2/users   │  │ earnings │                  │
│ │ REST  │ │reference│  │  /tweets   │  │ +profile2│                  │
│ │quotes │ │ /news   │  │ ($/post)   │  │  (free)  │                  │
│ └──────┘ └─────────┘  └────────────┘  └──────────┘                  │
│   └───────────┴─────────FinBERT (local)───┘                          │
│                                                                       │
│                     ┌──────────────────┐                             │
│                     │  Pushover API    │                             │
│                     │  (4 apps: crit / │                             │
│                     │   warn/news/info)│                             │
│                     └──────────────────┘                             │
└──────────────────────────────────────────────────────────────────────┘
```

**Process model**
- One Python process running Flask + Flask-SocketIO + APScheduler. SQLite is more than enough for a single-user app. No Redis/Celery — that's overkill for a laptop.
- Frontend is built with Vite and served as static files by Flask. In dev, Vite runs separately on `:5173`.

**Why a single process**: APScheduler shares an `Engine` with Flask, can push events to Socket.IO directly, no IPC overhead. The tradeoff is that a slow scheduler job can block requests; mitigate with a background thread pool (`BackgroundScheduler` w/ `ThreadPoolExecutor(max_workers=4)`).

---

## 5. Data sources (v1)

| Need | Source | Notes |
|---|---|---|
| Real-time L1 quote (bid, ask, last, size) | **Massive Stocks Advanced** WebSocket (`wss://socket.polygon.io/stocks` — note legacy `polygon.io` endpoints still in use post-rebrand) | $199/mo flat; full SIP tape, no per-symbol charge |
| Recent trades / VWAP / volume | Massive trades stream | Same connection |
| Historical bars (1m, 1d) | Massive REST aggregates endpoint | Backfill on reconnect; tick history available on Advanced tier |
| Liquidity (ADV, spread, depth, exit-cost) | Derived in-process from existing `bar_1m` + `tick` | No extra subscription. EOD job rolls 21-day means; exit liquidity computed on-demand from `watch.position_size`. See §6 `liquidity_daily` table and §11.C Microstructure tab. |
| Factor/thematic/commodity proxy bars | Massive REST aggregates | All ETF proxies (SPY, QQQ, MTUM, SOXX, GLD, USO, …) — same feed as watched equities |
| Per-symbol news headlines | **Massive `/v2/reference/news`** | Included in Stocks Advanced ($0 incremental). Ticker-tagged; returns title, description, URL, image, publisher, `tickers[]`, `keywords[]`, and pre-computed `insights[].sentiment`. Updated hourly. We re-score with FinBERT for consistency; Massive's `insights` is kept as a cross-check. See §10.2. |
| Curated X account posts (macro/policy/geopolitical + ticker catalyst tweets) | **X API `/2/users/:id/tweets`** (per-post-read billing, $0.005/post returned, 2M/mo cap) | ~$10–30/mo at the curated-list scale in §10.3. Account list lives in `social_account_watch` (~15 default handles seeded from `social_watch.yaml`; editable in Settings). Polled every 1 min. Truth Social covered transitively (Trump cross-posts to X). |
| Headline + post sentiment | **FinBERT** (`ProsusAI/finbert`) local inference | 3-class softmax → signed scalar; applied to Massive news headlines and X post text. See §3.3 for caveats on tweet quality. |
| Headline + post relevance + ticker extraction | Rule-based (regex + watchlist/sector match) + cosine vs `instrument.profile_embedding` (FinBERT) | Pure Python regex + one cosine; uniform across news and X. |
| Symbol reference (tradeable? exchange? SIC?) | Massive `/v3/reference/tickers/{symbol}` | Called once when user adds a symbol; cached |
| Sector / industry / market cap / logo | Finnhub `/stock/profile2?symbol={symbol}` | Free tier, ~60 calls/min. `finnhubIndustry` ≈ GICS sub-industry. Refresh quarterly. |
| Earnings calendar | Finnhub `/calendar/earnings` | Free tier; `earnings_sync` pulls a rolling 14d window daily at 02:00 ET. |
| Macro/economic calendar (Phase 2) | Trading Economics or FRED | Optional |

**Removed from v1:** Brave Search (replaced by Massive's bundled news endpoint + curated X feed for macro). The Haiku-driven macro-query generator that fed Brave's macro/policy queries was removed at the same time. See §17 for the decision record.

---

## 6. Database schema (SQLite, WAL mode)

Asset-class generic: every tracked thing is an `instrument`. A watchlist entry binds an instrument to a thesis and per-symbol thresholds.

```sql
-- A symbol the user could track. Pre-seeded with equities; extendable.
CREATE TABLE instrument (
  id              INTEGER PRIMARY KEY,
  symbol          TEXT NOT NULL UNIQUE,        -- 'AAPL', 'SPY', 'USO'
  display_name    TEXT NOT NULL,
  asset_class     TEXT NOT NULL,               -- 'equity','etf','future','crypto','index'
  exchange        TEXT,
  data_adapter    TEXT NOT NULL,               -- 'massive' (v1); future: 'ibkr','coinbase', etc.
  meta_json       TEXT,                        -- JSON blob (see shape below)
  meta_refreshed_at TIMESTAMP,                 -- last profile pull; refresh quarterly
  profile_text    TEXT,                        -- Haiku-generated economic-exposure paragraph.
                                               -- Built only from time-invariant inputs (sector,
                                               -- industry, country, description). Audit + edit target;
                                               -- regeneratable from the Haiku prompt in §3.3.
  profile_embedding BLOB                       -- 768-dim float32 FinBERT mean-pooled embedding of
                                               -- profile_text (L2-normalized). Used for hybrid
                                               -- relevance scoring (§3.3, §10). Recomputed by
                                               -- profile_refresh whenever profile_text changes.
);
-- meta_json shape (populated by Massive ticker reference + Finnhub /stock/profile2):
-- {
--   "sector":          "Technology",                   // Finnhub
--   "industry":        "Semiconductors",               // Finnhub `finnhubIndustry` (≈ GICS sub-industry)
--   "country":         "US",                           // Finnhub
--   "market_cap_m":    3424567.0,                      // Finnhub, USD millions
--   "ipo_date":        "1980-12-12",                   // Finnhub
--   "logo_url":        "https://...",                  // Finnhub
--   "website":         "https://www.apple.com/",       // Finnhub
--   "sic_code":        3571,                           // Massive (fallback)
--   "sic_description": "Electronic Computers",         // Massive (fallback)
--   "description":     "Apple Inc. designs ...",       // Massive (optional)
--   "news_keywords":   ["iPhone","App Store"]          // hand-curated overrides for news bucket (optional)
-- }
-- For ETFs / index proxies: Finnhub profile is sparse; populate hand-curated fields via the
-- factor_bucket seed file (sector/industry left null, factor_bucket.label carries the labeling).

-- User watchlist with thesis.
CREATE TABLE watch (
  id              INTEGER PRIMARY KEY,
  instrument_id   INTEGER NOT NULL REFERENCES instrument(id),
  direction       TEXT NOT NULL CHECK(direction IN ('BULL','BEAR')),
  entered_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  active          INTEGER NOT NULL DEFAULT 1,
  -- Per-symbol overrides; NULL = use global defaults.
  px_jump_pct     REAL,                        -- e.g. 0.03 = 3%
  px_jump_window_s INTEGER,                    -- e.g. 300
  spread_bps_max  REAL,                        -- e.g. 50 bps
  volume_zscore   REAL,                        -- e.g. 3.0
  position_size   REAL,                        -- optional; user-entered shares held.
                                               -- Used only for the exit-liquidity calc in §11.C
                                               -- ("days to exit", "cost to exit bps"). NULL = no calc.
  notes           TEXT
);

-- Append-only time series of quotes/trades. Keep 30 days hot; archive older.
CREATE TABLE tick (
  instrument_id   INTEGER NOT NULL REFERENCES instrument(id),
  ts              TIMESTAMP NOT NULL,
  bid             REAL,
  ask             REAL,
  last            REAL,
  bid_size        INTEGER,
  ask_size        INTEGER,
  trade_size      INTEGER,
  PRIMARY KEY (instrument_id, ts)
) WITHOUT ROWID;

-- Aggregated 1m bars for charts (computed from ticks).
CREATE TABLE bar_1m (
  instrument_id   INTEGER NOT NULL,
  ts              TIMESTAMP NOT NULL,
  o REAL, h REAL, l REAL, c REAL,
  v INTEGER, vwap REAL,
  PRIMARY KEY (instrument_id, ts)
) WITHOUT ROWID;

-- Alert events that fired.
CREATE TABLE alert (
  id              INTEGER PRIMARY KEY,
  instrument_id   INTEGER NOT NULL,
  ts              TIMESTAMP NOT NULL,
  kind            TEXT NOT NULL,               -- 'px_jump','spread','volume','combined','news',
                                               --   'social_x','earnings' (v2 adds 'factor')
  severity        TEXT NOT NULL,               -- 'info','warn','high','critical'
  adverse         INTEGER NOT NULL,            -- 1 if against thesis
  payload_json    TEXT NOT NULL,
  notified_via    TEXT,                        -- 'pushover:critical','pushover:warn','pushover:news','pushover:info','console','digest'
  pushover_receipt TEXT,                       -- receipt id for priority=2 emergency sends (for ack tracking)
  acked_at        TIMESTAMP,
  quiet_queued    INTEGER NOT NULL DEFAULT 0,  -- 1 if held back during quiet hours, awaiting next digest
  digested_at     TIMESTAMP                    -- when the morning digest delivered this alert; NULL if never digested
);

-- News headlines from Massive's /v2/reference/news endpoint (included in Stocks Advanced).
-- Re-scored locally by FinBERT + rule-based relevance so the scoring path is uniform across all
-- text sources (news, X posts). Massive's own `insights[].sentiment` is kept in payload_json
-- (alert) for cross-check but is not the source of truth.
CREATE TABLE news (
  id                INTEGER PRIMARY KEY,
  fetched_at        TIMESTAMP NOT NULL,
  source            TEXT,                      -- Massive's `publisher.name` (e.g., 'Benzinga', 'Zacks')
  url               TEXT UNIQUE,               -- Massive's `article_url`
  title             TEXT NOT NULL,
  snippet           TEXT,                      -- Massive's `description`
  published_at      TIMESTAMP,                 -- Massive's `published_utc`
  massive_id        TEXT,                      -- Massive's `id` for dedupe on poll overlap
  massive_insights  TEXT,                      -- raw JSON of Massive's `insights[]` (their own
                                               -- per-ticker sentiment + reasoning); kept for
                                               -- cross-check, not used in alert rules
  relevance         REAL,                      -- 0..1, max(rule_score, 0.85 * cosine_sim) — see §3.3
  relevance_source  TEXT,                      -- 'symbol' | 'sector' | 'semantic' (no 'macro' anymore)
  sentiment         REAL,                      -- -1..1 from FinBERT (p_positive - p_negative)
  sentiment_label   TEXT,                      -- FinBERT class: 'positive' | 'negative' | 'neutral'
  sentiment_conf    REAL,                      -- max softmax prob from FinBERT
  tickers_json      TEXT                       -- Massive's `tickers[]` ∪ regex-extracted tickers
);
CREATE INDEX idx_news_published ON news(published_at DESC);
CREATE INDEX idx_news_massive_id ON news(massive_id);

-- Curated X accounts the user follows. Seeded from server/db/seeds/social_watch.yaml on first
-- startup; thereafter editable via Settings (§11.E). The list is intended to be roughly
-- time-invariant — users add a new high-signal voice rarely, not daily.
CREATE TABLE social_account_watch (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL DEFAULT 'x' CHECK(source IN ('x')),  -- X-only in v1; column kept
                                               -- so a future source (e.g., Reddit) is an additive change
  handle          TEXT NOT NULL,               -- '@DeItaone' style (stored without '@')
  label           TEXT,                        -- human-friendly display (e.g., 'Federal Reserve')
  external_id     TEXT,                        -- numeric X user_id from one-time User: Read
  active          INTEGER NOT NULL DEFAULT 1,
  added_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_polled_at  TIMESTAMP,
  last_post_id    TEXT,                        -- since_id (tweet id); used to fetch only-new on next poll
  UNIQUE(source, handle)
);

-- Individual social posts ingested from X. Each post returned by /2/users/:id/tweets gets a row.
CREATE TABLE social_post (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL DEFAULT 'x' CHECK(source IN ('x')),
  account_id      INTEGER NOT NULL REFERENCES social_account_watch(id),
  external_post_id TEXT NOT NULL,              -- tweet id
  posted_at       TIMESTAMP NOT NULL,
  fetched_at      TIMESTAMP NOT NULL,
  body            TEXT NOT NULL,               -- full tweet text
  url             TEXT,                        -- 'https://x.com/<handle>/status/<id>'
  tickers_json    TEXT,                        -- regex-extracted tickers from body
  -- FinBERT outputs
  relevance       REAL,
  relevance_source TEXT,                       -- 'symbol' | 'sector' | 'semantic'
  sentiment       REAL,
  sentiment_label TEXT,
  sentiment_conf  REAL,
  UNIQUE(source, external_post_id)
);
CREATE INDEX idx_social_post_posted ON social_post(posted_at DESC);
CREATE INDEX idx_social_post_account ON social_post(account_id, posted_at DESC);

-- User-written notes on what happened. Two scopes:
--   instrument_id NOT NULL → per-symbol note (visible on that watch's Notes tab)
--   instrument_id IS NULL  → global market-wide note (visible on the /notes route,
--                            and auto-surfaced on per-symbol drill-downs via
--                            cosine(body_embedding, instrument.profile_embedding) ≥ 0.55)
CREATE TABLE update_log (
  id              INTEGER PRIMARY KEY,
  instrument_id   INTEGER,                     -- nullable; see scope rules above
  ts              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  body            TEXT NOT NULL,
  body_embedding  BLOB,                        -- 768-dim float32 FinBERT pooled embedding of `body`,
                                               -- L2-normalized. Computed on insert/edit. Used by the
                                               -- "Related market notes" panel on drill-down views.
                                               -- Only computed for global notes (instrument_id IS NULL);
                                               -- NULL for per-symbol notes.
  linked_alert_id       INTEGER REFERENCES alert(id),
  linked_news_id        INTEGER REFERENCES news(id),           -- Massive news article
  linked_social_post_id INTEGER REFERENCES social_post(id)     -- X tweet; set when the user
                                                               -- clicks "Save to notes" on an
                                                               -- X-sourced row in §11.B.
                                                               -- At most one of (linked_news_id,
                                                               -- linked_social_post_id) is non-NULL.
);

-- Daily liquidity snapshot. EOD job rolls 21d means; used for ADV + exit-liquidity displays.
CREATE TABLE liquidity_daily (
  instrument_id     INTEGER NOT NULL REFERENCES instrument(id),
  date              DATE NOT NULL,
  adv_shares_21d    REAL,                      -- 21-trading-day rolling mean of daily volume (shares)
  adv_dollar_21d    REAL,                      -- 21-day rolling mean of close × volume (USD)
  spread_avg_bps    REAL,                      -- session-average L1 bid-ask spread, basis points
  pct_zero_volume   REAL,                      -- fraction of 1m bars with zero volume (illiquidity flag)
  computed_at       TIMESTAMP NOT NULL,
  PRIMARY KEY (instrument_id, date)
);
CREATE INDEX idx_liquidity_latest ON liquidity_daily(instrument_id, date DESC);

-- Upcoming earnings.
CREATE TABLE earnings (
  instrument_id   INTEGER NOT NULL,
  scheduled_at    TIMESTAMP NOT NULL,
  when_hint       TEXT,                        -- 'bmo','amc','dmt'
  eps_estimate    REAL,
  rev_estimate    REAL,
  fetched_at      TIMESTAMP NOT NULL,
  PRIMARY KEY (instrument_id, scheduled_at)
);

-- Factor/thematic bucket → representative ETF mapping. Representative is the ETF we
-- actively regress watches against. Picked by PCA from the candidate basket (§9, §3.4).
CREATE TABLE factor_bucket (
  id              INTEGER PRIMARY KEY,
  kind            TEXT NOT NULL,               -- 'index','factor','sector','sub_sector','intl','commodity','thematic'
  label           TEXT NOT NULL UNIQUE,        -- 'AI','Momentum','Semis', ...
  representative_id INTEGER NOT NULL REFERENCES instrument(id),
  pc1_var_explained REAL,                      -- % variance PC1 explains; diagnostic of bucket cohesion
  selected_at     TIMESTAMP NOT NULL,          -- when this rep was chosen (always by PCA in v1)
  active          INTEGER NOT NULL DEFAULT 1
);

-- Candidate ETFs per bucket, with PC1 loadings after each PCA run.
CREATE TABLE factor_bucket_candidate (
  bucket_id       INTEGER NOT NULL REFERENCES factor_bucket(id),
  instrument_id   INTEGER NOT NULL REFERENCES instrument(id),
  pc1_loading     REAL,                        -- |loading| on PC1 from last PCA run
  last_pca_at     TIMESTAMP,
  PRIMARY KEY (bucket_id, instrument_id)
);

-- Per (watch, bucket) regression results. EOD-refreshed; `last_residual` updated intraday.
CREATE TABLE factor_exposure (
  watch_id        INTEGER NOT NULL REFERENCES watch(id),
  bucket_id       INTEGER NOT NULL REFERENCES factor_bucket(id),
  window_days     INTEGER NOT NULL,
  beta            REAL NOT NULL,
  intercept       REAL NOT NULL,
  r_squared       REAL NOT NULL,
  p_value         REAL NOT NULL,
  q_value         REAL,                        -- BH-FDR adjusted; UI uses this
  significant     INTEGER NOT NULL DEFAULT 0,  -- 1 if surfaced after BH-FDR pass at q=0.05
  correlation     REAL NOT NULL,
  last_residual   REAL,                        -- today's residual (refreshed intraday)
  computed_at     TIMESTAMP NOT NULL,
  PRIMARY KEY (watch_id, bucket_id, window_days)
);

CREATE TABLE setting (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

-- Every scheduled job writes one row per successful run. The UI reads this for
-- "last updated at" badges (§11) and the /api/health endpoint (§14).
CREATE TABLE job_run (
  job_name        TEXT NOT NULL,               -- 'massive_news_poll','factor_refresh','earnings_sync', ...
  started_at      TIMESTAMP NOT NULL,
  finished_at     TIMESTAMP,                   -- NULL while in progress
  status          TEXT NOT NULL,               -- 'ok','error','running'
  rows_written    INTEGER,                     -- optional: items processed
  error_message   TEXT,                        -- last error if status='error'
  PRIMARY KEY (job_name, started_at)
);
CREATE INDEX idx_job_run_latest ON job_run(job_name, started_at DESC);

-- Per-API-call billing events. Adapters write one row per billable interaction so
-- the in-dashboard Usage view (§11) shows real spend rather than estimates.
-- One job_run typically produces many rows (one per upstream account polled).
-- Ad-hoc calls outside the scheduler — User: Read on a new X account add,
-- Haiku profile_text on watchlist-add — also write here.
CREATE TABLE api_cost_event (
  id              INTEGER PRIMARY KEY,
  ts              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source          TEXT NOT NULL,               -- 'x:tweets'       — billed per post returned (units = posts)
                                               -- 'x:user_read'    — billed per call (units = 1)
                                               -- 'massive:news'   — free (bundled); units = req count
                                               -- 'haiku:profile_text' — billed per call (units = 1)
  units           INTEGER NOT NULL,            -- posts / requests / calls (unit meaning depends on source)
  unit_cost_usd   REAL NOT NULL,               -- 0.005 (x:tweets), 0.010 (x:user_read), 0.0 (massive),
                                               -- ~0.005 (haiku:profile_text). Stored explicitly so a
                                               -- vendor price change doesn't silently invalidate history.
  cost_usd        REAL NOT NULL,               -- units * unit_cost_usd, denormalized for fast SUM
  ref_job_run     TEXT,                        -- name of the originating scheduled job (NULL if ad-hoc)
  ref_endpoint    TEXT                         -- adapter function or REST endpoint that issued the call
);
CREATE INDEX idx_api_cost_event_recent       ON api_cost_event(ts DESC);
CREATE INDEX idx_api_cost_event_source_month ON api_cost_event(source, ts DESC);
```

**Notes**
- WAL mode is essential — APScheduler writes constantly while the UI reads.
- `tick` table grows fast (~80MB/symbol/day at sub-second granularity). Cap to ~30 days hot and archive older to a yearly Parquet file via a nightly job.
- All timestamps stored UTC; UI renders in user's local TZ.

---

## 7. Backend services (Flask blueprints + scheduler jobs)

### 7.1 REST API (`/api`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/watchlist` | List active watches with latest snapshot |
| POST | `/api/watchlist` | Add `{symbol, direction, thresholds?}`. If `instrument` row doesn't exist yet, looks up Massive ticker reference + Finnhub `/stock/profile2` to populate `meta_json` (sector/industry/cap/logo). Returns the resolved instrument. |
| PATCH | `/api/watchlist/:id` | Update thresholds or direction |
| DELETE | `/api/watchlist/:id` | Deactivate (soft delete) |
| GET | `/api/instrument/:symbol` | Drill-down detail blob |
| GET | `/api/instrument/:symbol/bars?tf=1m&from=...` | Chart data |
| GET | `/api/instrument/:symbol/news?since=...&min_relevance=0.5&sentiment=any\|pos\|neg&source=news\|x\|all&limit=50` | Scored items for one symbol. Returns a **union of `news` rows (Massive) and `social_post` rows where source='x'** with a watch ticker match. Each item: `{id, kind ∈ {'news','x'}, title?, body, url, source, posted_at, relevance, relevance_source ∈ {'symbol','sector','semantic'}, sentiment, sentiment_label ∈ {'positive','negative','neutral'}, sentiment_conf, tickers[]}`. `title` is null for X items (tweets don't have titles); `body` is always populated. Sorted `posted_at DESC` by default. |
| GET | `/api/news?since=...&min_relevance=0.5&sentiment=any\|pos\|neg&ticker=...&source=news\|x\|all&limit=100` | **Global feed** across all active watches (powers §11.B). Same union of Massive news + X posts as the per-symbol endpoint. |
| POST | `/api/notes/from-news/:news_id` | Convenience: create an `update_log` row pre-filled with the headline title + URL and `linked_news_id` set. Body may include `{instrument_id?: int}` to override; if omitted, server attaches the note to the **first watchlist symbol** present in `news.tickers_json` (in watchlist order), or leaves `instrument_id=NULL` (global note) if none of the tickers are watched. Returns the new note. |
| POST | `/api/notes/from-social/:post_id` | Same shape as `/from-news/:news_id`, but for X-sourced rows. Pre-fills the note body with the tweet text + URL and sets `linked_social_post_id`. Auto-attach to the first watchlist ticker in `social_post.tickers_json` (same fallback to global note if none match). |
| GET | `/api/social/accounts?active=true` | List curated X accounts (rows from `social_account_watch`). Powers the editor in §11.E. |
| POST | `/api/social/accounts` | Add a new X account. Body: `{handle, label?}`. The server does a one-shot User: Read against the X API to resolve the numeric `external_id` and validate the handle. Returns the new row. |
| PATCH | `/api/social/accounts/:id` | Update `label` or toggle `active`. |
| DELETE | `/api/social/accounts/:id` | Soft delete (sets `active=0`). The historical `social_post` rows are kept. |
| GET | `/api/instrument/:symbol/exposures?significant_only=true` | Factor exposures: β, ρ, R², p_value, q_value (BH-FDR adjusted), residual per bucket. Default returns only buckets where `significant=1` (passed BH-FDR at q=0.05); pass `significant_only=false` to see all 80. |
| GET | `/api/instrument/:symbol/liquidity?participation=0.10` | ADV (shares + $), session-avg spread, top-of-book sizes, pct_zero_volume, rank-in-watchlist. If `watch.position_size` is set: also returns `days_to_exit = position_size / (participation × adv_shares_21d)` and `cost_to_exit_bps ≈ spread_avg_bps × sqrt(position_size / adv_shares_21d)`. Defaults `participation=0.10`. |
| GET | `/api/alerts?since=...` | Alert history |
| POST | `/api/alerts/:id/ack` | Mark acknowledged |
| GET | `/api/notes?scope=global\|symbol\|all&instrument_id=...&since=...` | List notes. `scope=global` returns only `instrument_id IS NULL` rows; `scope=symbol` requires `instrument_id`. Default `all`. |
| POST | `/api/notes` | Create a note. Body: `{body, instrument_id?, linked_alert_id?, linked_news_id?, linked_social_post_id?}`. Server validates that at most one of `linked_news_id` / `linked_social_post_id` is set. If `instrument_id` is omitted, this is a **global** note; server runs FinBERT on `body` and persists `body_embedding`. |
| GET | `/api/instrument/:symbol/related_notes?cosine_min=0.55` | Returns global notes whose `body_embedding` has cosine ≥ threshold with `instrument.profile_embedding`. Powers the "Related market notes" panel on the drill-down Notes tab. |
| GET | `/api/earnings?window=14d` | Upcoming earnings for watchlist |
| GET/PATCH | `/api/settings` | Global thresholds, notifier creds, etc. |
| GET | `/api/usage?since=...&until=...&group_by=source\|day\|month` | Aggregated API spend over a window. Response: `{since, until, total_usd, by_source: [{source, units, cost_usd}], series?: [{bucket, source, units, cost_usd}]}`. Powers the §11 sticky-header Usage dropdown and the Settings Usage detail panel. Default window: current calendar month MTD in the user's TZ. `series` is included only when `group_by ∈ {day, month}`. |
| GET | `/api/health` | Feed connectivity, last tick age, queue depth |

### 7.2 WebSocket channels (Flask-SocketIO)

- `tick:<symbol>` — per-symbol bid/ask/last/volume push.
- `alerts` — broadcast new alerts so the UI flashes immediately.
- `news` — newly-scored items once they pass the persistence threshold (`relevance ≥ 0.5`). Carries a **union of Massive news + X posts**; payload includes a `kind ∈ {'news','x'}` discriminator. Matches the REST item shape so the frontend can render directly without a refetch. The grid mini-stack and the global news rail both subscribe.

### 7.3 Scheduler jobs

Every job writes a row to the `job_run` table on each invocation (`status='running'` at start, updated to `'ok'` or `'error'` on completion). This is the single source of truth for the "last updated at" badges described in §11 and the `/api/health` view in §14.

| Job | Cadence | Purpose |
|---|---|---|
| `quote_stream_supervisor` | continuous | Keeps Massive WS alive; reconnect w/ backoff |
| `tick_aggregator` | every 60s | Roll ticks → `bar_1m` |
| `threshold_evaluator` | every 5s | Walk recent ticks, evaluate alert rules |
| `massive_news_poll` | hourly (matches Massive's refresh cadence) | `GET /v2/reference/news?ticker=<X>` for each active watch instrument. Dedupe against `news.massive_id`. Run regex ticker extraction + cosine-relevance + FinBERT sentiment on new rows (§10.2). Persist to `news`; broadcast on the `news` WS channel; evaluate news alert ladder (§8). |
| `x_account_poll` | every 1 min | For each active `social_account_watch`: `GET /2/users/:external_id/tweets?since_id=:last_post_id`. Per-post-read billing — empty polls are free. Persist new tweets to `social_post`; run ticker extract + cosine-relevance + FinBERT sentiment (§10.3); broadcast on `news` WS channel with `kind='x'`; evaluate news alert ladder. |
| `earnings_sync` | daily 02:00 | Pull 14d window from Finnhub |
| `factor_refresh` | EOD (16:30 ET) | Pull daily bars for each bucket representative; refit OLS per (watch, bucket) on the rolling window; persist `factor_exposure`. |
| `factor_pca` | on startup (if any bucket has no representative or it's been ≥90 days since last PCA) + quarterly | Run PCA on each bucket's candidate basket using ~6mo of daily returns from Massive REST; pick the ETF with the highest \|PC1 loading\| as the representative; persist `factor_bucket.representative_id` + `pc1_var_explained`. Required for any subsequent regression. |
| `residual_intraday` | every 60s during session | Recompute today's `last_residual` per (watch, bucket) using latest live prices. |
| `meta_refresh` | weekly (Sun 03:00) | Refresh `instrument.meta_json` via Massive ticker reference + Finnhub `/stock/profile2`. Cheap; no LLM. If sector/industry/country/description **changed materially**, also enqueues an immediate `profile_text_refresh` for that symbol rather than waiting for the next monthly tick. |
| `profile_text_refresh` | monthly (1st Sun 03:30, per symbol) | (1) Call Haiku to regenerate `instrument.profile_text` with the current `meta_json` slow-fields (see §3.3 prompt); (2) FinBERT-embed `profile_text`; (3) L2-normalize and persist to `instrument.profile_embedding`. Also called on-demand at `POST /api/watchlist` and on the user's "Regenerate profile" click in Settings. Skipped for any symbol whose `profile_text` was regenerated in the last 7 days. |
| `pushover_ack_poll` | every 30s while any unacked priority=2 alert exists | Poll `https://api.pushover.net/1/receipts/{receipt}.json` for each emergency-priority alert; record `alert.acked_at` and stop polling that receipt once acked. Idle when there are no open emergencies. |
| `quiet_digest_send` | daily at 08:00 ET (configurable) | Query `alert` for `quiet_queued=1 AND digested_at IS NULL`. Group by severity (critical/high/warn) and `kind`. Build one Pushover message in the §12 digest format and send via the `info` category (📰 icon, priority=0). Set `digested_at=now()` and `notified_via='digest'` for each row. Skip entirely if the queue is empty. |
| `liquidity_refresh` | EOD (16:35 ET, after close) | For each active watch's instrument: roll the trailing 21 daily bars → write `liquidity_daily` row (`adv_shares_21d`, `adv_dollar_21d`, `spread_avg_bps`, `pct_zero_volume`, `computed_at`). Same job populates rep ETFs of active buckets so the §11.C grid liquidity-rank can include them. |
| `archive_ticks` | nightly | Move ticks > 30d to Parquet, vacuum |

---

## 8. Alert rules (v1, all configurable globally + per-watch)

A rule fires only when the move is **adverse to thesis**. Defaults:

**Severity levels (4-tier)** — used by every alert type so quiet-hours rules (§12) apply uniformly:

| Severity | Pushover priority | What it means |
|---|---|---|
| `info` | -1 (silent) | One-shot reminder; never wakes you. |
| `warn` | 0 (default sound) | Pays attention required, not urgent. Queued during quiet hours. |
| `high` | 1 (bypasses DND, always sounds) | Real signal but not a life-or-death page. Queued during quiet hours. |
| `critical` | 2 (emergency, repeats until acked) | Always pages, work hours or not. The "wake me up" tier. |

**Price / volume / spread rules**

| Rule (`kind`) | Threshold | Severity |
|---|---|---|
| Price jump (`px_jump`) | \|Δ\| ≥ 3% / 5m | `warn`; ≥5%/5m → `high`; ≥7%/5m → `critical` |
| Bid-ask spread (`spread`) | spread_bps > 50 sustained 30s | `warn`; >100 → `high`; >150 → `critical` |
| Volume z-score (`volume`) | 5m window > 3σ above 20d intraday-mean for that minute-of-day | `warn`; >4σ → `high`; >5σ → `critical` |
| Combined (`combined`) | px_jump ∧ volume z>3 ∧ adverse | **`critical`** (the headline deleveraging signal) |
| Pre-earnings (`earnings`) | Earnings within 24h | `info` (one-shot, not paging) |

**News rules (`kind='news'`)** — severity ladder driven by relevance × \|sentiment\| × ticker-match strength. **Only `critical` news pages outside work hours**, so the high bar matters.

| Threshold | Severity |
|---|---|
| relevance ≥ 0.95 ∧ \|sent\| ≥ 0.8 ∧ **explicit ticker match for a watched symbol** ∧ adverse | **`critical`** ("AAPL guides down at 8 PM ET"-class events; rare) |
| relevance ≥ 0.85 ∧ \|sent\| ≥ 0.7 ∧ adverse | `high` |
| relevance ≥ 0.7 ∧ \|sent\| ≥ 0.5 ∧ adverse | `warn` |
| relevance ≥ 0.5 | `info` (UI-only; never pushes during quiet hours) |

The strict `critical` news threshold is deliberate — outside work hours this is the only news that pages, so it has to be genuinely worth waking up for. Direct ticker match (not just semantic match via profile cosine) is required because that's the strongest signal that a specific watched position is moving on company-specific news.

**X curated-post rules (`kind='social_x'`)** — all curated X accounts are treated **uniformly**; the curation list itself is the credibility filter (the user has pre-vetted who they follow, so we don't tier by account type). Severity comes purely from the same relevance × \|sentiment\| × ticker-match math as news. FinBERT is run on tweet text per §10.3 with the quality caveat from §3.3.

| Threshold | Severity |
|---|---|
| relevance ≥ 0.95 ∧ \|sent\| ≥ 0.8 ∧ **explicit ticker match for a watched symbol** ∧ adverse | **`critical`** (e.g., @SecTreasury announcing tariffs on a watched name; rare) |
| relevance ≥ 0.85 ∧ \|sent\| ≥ 0.7 ∧ adverse | `high` |
| relevance ≥ 0.7 ∧ \|sent\| ≥ 0.5 ∧ adverse | `warn` |
| relevance ≥ 0.5 | `info` (UI-only) |

Deduplication: at most one alert of a given `(symbol, kind)` per 15 minutes; new alert allowed if severity escalates.

---

## 9. Correlated / factor / thematic view

Each **bucket** is a *concept* (an index): "Momentum", "Information Technology sector", "S&P 500 broad market", "AI thematic". Each bucket has a **candidate basket** of all reasonable ETFs that track it. The **representative** — the one ETF we regress each watch against — is picked by **PCA over the candidate basket from day one** (see §3.4). No hand-picked reps anywhere.

For each watched symbol × each bucket representative, we run an OLS regression and only **surface relationships that survive multiple-testing correction** (BH-FDR at q=0.05; see "Significance filter" below). That filter is critical — with ~80 buckets, a naive `p < 0.05` would surface ~4 false positives per watch on average.

### v1 bucket universe (80 buckets, all PCA-selected)

Raw index tickers like `^GSPC` are on Massive's separate Indices product and not used here — every bucket is tracked via a tradeable ETF in our Stocks Advanced subscription.

**Broad equity indices (5)**

| Bucket | Candidate basket |
|---|---|
| S&P 500 | SPY, IVV, VOO |
| Nasdaq-100 | QQQ, QQQM |
| Russell 2000 / small-cap | IWM, IJR, VB, VTWO |
| Mid-cap | IJH, MDY, VO |
| Equal-weight S&P | RSP, EQAL |

**Volatility regime (1)**

| Bucket | Candidate basket |
|---|---|
| VIX | VIXY, VXX, UVXY |

**Rates curve (5)**

| Bucket | Candidate basket |
|---|---|
| Short rates (front end) | SHV, BIL |
| 7–10Y rates (belly) | IEF, VGIT |
| 20+Y rates (long end) | TLT, VGLT, EDV |
| TIPS / inflation-linked | TIP, SCHP, VTIP |
| Mortgage-backed | MBB, VMBS |

**Credit (4)**

| Bucket | Candidate basket |
|---|---|
| High Yield | HYG, JNK |
| Investment Grade | LQD, VCIT |
| EM Debt (USD) | EMB, PCY |
| Bank Loans / Floating Rate | BKLN, SRLN |

**FX (4)**

| Bucket | Candidate basket |
|---|---|
| Dollar (DXY) | UUP, USDU |
| Yen | FXY |
| Euro | FXE |
| Yuan | CYB |

**Style factors (7)**

| Bucket | Candidate basket |
|---|---|
| Value | VLUE, IWD, IUSV, VTV |
| Momentum | MTUM, VFMO, IMTM, JMOM, PDP, FDMO |
| Quality | QUAL, SPHQ, JQUA |
| Low Vol | USMV, SPLV, EFAV |
| Growth | IWF, IUSG, VUG |
| Dividend / High-income | VYM, SCHD, DVY, NOBL |
| High Beta | SPHB |

**GICS sectors (11 — full set)**

| Bucket | Candidate basket |
|---|---|
| Info Tech | XLK, VGT, FTEC |
| Comm Services | XLC, VOX |
| Cons Discretionary | XLY, VCR, IYC |
| Cons Staples | XLP, VDC, IYK |
| Financials | XLF, VFH, IYF |
| Healthcare | XLV, VHT, IYH |
| Industrials | XLI, VIS, IYJ |
| Energy | XLE, VDE, IYE, FENY |
| Materials | XLB, VAW, IYM |
| Real Estate | XLRE, VNQ, IYR |
| Utilities | XLU, VPU, IDU |

**Sub-sectors / industry slices (6)**

| Bucket | Candidate basket |
|---|---|
| Banks (broad) | KBE, KBWB |
| Regional banks | KRE |
| Homebuilders | XHB, ITB |
| Transports | IYT |
| Pharma | PJP, IHE |
| Retail | XRT |

**International equities (6)**

| Bucket | Candidate basket |
|---|---|
| Developed ex-US | EFA, VEA, IEFA |
| Emerging markets | EEM, VWO, IEMG |
| Europe | VGK, EZU, FEZ |
| Japan | EWJ, DXJ |
| China (broad) | MCHI, FXI |
| China tech | KWEB, CQQQ |

**Commodities (7)**

| Bucket | Candidate basket |
|---|---|
| Broad commodities | DBC, GSG, PDBC |
| Oil | USO, BNO, DBO |
| Natural gas | UNG, BOIL |
| Gold | GLD, IAU, GLDM, SGOL |
| Silver | SLV, SIVR |
| Industrial metals / Copper | DBB, CPER |
| Agriculture | DBA, MOO |

**Thematics — tech-adjacent (7)**

| Bucket | Candidate basket |
|---|---|
| Semis | SOXX, SMH, XSD, PSI |
| AI | BOTZ, IRBO, ARTY, AIQ, ROBT, CHAT, THNQ, WTAI, … *(100+)* |
| Cloud/Software | IGV, WCLD, CLOU, SKYY |
| Cyber | HACK, CIBR, BUG |
| Fintech | FINX, ARKF |
| 5G / next-gen telecom | FIVG, NXTG |
| Quantum | QTUM |

**Thematics — energy & clean (5)**

| Bucket | Candidate basket |
|---|---|
| Clean energy (broad) | ICLN, QCLN, PBW |
| Solar | TAN |
| Wind | FAN |
| Uranium / Nuclear | URA, URNM, NLR |
| Lithium / EV batteries | LIT |

**Thematics — biology / health (3)**

| Bucket | Candidate basket |
|---|---|
| Biotech | IBB, XBI, BBH, FBT |
| Genomics | ARKG, IDNA |
| Medical devices | IHI |

**Thematics — defense / space (2)**

| Bucket | Candidate basket |
|---|---|
| Defense | ITA, XAR, PPA |
| Space | ARKX, UFO |

**Thematics — consumer / lifestyle (4)**

| Bucket | Candidate basket |
|---|---|
| Travel / leisure | JETS, PEJ, AWAY |
| Gaming / esports | HERO, ESPO, NERD |
| Sports betting | BETZ |
| Cannabis | MSOS, MJ |

**Thematics — crypto / digital (3)**

| Bucket | Candidate basket |
|---|---|
| Bitcoin | IBIT, FBTC, BTCO, BITB, ARKB |
| Ethereum | ETHA, FETH |
| Blockchain / crypto-adjacent | WGMI, BKCH, BLOK |

**Total: 80 buckets, all with PCA-selected representatives.** Total daily Massive REST cost: ~80 ETFs × 1 daily bar = 80 calls/day for representatives + N × 6mo bars on each `factor_pca` run (quarterly). Trivial.

### Significance filter — BH-FDR at q=0.05

With 80 buckets, a naive `p < 0.05` would expose ~4 false-positive bucket exposures per watch on average. We use **Benjamini–Hochberg False Discovery Rate** with `q=0.05`:

1. Run all 80 single-factor OLS regressions for the watch.
2. Sort the resulting p-values ascending: `p_(1) ≤ p_(2) ≤ … ≤ p_(80)`.
3. Find the largest `k` such that `p_(k) ≤ (k / 80) · 0.05`.
4. Mark the first `k` rows `significant=1`; persist `q_value`. The Context tab filters on `significant=1`.

Bounds the expected proportion of false positives in the surfaced set to 5%. Strictly less conservative than Bonferroni but tight enough to keep UI noise low. Schema: `factor_exposure.q_value` + `factor_exposure.significant` (see §6).

### Live computation (regression per watched symbol)

For each `(watched_symbol, representative_etf)` pair, daily OLS on a rolling window (default 90d, configurable 30/90/250):

```
r_symbol_t = α + β · r_rep_t + ε_t
```

We store, per pair:
- `beta` (β) — exposure of the watched stock to the factor.
- `intercept` (α) — usually near zero; kept for completeness.
- `r_squared` — explanatory power.
- `p_value` — p-value of β under H₀: β = 0.
- `correlation` — Pearson ρ on the same window (equivalent ranking signal to β, easier to reason about).
- `last_residual` — today's idiosyncratic move (definition below).
- `window_days`, `computed_at`.

### Residual (the bit we actually want to see)

For today's session:
- `expected_return = α + β · r_rep_today`
- `residual = r_symbol_today − expected_return`

The residual is the part of today's move that the factor does **not** explain. Large adverse residuals are the cleanest idiosyncratic deleveraging signal — they mean "the stock is moving against you for reasons that aren't 'the whole sector is moving.'"

### Drill-down display (Context tab — see §11.C)

For the selected watched symbol, show only `(symbol, rep)` pairs that **passed BH-FDR (`significant = 1`)**, sorted by descending `|β|` (or `|ρ|`):

| Bucket | Rep | β | ρ | R² | p | Today: rep return | Expected | Actual | Residual |
|---|---|---|---|---|---|---|---|---|---|
| Semis | SOXX | 1.42 | 0.81 | 0.66 | <0.001 | −2.1% | −2.98% | −0.8% | **+2.18%** |
| Momentum | MTUM | 0.83 | 0.62 | 0.39 | 0.003 | −1.2% | −1.00% | −0.8% | +0.20% |
| AI | BOTZ | 0.61 | 0.44 | 0.20 | 0.018 | −1.8% | −1.10% | −0.8% | +0.30% |

Sign convention: residual is colored red if **adverse to thesis direction**, green if aligned. The big visible adverse-residual cells are the things to investigate.

### Factor-level deleveraging alerts (Phase 5 — ON by default)

Beyond the per-symbol price/volume/spread rules (§8), bucket-level moves fire alerts via the same engine:

- For each bucket representative, the `bucket_alerts` job (60s cadence) computes today's intraday z-score vs the trailing 60d daily return distribution (`server/analytics/bucket_zscore.py`).
- For each watched symbol with `factor_exposure.significant=1` against that bucket: if `sign(β) · sign(bucket_return) · sign(thesis) < 0` (the bucket move is adverse to the position via that exposure) AND `|z_bucket| ≥ threshold`, fire through `engine.fire()`.
- Severity tiers (configurable in Settings under `bucket_alerts`):
  - `|z| ≥ 3` → `warn`
  - `|z| ≥ 4` → `high`
  - `|z| ≥ 5` → `critical`
- The alert `kind` is namespaced as `factor:<bucket_label>` so the engine's per-(symbol, kind) 15-minute dedup naturally separates simultaneous alerts on different buckets affecting the same watch.

**Gating.** `setting('global').bucket_alerts.enabled` defaults to **true** (Phase 5 user choice). Setting it to `false` short-circuits the job — no rows written, no broadcast, no Pushover. Recommended workflow if alert volume is too noisy in the first week: flip to `false` in Settings, raise `z_warn` to 3.5 or 4, flip back on.

### Refresh cadence

- **`factor_pca`** — startup + quarterly. Runs PCA over each bucket's candidate basket; updates `factor_bucket.representative_id` + `pc1_var_explained`.
- **`factor_refresh`** — EOD (16:30 ET). Refits OLS for every (watch, bucket) on the rolling window; rewrites `factor_exposure` with new β / p / q / significant.
- **`residual_intraday`** — every 60s during session. Updates only `factor_exposure.last_residual` using the latest live representative-ETF prices.

Schema for all three tables (`factor_bucket`, `factor_bucket_candidate`, `factor_exposure`) lives in §6.

---

## 10. News + social pipeline

The pipeline has **three flows**, all sharing one cached artifact — `instrument.profile_embedding` from §10.1 — that every downstream cosine-relevance pass reads:

- **§10.1 Profile setup** — runs **once per stock** (watchlist-add or monthly refresh). Produces the per-stock `profile_text` + `profile_embedding`.
- **§10.2 Massive news ingestion** — runs **hourly** (matching Massive's refresh cadence). Pulls `/v2/reference/news?ticker=<X>` per active watch, dedupes against `news.massive_id`, scores with FinBERT + relevance, persists to `news`, broadcasts on the `news` WS channel.
- **§10.3 X curated-account ingestion** — runs **every 1 minute**. For each `social_account_watch` row, polls `/2/users/:id/tweets?since_id=...`. Per-post-read billing keeps polling cheap; only new tweets cost money. Scored by FinBERT and emitted on the same `news` WS channel (`kind='x'`).

What got removed when Brave was dropped: the per-symbol Brave queries (replaced by Massive's bundled news endpoint), the Haiku-driven macro-query generator (replaced by curated X government/journalist accounts), and the `setting('macro_queries')` row.

### 10.1 Profile setup pipeline — once per stock

Triggered by: `POST /api/watchlist` (when a symbol is first added), the **monthly** `profile_text_refresh` scheduler job, a material-change trigger from `meta_refresh` (when sector/industry/country/description shifts), or a manual "Regenerate profile" click in Settings.

```
[ Trigger: watchlist-add  OR  profile_text_refresh (monthly)  OR  material-change from meta_refresh  OR  manual ]
       │
       ▼
[ Massive /v3/reference/tickers/{symbol} ]
       │  Confirm tradeable, get exchange + SIC (fallback fields).
       ▼
[ Finnhub /stock/profile2?symbol={symbol} ]
       │  Get sector, industry, country, description, logo, IPO date.
       │  (market_cap_m is also returned but NOT used in profile generation —
       │  it's volatile.)
       ▼
[ Persist meta to instrument.meta_json + instrument.meta_refreshed_at ]
       │
       ▼
[ Build Haiku prompt — time-invariant inputs ONLY ]
       │  Used:        symbol, display_name, sector, industry, country, description
       │  Excluded:    market cap, recent prices, recent events, current executives,
       │               anything that changes day-to-day
       │  Full prompt template lives in §3.3 / server/nlp/profile_text.py
       ▼
[ Claude Haiku 4.5  (temperature=0, max_tokens≈400) ]
       │  Output: 4–6 sentence economic-exposure paragraph.
       │  Vocabulary-rich in macro/regulatory/factor/geopolitical terms
       │  (e.g., "interest rates", "Fed policy", "tariffs", "antitrust",
       │  "supply chain", "forex", "OPEC", "EU regulation", ...).
       │  Cost: ~$0.005/call. Deterministic at temperature=0.
       │  Fallback: if API unreachable, embed the Finnhub description directly
       │  and set meta.profile_pending=true; retry job re-runs Haiku later.
       ▼
[ Persist Haiku output to instrument.profile_text ]
       │  Audit + edit target. Settings (§11.E) exposes inline editor and
       │  "Regenerate via Haiku" button.
       ▼
[ FinBERT forward pass on profile_text ]
       │  Mean-pool last hidden state across non-padding tokens → 768-dim float32.
       │  L2-normalize so later cosine reduces to a dot product.
       ▼
[ Persist to instrument.profile_embedding (BLOB ~3KB) ]
       │
       ▼
[ Ready — every subsequent headline can cosine against this vector ]
```

**Total wall-clock at watchlist-add: ~1–2s** (one Massive call + one Finnhub call + one Haiku call + one FinBERT forward).

### 10.2 Massive news ingestion — hourly per watch

Triggered by the `massive_news_poll` scheduler job (§7.3) every hour. For each active watch instrument, fetch new headlines from Massive's bundled news endpoint, dedupe, score, and persist.

```
[ For each active watch instrument: ]
       │
       ▼
[ GET https://api.polygon.io/v2/reference/news ]
       │  ?ticker={symbol}&order=desc&limit=50
       │  Massive returns: id, title, description, article_url,
       │  published_utc, publisher{}, tickers[], keywords[], insights[]
       │  Cost: $0 incremental — included in Stocks Advanced.
       ▼
[ Dedupe against news.massive_id ]
       │  Drop rows already ingested (poll overlap is normal).
       ▼
[ Ticker extraction ]
       │  tickers_final = massive_tickers[] ∪ regex_extracted_from(title+description)
       │  Regex pass catches tickers Massive didn't tag (rare but real, e.g.,
       │  related names in the body that aren't in Massive's tickers[]).
       ▼
[ Rule-based relevance ]
       │  1.0 if any active-watch symbol in tickers_final  →  source='symbol'
       │  0.7 if title/description matches a watch's sector or industry keyword
       │                                                    →  source='sector'
       │  0.0 otherwise (the semantic pass may rescue)
       ▼
[ Early-exit ]
       │  If rule_score == 0 AND no watch's sector/industry keyword matched
       │  AND no watch's ticker is in tickers_final → drop. Cheap path for
       │  headlines about unrelated tickers Massive returned in batch.
       ▼
[ FinBERT forward pass (one per surviving headline) ]
       │  Input: title + description (snippet).
       │  Output: (p_pos, p_neg, p_neu) softmax + mean-pooled 768-dim embedding.
       ▼
[ Semantic relevance pass ]
       │  For each active watch: cosine(headline_emb, profile_emb).
       │  relevance_final = max(rule_score, 0.85 * cosine_sim)
       │  If semantic > rule_score, relevance_source='semantic'
       ▼
[ Sentiment scalar ]
       │  sentiment = p_positive − p_negative ∈ [−1, 1]
       │  sentiment_label = argmax class; sentiment_conf = max softmax prob
       │  Massive's own insights[].sentiment is saved verbatim into
       │  news.massive_insights (raw JSON) as a cross-check, NOT as the
       │  alert source of truth.
       ▼
[ Persist to news; push on WS `news` channel with kind='news' ]
       │
       ▼
[ Alert if relevance/sentiment crosses any §8 news-rule threshold ]
```

**Latency note.** Massive's news endpoint refreshes hourly. So an "AAPL guides down at 4:01 PM ET" headline may not appear in our `news` table until ~5:00 PM. The price/volume/spread WS alerts are real-time, so the *signal* hits you within seconds — the news layer is *explanation*, not detection. For breaking macro/policy news during the trading day, the §10.3 X feed at 1-min cadence is the real-time path.

### 10.3 X curated-account ingestion — every 1 minute

Triggered by `x_account_poll` (§7.3). The X API bills per post returned, not per call, so polling every 1 min costs the same as every 15 min — except the latency improves from 15 min to <1 min on a quiet-but-real story (Trump tariff announcement, Fed Powell tweet during a press conference, journalist breaking-news tweet).

```
[ For each active social_account_watch: ]
       │
       ▼
[ GET https://api.twitter.com/2/users/:external_id/tweets ]
       │  ?since_id={last_post_id}&max_results=10&tweet.fields=created_at
       │  Empty response = $0. Non-empty = $0.005 per post returned.
       │  One-time User: Read at row-insert time resolves @handle → external_id ($0.01 once).
       ▼
[ Persist new tweets to social_post ]
       │  external_post_id = tweet.id; body = tweet.text; posted_at = created_at.
       │  Update social_account_watch.last_post_id = max(tweet.id).
       ▼
[ Ticker extraction (same regex as §10.2) ]
       │
       ▼
[ Rule-based relevance against active-watch keywords (same logic as §10.2) ]
       │  1.0 explicit ticker match; 0.7 sector/industry match; 0.0 otherwise.
       ▼
[ Early-exit if rule_score == 0 AND no sector/industry keyword matched ]
       │  Drops most tweets — curated accounts post a lot of non-market content.
       ▼
[ FinBERT forward pass on tweet body ]
       │  Same model, same call. Quality caveat per §3.3: FinBERT was trained
       │  on Reuters-style headlines, not tweets. Adequate on journalist /
       │  government / central-bank prose; noisier on casual tweets.
       ▼
[ Semantic relevance pass (cosine vs each watch's profile_embedding) ]
       │  Same hybrid formula: relevance_final = max(rule_score, 0.85 * cosine).
       ▼
[ Sentiment scalar (same derivation as §10.2) ]
       │
       ▼
[ Persist to social_post; push on WS `news` channel with kind='x' ]
       │
       ▼
[ Alert if any §8 social_x threshold crosses ]
```

**Latency profile.** With a 1-min poll cadence and per-post billing, a tweet from @SecTreasury or @realDonaldTrump that mentions a watched name typically clears the full pipeline (ingest → FinBERT → cosine → alert) in **30–90 seconds** from posting. That's the real-time path the §10.2 hourly Massive feed can't match.

**Truth Social coverage.** No direct API. Trump's Truth posts are reliably cross-posted to his X account (@realDonaldTrump) within minutes by his own team. Including @realDonaldTrump in the default `social_watch.yaml` seed gives us ~95% Truth coverage transitively at no extra plumbing.

### 10.4 Operational notes

**Profile-setup cost** (§10.1): ~20 watches × 1 Haiku refresh/month × ~$0.005/call ≈ **$0.10/month**.

**Massive news cost** (§10.2): **$0 incremental** — included in Stocks Advanced. Volume is ~500–2,000 headlines/day across 20 watches. FinBERT CPU: ~50–200ms/headline → trivial.

**X cost** (§10.3): per-post-read billing at $0.005/post returned. With ~15 curated accounts collectively producing 30–200 posts/day, expect **$10–30/month**. One-time User: Read ($0.01 each) on watchlist-add only.

**Real-spend tracking.** Every billable adapter call writes an `api_cost_event` row (§6) — one per X tweet returned, one per X User: Read, one per Haiku profile_text call. The Usage dropdown in the sticky header (§11) reads `/api/usage` (§7.1), which is a `SUM(cost_usd) GROUP BY source` over `api_cost_event`. This means the numbers shown in the UI are the **actual** vendor-billable spend recorded at call time — not estimates extrapolated from a fixed rate card. If X changes per-post pricing mid-month, history stays accurate (we persisted `unit_cost_usd` per row) and only new events use the new rate.

**`social_watch.yaml` seed format.** Lives at `server/db/seeds/social_watch.yaml`. Loaded on first startup if `social_account_watch` is empty; thereafter the DB is the source of truth and Settings (§11.E) is the edit surface. The user-facing shape:

```yaml
# server/db/seeds/social_watch.yaml
x_accounts:
  # US executive + economic
  - {handle: realDonaldTrump,     label: "Trump"}
  - {handle: POTUS,               label: "President of the United States"}
  - {handle: WhiteHouse,          label: "White House"}
  - {handle: SecTreasury,         label: "US Treasury Secretary"}
  # Central banks
  - {handle: federalreserve,      label: "Federal Reserve"}
  - {handle: ECB,                 label: "European Central Bank"}
  - {handle: bankofengland,       label: "Bank of England"}
  - {handle: bankofjapan,         label: "Bank of Japan"}
  # Regulators
  - {handle: SECGov,              label: "SEC"}
  - {handle: TheJusticeDept,      label: "DOJ"}
  - {handle: FTC,                 label: "FTC"}
  # Top financial journalists
  - {handle: DeItaone,            label: "Walter Bloomberg (DeItaone)"}
  - {handle: Carl_Quintanilla,    label: "Carl Quintanilla, CNBC"}
  - {handle: LisaAbramowicz1,     label: "Lisa Abramowicz, Bloomberg"}
  - {handle: zerohedge,           label: "ZeroHedge"}
```

Rules:
- `handle` is stored *without* the leading `@`.
- The list is an array of `{handle, label}`. `label` is the human-friendly display string shown in Settings and in alert payloads; it can be edited without affecting the underlying account.
- The loader inserts one `social_account_watch` row per entry. On startup, missing handles are inserted; existing handles are left alone (so user edits in Settings survive a restart).
- The loader resolves `external_id` (numeric X user_id) at insertion time via one User: Read per handle (~$0.01 each, one-shot per account ever added).

**FinBERT model management**: download on first run via `transformers.AutoModel.from_pretrained(...)`; cache under `~/.cache/huggingface/`. Pin the model revision in `requirements.txt` so we don't get silently upgraded.

**Optional rationale add-back** (not in v1): if interpretability becomes a problem later, call Claude Haiku **only** on items that already passed the alert threshold to generate a one-sentence "why this matters" string. ~5–20 calls/day, pennies/month.

**Failure modes**:
- Anthropic API unreachable at watchlist-add → §10.1 falls back to embedding raw Finnhub description; sets `meta.profile_pending=true`; retry job re-runs Haiku when API is back.
- Massive news endpoint errors → `massive_news_poll` logs `status='error'` in `job_run`; UI surfaces staleness via §11 "Last updated" indicators.
- X API rate-limit / 429 → `x_account_poll` backs off exponentially; logs to `job_run`; UI shows the X feed as stale.
- FinBERT model corrupted → process refuses to start; surfaced in `/api/health`.

---

## 11. Frontend (React + Vite + TypeScript)

### Libraries
- **Recharts** or **lightweight-charts** (TradingView OSS) for price charts. `lightweight-charts` is way better for OHLC; use it for drill-down. Recharts is fine for sparklines on the grid view.
- **TanStack Query** for REST caching.
- **socket.io-client** for live ticks/alerts/news.
- **shadcn/ui** + Tailwind for components.
- **zustand** for global UI state (selected symbol, time window).

### Visual style

Think **Bloomberg Terminal re-skinned by Linear / Vercel** — information-dense and serious, but sleek and modern. Not a retro CRT pastiche.

- **Dark theme by default.** Near-black background (`zinc-950` / `#0a0a0a`), one step lighter for cards (`zinc-900`), borders at `zinc-800`. Light mode is a nice-to-have, not a v1 requirement.
- **Typography.** A single **geometric sans** for everything UI (Inter, or Geist Sans) and a **tabular monospace** for every number, ticker, and timestamp (JetBrains Mono, IBM Plex Mono, or Geist Mono). Tabular numerals (`font-variant-numeric: tabular-nums`) are non-negotiable so columns of prices align. **No serif body fonts, no decorative or display faces, no Comic Sans, no Papyrus, no Times New Roman** — if it would look out of place in Linear or a trading desk, it doesn't ship.
- **Color is signal, not decoration.** Reserve red/green strictly for adverse/aligned moves and sentiment polarity; reserve amber/red intensity for `warn` / `high` / `critical` severity. Everything else stays neutral grayscale so the eye latches onto the meaningful color instantly. Avoid gradients, glows, and saturated brand colors in chrome.
- **Density.** Compact spacing (Tailwind `text-sm` / `text-xs` for tables, `space-y-1` between rows). The grid should fit 12+ watch cards on a 1440p screen without scrolling. No oversized hero sections, no marketing whitespace.
- **Motion.** Subtle and functional only — new headlines slide in at the top of the feed with a brief highlight; alerts get a one-frame flash on arrival; sparklines transition smoothly. No bounces, no parallax, no decorative animation.
- **Iconography.** Lucide (already shipped with shadcn) at small sizes, never as visual weight on its own. Direction badges use 🐂/🐻 emoji (already specified) because they're glanceable; that is the only place emoji belong in the chrome.
- **Borders over shadows.** Hairline 1px borders separate panels. Drop shadows are reserved for popovers and modals, never on resting cards.

The test: a screenshot of the dashboard should look like it belongs next to a Bloomberg / Linear / Vercel screenshot, not next to a fintech landing page or a crypto dashboard.

### Views

**A) Watchlist Grid (default route `/`)**
- Sticky header: market session, last alert, feed health, Pushover status, **API usage chip** (`$12.40 MTD ▾` — opens the Usage dropdown described below).
- One card per watch: symbol, direction badge (🐂/🐻), last px, %Δ-from-open, mini sparkline, spread bps, volume z, an "adverse" red dot if any rule is hot, and a stack of the 3 most recent **relevance ≥ 0.5** news headlines for that symbol (each row: small sentiment dot, title, source · "5 min ago"). **Each title is a hyperlink to the source URL, opens in a new tab.**
- Sort/filter: most adverse first by default.
- Click a card body → drill-down view (clicking a headline link does *not* open the drill-down; it opens the article).

**B) Global News + Social Feed — *both* a right-side rail on `/` *and* a dedicated route `/news`**

The rail (toggleable in §11.E) renders the top N most-recent items at the side of the grid; `/news` is the full-page view with the same data, more space, and richer filtering. Both share one component and one data source (`GET /api/news`, which returns a union of Massive news + X posts).
- Chronological feed across **all active watches**, not just one symbol. Each row:
  - **Source-kind chip** (`📰 NEWS` / `𝕏 POST`) so the user can tell at a glance which feed it came from.
  - **Title** (news) or **first line of body** (X) — hyperlinked → opens article/tweet in new tab. Favicon next to it.
  - Source name (publisher for news, X account label for X) · "12 min ago".
  - Sentiment chip (`+ positive`, `– negative`, `· neutral`) colored.
  - Relevance badge (e.g., `0.92`).
  - Ticker chips for every symbol extracted (`AAPL`, `NVDA`); clicking a chip filters the feed to that ticker.
  - "Save to notes" button → routes to `/api/notes/from-news/:id` for `kind='news'` rows (sets `linked_news_id`) or `/api/notes/from-social/:id` for `kind='x'` rows (sets `linked_social_post_id`). The composer pre-fills with the headline/tweet body + source URL either way.
- Filter chips at top: relevance threshold (default ≥0.5), sentiment polarity (**default "all"** — positive, negative, and neutral items are all shown; user opts in to narrow), **source kind** (`news` / `x` / `all`, default `all`), source/publisher allow-deny, ticker.
- Live-updated via the `news` Socket.IO channel — new items slide in at the top with a brief highlight, regardless of whether they came from §10.2 (Massive) or §10.3 (X).
- Default sort: posted_at DESC. Toggle: relevance DESC.
- This is the view to skim when *something just felt off* on the grid — see what's hitting the wire AND what's hitting X.

**C) Drill-down (`/instrument/:symbol`)**
Tabs:
1. **Tape** — candlestick chart (1m/5m/1h/1d), bid/ask overlay, volume histogram, vertical lines for alerts & news. **News markers on the chart are clickable** — popover shows the title + source link, opens article in new tab.
2. **Microstructure & Liquidity** — live bid/ask spread chart, top-of-book size, trades-per-minute. **Liquidity sub-panel** (sourced from `liquidity_daily`): 21-day ADV in shares and dollars, session-average spread (bps), `pct_zero_volume` flag for thin names, liquidity rank within the watchlist (1 = most liquid). If `watch.position_size` is set: shows estimated **days to exit at 10% ADV participation** and **cost to exit (bps)** using `spread × √(position / ADV)`. Inline position-size editor lets the user enter or update the held quantity; cost/days update live. Stamped with `liquidity_daily.computed_at` so staleness is obvious.
3. **Context** — BH-FDR-filtered factor exposure table (`significant=1` only), columns: bucket / representative / β / ρ / R² / p / q (BH-adjusted) / today's rep return / expected / actual / residual (see §9). Residuals colored red if adverse to thesis, green if aligned. Hover any bucket row to see the candidate basket, the PCA-chosen representative, and `pc1_var_explained` (how cohesive the bucket is). Toggle "Show all 80 buckets" to disable the significance filter.
4. **News & Social** — symbol-scoped feed (union of Massive news + X posts mentioning this symbol; same row format as the global feed in §11.B). Filters: relevance (default ≥0.5), sentiment polarity (**default "all"**), source kind (`news`/`x`/`all`, default `all`), source/publisher, date range. **Title/body is hyperlinked.** "Save to notes" routes to `/api/notes/from-news/:id` or `/api/notes/from-social/:id` based on the row's kind, attaching the row to a new `update_log` entry pinned to this symbol with either `linked_news_id` or `linked_social_post_id` set.
5. **Notes** — `update_log` viewer + composer (scoped to this symbol). Composer defaults to per-symbol scope (writes `instrument_id` set to this watch); toggle "Mark as market-wide instead" to write a global note. Pin a note to an alert/news item; news-linked notes render the original headline + source link inline. Below the per-symbol feed, a **"Related market notes" collapsed panel** lists global notes whose `body_embedding` has cosine ≥ 0.55 with this watch's `profile_embedding` — so a "Powell hawkish" global note appears on AMZN / NVDA / TLT drill-downs automatically.
6. **Earnings** — next event countdown, history of post-earnings move.

**D) Global Notes (`/notes`)**
- Chronological feed of all global notes (`instrument_id IS NULL`) from `update_log`.
- Composer defaults to global scope here. Quick-add input pinned to the top: "What mattered today?" — single keystroke (`g n` shortcut) opens it.
- Each row: timestamp · body · linked alert/news chip (if any) · "Surfaces on N watches" badge (count of active watches with cosine ≥ 0.55 to this note's embedding).
- Click "Surfaces on N watches" → tooltip listing the matching watches sorted by cosine.
- Useful for end-of-day journaling: write one "today's tape" note that auto-attaches to every relevant drill-down.

**E) Settings (`/settings`)**
- Global default thresholds.
- Pushover credentials: User Key + four App Tokens (critical, warn, news, info). "Send test notification" button per app.
- Factor bucket editor: edit the candidate basket per bucket; force a representative override; trigger a manual PCA rerun (v2).
- Data adapter selection (Massive only in v1; reserved for future adapters).
- News rail: enable/disable on grid view, default relevance threshold, source allow/denylist.
- Per-watch profile editor: view the Haiku-generated `profile_text`, edit it inline (re-embeds on save), or click "Regenerate via Haiku" to overwrite. Useful when Haiku misses an exposure category you know matters.
- Per-watch position size (`watch.position_size`): optional shares-held input; drives the exit-liquidity calc in §11.C. Global default participation rate (default 10%) controls "days to exit".
- **X curated-accounts editor** (`social_account_watch`): list view, columns `(handle · label · added · last_polled · active toggle · remove)`. Add row: enter handle (e.g., `realDonaldTrump`), optional label; on save, the server does the one-shot User: Read against the X API to validate and persist `external_id`. Bulk-import textbox accepts one handle per line for seeding. Defaults to the contents of `server/db/seeds/social_watch.yaml`.
- API credentials (all read-only fields sourced from `.env`, shown only to confirm presence/absence + a periodic health check):
  - `MASSIVE_API_KEY` — the core quote + news feed; required for the WS stream, REST aggregates, and `massive_news_poll`. (Legacy `POLYGON_API_KEY` accepted as an alias post-rebrand.)
  - `FINNHUB_API_KEY` — earnings calendar + `/stock/profile2`; required for `earnings_sync` and `meta_refresh`.
  - `ANTHROPIC_API_KEY` — used by `profile_text_refresh`.
  - `X_BEARER_TOKEN` — shows status (valid / expired / missing); required for `x_account_poll`.
- Quiet hours panel:
  - Enable quiet hours (default on).
  - **Work hours**: weekday start (default 09:00 ET) + weekday end (default 17:00 ET).
  - **Weekend handling**: toggle "weekends always quiet" (default on).
  - **Morning digest**: delivery time (default 08:00 ET) + "send empty digests?" (default off).
  - **Per-severity overrides**: 4 toggles (`info` / `warn` / `high` / `critical`) for "page during quiet hours" — defaults match the §12 table.
  - "Send a test digest now" button.

### Usage dropdown (sticky-header chip)

A chip in the sticky header on every route showing **`$<MTD total> MTD ▾`** — current calendar month-to-date API spend, refreshed every 30 seconds. Click → dropdown panel anchored to the chip:

```
─────────────────────────────────────────────────────
  Usage — May 1 → May 25, 2026 (MTD)
─────────────────────────────────────────────────────
  𝕏  X API                $12.40    2,480 posts read
  Massive News            $0.00     (included in $199 sub)
  Anthropic Haiku         $0.08     2 profile_text calls
─────────────────────────────────────────────────────
  Total MTD               $12.48

  Last 7 days             $3.20
  Today                   $0.41
─────────────────────────────────────────────────────
  [ View detailed usage → ]
```

- Data source: `GET /api/usage?group_by=source` (§7.1).
- Color coding: X cost row uses tabular monospace per §11 Visual style for column alignment.
- "View detailed usage" routes to `/settings#usage` (anchored to the Usage panel in §11.E below).

**Settings → Usage panel** (`/settings#usage`):
- Time-range selector: Today / Last 7 days / Last 30 days / Current month (default) / Last month / Custom date range.
- Per-source table: `(source, units, unit cost USD, total cost USD)` with sort and CSV export.
- Daily-spend bar chart (Recharts, stacked by source) — useful for spotting a runaway day (e.g., X spend spike on a Trump-tariff news cycle).
- All numbers are real — they're `SUM(cost_usd)` over `api_cost_event` rows, written by the adapters at call time. Not estimates.

### "Last updated at" indicators

Every fetched or computed value the user looks at must show its own freshness so nothing is silently stale. Sources are already in the schema (per-row timestamps) or in the new `job_run` table (per-job last run). Concretely:

| UI surface | What it shows | Source |
|---|---|---|
| Sticky header (all routes) | `Feed: live ●` / `Feed: stalled (12s) ●` | `MAX(tick.ts)` for active symbols via `/api/health` |
| Sticky header (all routes) | `Massive news: last run 42 min ago` | `job_run` latest `massive_news_poll` |
| Sticky header (all routes) | `X: last poll 12s ago` | `job_run` latest `x_account_poll` |
| Sticky header (all routes) | `$12.40 MTD ▾` (Usage dropdown chip) | `SUM(cost_usd)` over `api_cost_event` for current month |
| Sticky header (all routes) | `Factors refreshed at 16:31 ET` | `job_run` latest `factor_refresh` |
| Grid card | `$176.42 @ 14:32:09` under the price | `MAX(tick.ts)` for that symbol |
| Grid card news mini-stack | `12 min ago` per headline | `news.fetched_at` |
| Drill-down header | `Meta refreshed Mon 03:00 · Profile text regenerated 2026-05-01` | `instrument.meta_refreshed_at` + `job_run` latest `profile_text_refresh` for this symbol |
| Drill-down Tape tab | "Bars current to 14:32" | `MAX(bar_1m.ts)` |
| Drill-down Context tab | Per-row `computed 16:31 ET (90d window)` and `residual @ 14:32 ET` | `factor_exposure.computed_at` + `residual_intraday` last run |
| Drill-down Context tab | Bucket header: `Rep selected 2026-04-01 (PC1 explains 78%)` | `factor_bucket.selected_at`, `pc1_var_explained` |
| Drill-down Microstructure tab | `ADV computed 16:35 ET 2026-05-25` | `liquidity_daily.computed_at` for this instrument |
| News & Social tab / rail row | `posted 12 min ago` and `fetched 4 min ago` | `news.published_at` / `social_post.posted_at`, `*.fetched_at` |
| News rail / `/news` route | Top bar per source: `Massive 42m ago · X 12s ago` | latest `massive_news_poll` / `x_account_poll` in `job_run` |
| Earnings tab | `Calendar synced today 02:00 ET` | latest `earnings_sync` in `job_run` |
| Settings → Health subpanel | Full `job_run` table for every job: last run, status, error if any | `/api/health` (extended) |

**Rule of thumb for the UI**: any number on screen has either a) a live-streaming source (then show `… @ HH:MM:SS` updated tick-by-tick) or b) a periodic refresh (then show `last updated X min ago` next to the value, colored amber if stale beyond the expected cadence, red if very stale).

---

## 12. Notifications

Pushover is the sole notification channel. Wrapped behind a `Notifier` interface so swapping (e.g., to ntfy.sh) is possible later, but no second implementation ships in v1.

```python
class Notifier(Protocol):
    def send(self, *, category: AlertCategory, title: str, body: str,
             severity: Severity, url: str | None = None) -> NotifyResult: ...
```

### Multi-application setup (see §3.2)

`PushoverNotifier` holds a dict of `{category → app_token}` plus the shared User Key. `category` is one of `critical`, `warn`, `news`, `info`. The four Pushover applications are created once on `pushover.net` and their tokens go in `.env`:

```
PUSHOVER_USER_KEY=...
PUSHOVER_APP_TOKEN_CRITICAL=...
PUSHOVER_APP_TOKEN_WARN=...
PUSHOVER_APP_TOKEN_NEWS=...
PUSHOVER_APP_TOKEN_INFO=...
```

### Pushover priority mapping

| `severity` | Pushover `priority` | Behavior |
|---|---|---|
| `info` | -1 | Silent banner, no sound. |
| `warn` | 0 | Default sound, respects iOS Focus/DND. |
| `high` | 1 | Always sounds, bypasses the recipient's Pushover-side quiet hours (does NOT bypass iOS Critical Alerts permission). |
| `critical` | 2 (emergency) | Required `retry=60`, `expire=1800`. Repeats every 60s for up to 30 min until acked in the Pushover app. Requires Critical Alerts permission on iOS to bypass DND. |

### Per-message customization (see §3.2)

- **Title**: 1-line summary, e.g. `AMZN — Deleveraging vs 🐂 thesis`.
- **Body**: numeric details — Δ price, σ volume, spread bps, top news (≤1024 UTF-8 chars; emojis fine).
- **URL**: deep-link to `/instrument/<symbol>` on the dashboard — tapping it opens the live chart, so the notification stays text-only and the user gets the visual on the dashboard.

### Acknowledgement tracking

For `priority=2` sends, Pushover returns a `receipt` string. Store it in `alert.pushover_receipt`. A scheduler job polls `GET https://api.pushover.net/1/receipts/{receipt}.json` every 30s to record ack time → `alert.acked_at`. Once acked, retries stop automatically Pushover-side.

### Quiet hours

Defaults are tuned for a US-based trader who works the regular session but watches non-US equities active overnight (ADRs on European/Asian listings, international ETFs like EWJ/MCHI/EFA). Override in Settings (§11.E).

**Work hours (everything pages):** Mon–Fri **09:00–17:00 ET**.
**Quiet hours (only `critical` pages, everything else queues):** Mon–Fri 17:00–09:00 ET, and all day Saturday and Sunday.
**Morning digest:** every day at **08:00 ET**, covering whatever queued since the last digest. Skipped if the queue is empty.

| Severity | During work hours | During quiet hours |
|---|---|---|
| `critical` | Page (priority=2 emergency) | **Always pages.** Emergency priority bypasses DND if iOS Critical Alerts permission is granted. This is the wake-you-up tier — including overnight `kind='news'` events that hit the strict `critical` news threshold in §8 (rare, but the whole point of having it). |
| `high` | Page (priority=1) | **Queue → 08:00 digest.** |
| `warn` | Page (priority=0) | **Queue → 08:00 digest.** |
| `info` | Silent push (priority=-1) | **Drop entirely** (not even queued; UI-only). |

**Digest delivery** — one Pushover notification per morning at 08:00 ET, sent via the `info` category icon (📰) so it visually distinguishes from real-time alerts. Body format:

```
Title:  Overnight digest — 1 critical · 4 high · 7 warn · 12 news (info)
Body:
🚨 1 critical (paged at the time):
  • 02:14 ET — TLT spread 178bps, adverse to 🐂 thesis

🔔 4 high (queued):
  • 23:48 — ASML −3.8% on Amsterdam open
  • 03:22 — EWJ volume z=4.4 (adverse to 🐻)
  • 05:11 — MCHI gap down on Hong Kong session
  • 07:45 — BABA earnings beat reaction post-ADR

⚠️ 7 warn (queued):
  • ... (compact list)

📰 12 news (info-tier, UI only, summarized):
  • Fed officials signal "higher for longer" (-0.7)
  • EU launches probe into AAPL App Store (-0.5)
  • ... (tap to open)

URL: https://localhost:5000/news?since=2026-05-25T17:00:00
```

Pushover priority for the digest itself: **0** (normal sound). The point is to be there when you wake up at 08:00, not to wake you earlier.

**Edge cases handled by defaults:**
- **Overnight news bombshells on watched symbols** — captured by the strict `critical` news tier in §8 (relevance ≥ 0.95 ∧ \|sent\| ≥ 0.8 ∧ explicit watchlist ticker match). These do page through quiet hours.
- **Asia-session moves on ADRs (BABA, JD, TSM, ASML)** — flow as `warn` or `high` from the `kind='px_jump'`/`volume`/`spread` rules; queued to digest.
- **Pre-earnings (`info`) reminders fired overnight** — dropped during quiet hours; re-fire automatically the next session if still within 24h.
- **US holidays** — quiet hours treat them as weekend-style; the 08:00 ET digest still fires if non-empty (catch-up).
- **DST transitions** — APScheduler with `zoneinfo` handles this; quiet/work window adjusts automatically (don't double-fire or skip the digest the night of the jump).

**Per-watch overrides** (v2 only, not v1): a toggle on each watch to "page through quiet hours for this symbol" — useful for crypto-adjacent or actively-traded overnight positions.

### Rate / dedupe safety net

Pushover limits to 2 concurrent HTTP connections; the API client serializes sends. Local dedupe (§8: ≤1 alert per `(symbol, kind)` per 15 min unless severity escalates) also caps outbound traffic. Worst case: 20 symbols × 4 categories × 1 every 15 min = 320/hr, well inside Pushover's 10k/month quota.

---

## 13. Generalizing beyond stocks

The data adapter is the only thing that changes per asset class. Adapter contract:

```python
class DataAdapter(Protocol):
    def subscribe_quotes(self, symbols: list[str], on_tick) -> None: ...
    def get_bars(self, symbol: str, tf: str, since: datetime) -> list[Bar]: ...
    def supports(self, asset_class: str) -> bool: ...
```

- Equities/ETFs → `MassiveAdapter` (Polygon WS endpoints, post-rebrand).
- Commodities → use **ETF proxies** through `MassiveAdapter` (USO/BNO for oil, GLD/IAU for gold, SLV for silver, CPER for copper, UNG for nat gas, DBA for ag). These trade on US exchanges and are covered by our Stocks Advanced subscription. If we ever need actual futures (CL=F, GC=F), add Massive's Futures product as a separate subscription with a `MassiveFuturesAdapter`.
- Crypto → `CoinbaseAdapter` (24/7; scheduler must respect this).

Asset-class-specific quirks (sessions, tick size, halt rules) live in a `MarketCalendar` registry keyed by `instrument.asset_class`.

---

## 14. Operations on the laptop

- **Process supervision**: `launchd` plist that runs `python -m deleveraging_watch.server`, restarts on exit, redirects logs to `~/Library/Logs/deleveraging_watch/`.
- **Sleep prevention**: README documents `caffeinate -dims python -m deleveraging_watch.server` (or amphetamine.app while on battery).
- **Reconnect/backfill**: on WS reconnect, pull REST bars for the gap window and reconcile; never re-fire alerts for backfilled bars (mark them `replayed=true`).
- **Storage**: nightly Parquet archive of `tick > 30d`; SQLite `VACUUM` weekly.
- **Health view**: `/api/health` returns: last tick timestamp per active symbol, WS state, queue depths, **and the latest row of `job_run` for every scheduled job** (started_at, finished_at, status, error). UI shows a red dot if anything stale > 30s during session and surfaces per-job freshness everywhere a computed value appears (§11 "Last updated at" indicators).

---

## 15. Repo layout (proposed)

```
deleveraging-watch/
├── DESIGN.md                  (this file)
├── README.md
├── pyproject.toml
├── server/
│   ├── app.py                 (Flask + SocketIO factory)
│   ├── config.py
│   ├── db/
│   │   ├── schema.sql
│   │   ├── seeds/
│   │   │   ├── factor_buckets.yaml       (80-bucket candidate baskets, §9)
│   │   │   └── social_watch.yaml         (default X accounts, §10.3)
│   │   └── migrations/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── massive.py            (WS quotes + REST aggregates)
│   │   ├── massive_news.py       (/v2/reference/news client — §10.2)
│   │   ├── x_api.py              (X API client: User: Read + /2/users/:id/tweets — §10.3)
│   │   └── finnhub.py
│   ├── jobs/
│   │   ├── quote_stream.py
│   │   ├── threshold_eval.py
│   │   ├── massive_news_poll.py  (hourly, §10.2)
│   │   ├── x_account_poll.py     (every 1 min, §10.3)
│   │   ├── earnings_sync.py
│   │   └── factor_refresh.py
│   ├── analytics/
│   │   ├── regression.py         (OLS per (watch, bucket): β, α, R², p-value, ρ, residual)
│   │   ├── residual.py           (intraday expected/actual/residual for the live UI)
│   │   ├── liquidity.py          (ADV roll-up + exit-liquidity calc from bar_1m/tick)
│   │   ├── usage.py              (api_cost_event aggregator queries for /api/usage)
│   │   └── bucket_pca.py         (PCA over each bucket's candidate basket → representative)
│   ├── alerts/
│   │   ├── rules.py
│   │   └── notifiers/
│   │       ├── pushover.py
│   │       └── console.py
│   ├── nlp/
│   │   ├── finbert.py            (model load; one forward → sentiment logits + pooled embedding)
│   │   ├── ticker_extract.py     (regex matcher against watchlist/proxy symbols + $cashtags)
│   │   ├── profile_text.py       (Haiku call: slow-moving inputs → exposure paragraph)
│   │   ├── profile_embed.py      (FinBERT-embed profile_text → L2-normalized vector)
│   │   └── relevance.py          (hybrid scoring: rules ∪ embedding cosine; applied to news + X)
│   └── api/
│       ├── watchlist.py
│       ├── instrument.py
│       ├── alerts.py
│       ├── notes.py                (CRUD + scope filter + related_notes cosine query)
│       ├── social.py               (social_account_watch CRUD)
│       ├── usage.py                (GET /api/usage → SUM over api_cost_event)
│       └── settings.py
├── web/
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── routes/
│   │   │   ├── Grid.tsx
│   │   │   ├── Instrument.tsx
│   │   │   ├── News.tsx              (global news feed; §11.B)
│   │   │   ├── Notes.tsx             (global notes feed; §11.D)
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   ├── lib/api.ts
│   │   ├── lib/socket.ts
│   │   └── store.ts
│   └── package.json
├── scripts/
│   └── launchd/com.user.deleveraging-watch.plist
└── tests/                       (pytest suite — mirrors server/; see §18)
    ├── conftest.py              (fresh-DB fixture, Flask test client, helpers)
    ├── test_db.py
    ├── test_config.py
    ├── test_adapters_stub.py
    ├── test_quiet_hours.py
    ├── test_volume_zscore.py
    ├── test_rules.py
    ├── test_engine.py
    ├── test_pushover.py
    ├── test_api_watchlist.py
    ├── test_api_alerts.py
    ├── test_api_settings.py
    ├── test_api_health.py
    # Phase 2 coverage (news + social + earnings)
    ├── test_finbert.py                  (stub backend, BLOB roundtrip, cosine)
    ├── test_ticker_extract.py           (cashtag + watchlist-gated bare matches)
    ├── test_relevance.py                (hybrid scoring, semantic discount)
    ├── test_profile_setup.py            (Haiku-stub paragraph → embed → persist)
    ├── test_news_rules.py               (§8 news/social_x severity ladder)
    ├── test_adapters_news.py            (massive_news, finnhub, x_api stubs + costs)
    ├── test_jobs_news.py                (poll → score → persist → broadcast → alert)
    ├── test_api_news.py                 (/api/news union + filters)
    ├── test_api_social.py               (/api/social/accounts CRUD)
    ├── test_api_notes.py                (notes CRUD + from-news/from-social + related)
    ├── test_api_earnings_usage.py       (/api/earnings + /api/usage)
    ├── test_api_watchlist_phase2.py     (watchlist-add runs §10.1 pipeline)
    # Phase 3 coverage (factor exposures)
    ├── test_multitest.py                (BH-FDR @ q=0.05)
    ├── test_bucket_pca.py               (PCA over candidate basket → rep ETF)
    ├── test_regression.py               (OLS β, α, R², p, ρ on aligned returns)
    ├── test_residual.py                 (intraday actual − expected)
    ├── test_adapters_daily.py           (massive_daily stub: correlated stub bars)
    ├── test_jobs_factor.py              (warmup → PCA → refresh → residual chain)
    ├── test_api_exposures.py            (/api/instrument/<sym>/exposures contract)
    # Phase 4 coverage (notes + liquidity + archive)
    ├── test_liquidity.py                (ADV roll-up + exit-liquidity helpers)
    ├── test_jobs_liquidity.py           (liquidity_refresh writes per-instrument)
    ├── test_api_liquidity.py            (/api/instrument/<sym>/liquidity + position size)
    ├── test_jobs_archive_ticks.py       (hot window kept, cold ticks archived)
    ├── test_api_notes_phase4.py         (from-alert, DELETE, symbol denormalization)
    # Phase 5 coverage (bucket-level alerts + candidate-basket editor)
    ├── test_bucket_zscore.py            (today's rep return vs 60d distribution)
    ├── test_bucket_rules.py             (severity ladder + sign(β)·sign(ret)·sign(thesis) adversity)
    ├── test_engine_factor_kind.py       (factor:<bucket> dedup + payload rendering)
    ├── test_jobs_bucket_alerts.py       (off-toggle, default-ON, z-cache, per-bucket dedup)
    └── test_api_buckets.py              (candidate CRUD + on-demand refit_pca)
```

---

## 16. Phased roadmap

Testing is a per-phase discipline, not a phase of its own: every phase ships pytest coverage for the Python modules it adds (see §18).

| Phase | Version | Status | Headline |
|---|---|---|---|
| 0 | v1 | done | Skeleton |
| 1 | v1 | done | Live quotes + price/volume/spread thresholds |
| 2 | v1 | done | News + social pipeline (Massive news + X) + earnings |
| 3 | v1 | done | Factor exposures (80-bucket PCA + BH-FDR) |
| 4 | v1 | done | Notes (per-symbol + global) + liquidity layer + ops polish |
| 5 | v2 | done | Bucket-level alerts + candidate-basket editor (alerts ON by default) |
| 6 | v2 (paid) | future | Options Advanced — requires +$199/mo Massive Options subscription |
| 7 | v3 (paid) | future | Futures Advanced — requires Massive Futures subscription |
| 8 | future | future | Generalization (more thematics, Haiku rationale add-back, twitter-roberta for X if FinBERT quality is an issue) |

---

**Phase 0 — Skeleton (1 weekend)**
- Repo, Flask app, SQLite schema, watchlist CRUD, basic React grid w/ static data.

**Phase 1 — Live quotes + thresholds (1 week)**
- Massive (Polygon) WS adapter, tick storage, 1m bars, price-jump + spread + volume rules, Pushover notifier, drill-down chart.

**Phase 2 — News + social pipeline + earnings (1.5 weeks)**
- **Massive news**: `MassiveNewsAdapter`, `massive_news_poll` hourly job, FinBERT scoring + hybrid relevance against `instrument.profile_embedding`, persistence to `news`, WS broadcast on `news` channel.
- **X curated accounts**: `XApiAdapter`, `x_account_poll` 1-min job, `social_account_watch` CRUD endpoints, FinBERT scoring on tweet text, Settings editor for the curated handle list, seed from `social_watch.yaml`.
- **News & Social UI**: union global feed (§11.B), drill-down News & Social tab (§11.C #4), `kind ∈ {'news','x'}` source filter.
- **Earnings**: Finnhub calendar sync (`earnings_sync` daily 02:00), drill-down Earnings tab.
- Alert pipelines for `kind='news'` and `kind='social_x'`.

**Phase 3 — Factor exposures (1 week, v1)**
- 80-bucket universe, PCA-selected representatives at startup, EOD OLS per (watch, bucket) with BH-FDR significance filter, intraday residual refresh, Context tab. PCA refresh cron set to quarterly.

**Phase 4 — Notes + liquidity + persistence polish (few days)**
- Per-symbol Notes tab composer + viewer, global `/notes` route, FinBERT-embedding-on-insert for global notes, "Related market notes" panel on drill-downs (cosine ≥ 0.55 vs `instrument.profile_embedding`), alert↔note + news↔note linking. **Liquidity layer**: `liquidity_daily` table, EOD `liquidity_refresh` job, Microstructure-tab ADV + exit-liquidity panel, per-watch `position_size` editor. Archive job, launchd plist, prevent-sleep doc.

**Phase 5 — Bucket-level alerts (v2)**
- Per-user candidate-basket editor (add/remove ETFs from a bucket and re-run PCA on demand); bucket-level deleveraging alerts (§9, held out of v1 until baseline noise is observed).

**Phase 6 — Options Advanced *(paid add-on, +$199/mo Massive Options)***
- Subscribe to Massive Options Advanced. New `MassiveOptionsAdapter`. Track unusual options volume (today vs 20d avg), IV percentile, put-call ratio, skew, large block prints. New alert kinds (`kind='options_volume'`, `kind='iv_spike'`). Schema additions for `options_snapshot` table. Drill-down gets an "Options" tab.

**Phase 7 — Futures Advanced *(paid add-on, sales-quoted)***
- Subscribe to Massive Futures. New `MassiveFuturesAdapter` for ES/NQ/RTY/VX (overnight context) and commodity futures (CL/GC/etc. for fundamental commodity exposure beyond ETF proxies). Pre-market overnight digest enrichment (futures gap moves on indices the watchlist is exposed to).

**Phase 8 — Generalization (later)**
- Additional thematics, commodity-via-ETF coverage refinements, optional Haiku rationale-add-back on alert-firing headlines.

---

## 17. Decisions log

Each row is a foundational decision plus a pointer to where it lives. All v1-blocking decisions are settled; one item remains open (see end).

| # | Decision | Where it lives |
|---|---|---|
| 1 | Market data: **Massive Stocks Advanced $199/mo**. Real-time SIP over WS+REST. Finnhub for earnings + profile only. yfinance not used. | §3.1, §5 |
| 2 | Notifications: **Pushover only**, four applications (Critical/Warning/News/Info) for distinct lock-screen icons. No Twilio in v1. | §3.2, §12 |
| 3 | Sentiment + relevance: **FinBERT locally** (one forward pass → sentiment + 768-dim embedding). Hybrid relevance = `max(rule_score, 0.85 × cosine_sim)`. Applied to **Massive news headlines** and **X post text**. Haiku used only for monthly profile-text generation (~$0.10/mo). | §3.3, §10 |
| 4 | News + social architecture: **Massive `/v2/reference/news` (bundled) + curated X accounts (~$15/mo)**. Brave Search removed; Haiku macro-query generator removed. Curated list seeded from `social_watch.yaml`, editable in Settings, roughly time-invariant. | §10, §5, §11.E |
| 5 | Bucket universe: **80 buckets**. All representatives picked by PCA from v1 (no hand-picks). BH-FDR @ q=0.05 for significance filtering. Bucket-level alerts held to Phase 5. | §3.4, §9 |
| 6 | Quiet hours: **work hours Mon–Fri 09:00–17:00 ET**, quiet otherwise + weekends. Only `critical` pages overnight; `high`/`warn` queue to **08:00 ET morning digest**; `info` drops. 4-tier severity (`info`/`warn`/`high`/`critical`). | §3.5, §8, §12 |
| 7 | Update log: **both per-symbol and global scopes**. Global notes are FinBERT-embedded; auto-surface on per-symbol drill-downs at cosine ≥ 0.55 vs `profile_embedding`. Dedicated `/notes` route + "what mattered today" quick-add. | §11.D |
| 8 | Liquidity layer: ADV + exit-liquidity ship in v1, derived from existing Stocks Advanced data. Options (+$199/mo) is Phase 6; Futures is Phase 7. | §11.C, §16 |

### Still open

- **Asset classes beyond equities/ETFs for v1.** Current v1 covers equities + ETF proxies (factor / thematic / commodity). Open: do we want to commit to actual futures contracts (`CL=F`, `GC=F`) from day one, which would require subscribing to Massive Futures (Phase 7 pulled forward)? Default if unanswered: equity/ETF only for v1, real futures wait for Phase 7.

---

## 18. Testing strategy

Python is tested with **pytest**. The frontend is not unit-tested in v1 — it's thin enough that broken renders surface immediately against the live backend, and a single-user dashboard doesn't justify the React-testing-library overhead. Revisit if the SPA grows past ~10 routes.

### Discipline

Every phase that adds Python modules ships pytest coverage for them in the **same PR**. "Working" means `pytest` is green; the smoke scripts under `scripts/` are quick demonstrations, not the test of record. CI is out of scope for a personal laptop project — run `pytest` locally before each phase ends.

### Layout

`tests/` mirrors `server/` one-for-one (see §15). A `conftest.py` at the root provides shared fixtures; per-test isolation is the default.

### Fixtures

- **Fresh DB per test.** `fresh_db` (autouse) points `DW_DB_PATH` at a per-session tempfile, closes the thread-local connection between tests, and re-runs `init_db()` so seeds are loaded fresh. No test ever touches the real `deleveraging_watch.db`.
- **Flask test client.** `client` builds the app with `start_background=False` (no scheduler, no feed thread) and returns `app.test_client()`. Background work is exercised by calling job `run()` functions directly.
- **Synthetic ticks.** `seed_ticks(iid, start_px, end_px, n, spread_bps)` writes a linear price walk into the `tick` table so rules tests are deterministic regardless of wall-clock.
- **Time injection.** `quiet_hours.route(severity, now_et=...)` accepts an explicit time, so quiet-hours tests don't depend on when they run.

### What to test (and what not to)

| Worth testing | Notes |
|---|---|
| Pure functions (rules, quiet_hours.route, volume z-score, pushover.category_for) | Deterministic in / deterministic out — cheap and high-signal. |
| Engine orchestration | dedup, persist+adverse routing, console fallback. Mock `socketio` with a stub that records emits. |
| API blueprints | `client.get/post/...` round-trips. Validation errors (400, 404, 409) are part of the contract. |
| DB schema + seeds | `init_db()` is idempotent; seeds load 80 buckets + 15 X accounts. |
| StubAdapter | Subscribe → tick fires on the callback within one polling interval. |

| Not worth testing |
|---|
| `MassiveAdapter` live socket (covered by integration smoke once a key exists; mocking websocket-client adds friction without confidence). |
| `PushoverNotifier` real send (mock `requests.post`; no live calls in CI). |
| APScheduler trigger plumbing (it works; test the job `run()` functions, not the cron expression). |
| Frontend (see "not unit-tested" above). |

### Running

```bash
../bin/pip install -e '.[dev]'   # pytest + ruff
../bin/pytest -q                  # whole suite
../bin/pytest tests/test_rules.py # one module
```
