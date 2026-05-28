-- Deleveraging Watch — SQLite schema (DESIGN.md §6).
-- Asset-class generic: every tracked thing is an `instrument`; a `watch` binds
-- an instrument to a thesis direction and per-symbol thresholds.
-- WAL mode is set at connection time in db/__init__.py, not here.

PRAGMA foreign_keys = ON;

-- A symbol the user could track. Pre-seeded with equities/ETFs; extendable.
CREATE TABLE IF NOT EXISTS instrument (
  id                INTEGER PRIMARY KEY,
  symbol            TEXT NOT NULL UNIQUE,        -- 'AAPL', 'SPY', 'USO'
  display_name      TEXT NOT NULL,
  asset_class       TEXT NOT NULL,              -- 'equity','etf','future','crypto','index'
  exchange          TEXT,
  data_adapter      TEXT NOT NULL,              -- 'massive' (v1); future: 'ibkr','coinbase'
  meta_json         TEXT,                       -- JSON blob (Massive ref + Finnhub profile2)
  meta_refreshed_at TIMESTAMP,                  -- last profile pull; refresh quarterly
  profile_text      TEXT,                       -- Haiku-generated economic-exposure paragraph
  profile_embedding BLOB                        -- 768-dim float32 FinBERT pooled embedding (L2-norm)
);

-- User watchlist with thesis.
CREATE TABLE IF NOT EXISTS watch (
  id               INTEGER PRIMARY KEY,
  instrument_id    INTEGER NOT NULL REFERENCES instrument(id),
  direction        TEXT NOT NULL CHECK(direction IN ('BULL','BEAR')),
  entered_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  active           INTEGER NOT NULL DEFAULT 1,
  -- Per-symbol overrides; NULL = use global defaults.
  px_jump_pct      REAL,
  px_jump_window_s INTEGER,
  spread_bps_max   REAL,
  volume_zscore    REAL,
  position_size    REAL,                        -- shares held; drives exit-liquidity calc (§11.C)
  notes            TEXT
);
CREATE INDEX IF NOT EXISTS idx_watch_active ON watch(active, instrument_id);

-- Append-only time series of quotes/trades. Keep 30 days hot; archive older.
CREATE TABLE IF NOT EXISTS tick (
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  ts            TIMESTAMP NOT NULL,
  bid           REAL,
  ask           REAL,
  last          REAL,
  bid_size      INTEGER,
  ask_size      INTEGER,
  trade_size    INTEGER,
  PRIMARY KEY (instrument_id, ts)
) WITHOUT ROWID;

-- Aggregated 1m bars for charts (computed from ticks).
CREATE TABLE IF NOT EXISTS bar_1m (
  instrument_id INTEGER NOT NULL,
  ts            TIMESTAMP NOT NULL,
  o REAL, h REAL, l REAL, c REAL,
  v INTEGER, vwap REAL,
  PRIMARY KEY (instrument_id, ts)
) WITHOUT ROWID;

-- Daily bars (Phase 3). Bulk-loaded on first run, then refreshed EOD. Required
-- by factor_pca (PCA over ~6mo of returns) and factor_refresh (rolling-window OLS).
CREATE TABLE IF NOT EXISTS bar_daily (
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  date          DATE NOT NULL,
  o REAL, h REAL, l REAL, c REAL,
  v INTEGER, vwap REAL,
  PRIMARY KEY (instrument_id, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_bar_daily_recent ON bar_daily(instrument_id, date DESC);

-- Alert events that fired.
CREATE TABLE IF NOT EXISTS alert (
  id               INTEGER PRIMARY KEY,
  instrument_id    INTEGER NOT NULL REFERENCES instrument(id),
  ts               TIMESTAMP NOT NULL,
  kind             TEXT NOT NULL,               -- px_jump,spread,volume,combined,news,social_x,earnings
  severity         TEXT NOT NULL,               -- info,warn,high,critical
  adverse          INTEGER NOT NULL,            -- 1 if against thesis
  payload_json     TEXT NOT NULL,
  notified_via     TEXT,
  pushover_receipt TEXT,
  acked_at         TIMESTAMP,
  quiet_queued     INTEGER NOT NULL DEFAULT 0,
  digested_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert(ts DESC);

-- News headlines from Massive's /v2/reference/news endpoint, re-scored by FinBERT.
CREATE TABLE IF NOT EXISTS news (
  id               INTEGER PRIMARY KEY,
  fetched_at       TIMESTAMP NOT NULL,
  source           TEXT,                        -- Massive publisher.name
  url              TEXT UNIQUE,                 -- Massive article_url
  title            TEXT NOT NULL,
  snippet          TEXT,
  published_at     TIMESTAMP,
  massive_id       TEXT,
  massive_insights TEXT,                        -- raw JSON of Massive insights[] (cross-check)
  relevance        REAL,                        -- max(rule_score, 0.85 * cosine_sim)
  relevance_source TEXT,                        -- 'symbol' | 'sector' | 'semantic'
  sentiment        REAL,                        -- -1..1 (p_pos - p_neg)
  sentiment_label  TEXT,                        -- positive | negative | neutral
  sentiment_conf   REAL,
  tickers_json     TEXT                         -- Massive tickers[] ∪ regex-extracted
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_massive_id ON news(massive_id);

-- Curated X accounts the user follows (X-only in v1; source column kept for forward-compat).
CREATE TABLE IF NOT EXISTS social_account_watch (
  id             INTEGER PRIMARY KEY,
  source         TEXT NOT NULL DEFAULT 'x' CHECK(source IN ('x')),
  handle         TEXT NOT NULL,                 -- stored without leading '@'
  label          TEXT,
  external_id    TEXT,                          -- numeric X user_id (one-time User: Read)
  active         INTEGER NOT NULL DEFAULT 1,
  added_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_polled_at TIMESTAMP,
  last_post_id   TEXT,                          -- since_id for next poll
  UNIQUE(source, handle)
);

-- Individual social posts ingested from X.
CREATE TABLE IF NOT EXISTS social_post (
  id               INTEGER PRIMARY KEY,
  source           TEXT NOT NULL DEFAULT 'x' CHECK(source IN ('x')),
  account_id       INTEGER NOT NULL REFERENCES social_account_watch(id),
  external_post_id TEXT NOT NULL,
  posted_at        TIMESTAMP NOT NULL,
  fetched_at       TIMESTAMP NOT NULL,
  body             TEXT NOT NULL,
  url              TEXT,
  tickers_json     TEXT,
  relevance        REAL,
  relevance_source TEXT,                        -- 'symbol' | 'sector' | 'semantic'
  sentiment        REAL,
  sentiment_label  TEXT,
  sentiment_conf   REAL,
  UNIQUE(source, external_post_id)
);
CREATE INDEX IF NOT EXISTS idx_social_post_posted ON social_post(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_post_account ON social_post(account_id, posted_at DESC);

-- User-written notes. instrument_id NOT NULL = per-symbol; NULL = global market-wide.
CREATE TABLE IF NOT EXISTS update_log (
  id                    INTEGER PRIMARY KEY,
  instrument_id         INTEGER REFERENCES instrument(id),
  ts                    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  body                  TEXT NOT NULL,
  body_embedding        BLOB,                   -- FinBERT pooled embedding; only for global notes
  linked_alert_id       INTEGER REFERENCES alert(id),
  linked_news_id        INTEGER REFERENCES news(id),
  linked_social_post_id INTEGER REFERENCES social_post(id)
);
CREATE INDEX IF NOT EXISTS idx_update_log_ts ON update_log(ts DESC);

-- Daily liquidity snapshot. EOD job rolls 21d means (ADV + exit-liquidity).
CREATE TABLE IF NOT EXISTS liquidity_daily (
  instrument_id   INTEGER NOT NULL REFERENCES instrument(id),
  date            DATE NOT NULL,
  adv_shares_21d  REAL,
  adv_dollar_21d  REAL,
  spread_avg_bps  REAL,
  pct_zero_volume REAL,
  computed_at     TIMESTAMP NOT NULL,
  PRIMARY KEY (instrument_id, date)
);
CREATE INDEX IF NOT EXISTS idx_liquidity_latest ON liquidity_daily(instrument_id, date DESC);

-- Upcoming earnings.
CREATE TABLE IF NOT EXISTS earnings (
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  scheduled_at  TIMESTAMP NOT NULL,
  when_hint     TEXT,                           -- 'bmo','amc','dmt'
  eps_estimate  REAL,
  rev_estimate  REAL,
  fetched_at    TIMESTAMP NOT NULL,
  PRIMARY KEY (instrument_id, scheduled_at)
);

-- Factor/thematic bucket → representative ETF (picked by PCA, §9 / §3.4).
CREATE TABLE IF NOT EXISTS factor_bucket (
  id                INTEGER PRIMARY KEY,
  kind              TEXT NOT NULL,              -- index,factor,sector,sub_sector,intl,commodity,thematic
  label             TEXT NOT NULL UNIQUE,
  representative_id INTEGER REFERENCES instrument(id),
  pc1_var_explained REAL,
  selected_at       TIMESTAMP,
  active            INTEGER NOT NULL DEFAULT 1
);

-- Candidate ETFs per bucket, with PC1 loadings after each PCA run.
CREATE TABLE IF NOT EXISTS factor_bucket_candidate (
  bucket_id     INTEGER NOT NULL REFERENCES factor_bucket(id),
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  pc1_loading   REAL,
  last_pca_at   TIMESTAMP,
  PRIMARY KEY (bucket_id, instrument_id)
);

-- Per (watch, bucket) regression results.
CREATE TABLE IF NOT EXISTS factor_exposure (
  watch_id      INTEGER NOT NULL REFERENCES watch(id),
  bucket_id     INTEGER NOT NULL REFERENCES factor_bucket(id),
  window_days   INTEGER NOT NULL,
  beta          REAL NOT NULL,
  intercept     REAL NOT NULL,
  r_squared     REAL NOT NULL,
  p_value       REAL NOT NULL,
  q_value       REAL,
  significant   INTEGER NOT NULL DEFAULT 0,
  correlation   REAL NOT NULL,
  last_residual REAL,
  computed_at   TIMESTAMP NOT NULL,
  PRIMARY KEY (watch_id, bucket_id, window_days)
);

CREATE TABLE IF NOT EXISTS setting (
  key        TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

-- Every scheduled job writes one row per run (source of truth for freshness badges).
CREATE TABLE IF NOT EXISTS job_run (
  job_name      TEXT NOT NULL,
  started_at    TIMESTAMP NOT NULL,
  finished_at   TIMESTAMP,
  status        TEXT NOT NULL,                  -- ok,error,running
  rows_written  INTEGER,
  error_message TEXT,
  PRIMARY KEY (job_name, started_at)
);
CREATE INDEX IF NOT EXISTS idx_job_run_latest ON job_run(job_name, started_at DESC);

-- Per-API-call billing events (real spend, not estimates).
CREATE TABLE IF NOT EXISTS api_cost_event (
  id            INTEGER PRIMARY KEY,
  ts            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source        TEXT NOT NULL,                  -- x:tweets, x:user_read, massive:news, haiku:profile_text
  units         INTEGER NOT NULL,
  unit_cost_usd REAL NOT NULL,
  cost_usd      REAL NOT NULL,
  ref_job_run   TEXT,
  ref_endpoint  TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_cost_event_recent ON api_cost_event(ts DESC);
CREATE INDEX IF NOT EXISTS idx_api_cost_event_source_month ON api_cost_event(source, ts DESC);
