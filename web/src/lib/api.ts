// REST client for the Flask API (DESIGN.md §7.1). In dev, Vite proxies /api to
// the backend on :5000; in prod they share an origin.

export interface Snapshot {
  ts: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  bid_size: number | null;
  ask_size: number | null;
}

export interface Watch {
  id: number;
  symbol: string;
  display_name: string;
  asset_class: string;
  direction: "BULL" | "BEAR";
  active: boolean;
  entered_at: string;
  thresholds: Record<string, number | null>;
  snapshot: Snapshot | null;
}

export interface Health {
  feed: { adapter: string; status: string; last_tick_age_s: number | null; symbols_live: number };
  notifier: string;
  jobs: Array<{ job_name: string; status: string; started_at: string; finished_at: string | null }>;
}

export type Severity = "info" | "warn" | "high" | "critical";

export interface Alert {
  id: number;
  symbol: string;
  kind: string;
  severity: Severity;
  adverse: boolean;
  ts: string;
  payload: Record<string, unknown>;
  notified_via: string | null;
  acked_at: string | null;
  quiet_queued: boolean;
}

export interface Bar {
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  vwap: number | null;
}

export interface InstrumentDetail {
  instrument_id: number;
  symbol: string;
  display_name: string;
  asset_class: string;
  exchange: string | null;
  meta: Record<string, unknown> | null;
  watch: { id: number; direction: "BULL" | "BEAR"; position_size: number | null } | null;
  snapshot: Snapshot | null;
}

// Unified news/social feed item (§7.1 /api/news, /api/instrument/:symbol/news).
export type NewsKind = "news" | "x";
export type SentimentLabel = "positive" | "negative" | "neutral";
export interface NewsItem {
  id: number;
  kind: NewsKind;
  title: string | null;        // null for X posts
  body: string;
  url: string | null;
  source: string | null;
  posted_at: string;
  relevance: number;
  relevance_source: "symbol" | "sector" | "semantic";
  sentiment: number;           // -1..1
  sentiment_label: SentimentLabel;
  sentiment_conf: number;
  tickers: string[];
}

export interface SocialAccount {
  id: number;
  handle: string;
  label: string | null;
  external_id: string | null;
  active: boolean;
  added_at: string;
  last_polled_at: string | null;
  last_post_id: string | null;
}

export interface EarningsRow {
  symbol?: string;
  scheduled_at: string;
  when_hint: string | null;
  eps_estimate: number | null;
  rev_estimate: number | null;
}

// Factor exposure for the Context tab (§9, §11.C).
export interface Exposure {
  bucket_id: number;
  bucket_label: string;
  bucket_kind: string;
  representative: string;
  pc1_var_explained: number | null;
  beta: number;
  intercept: number;
  r_squared: number;
  p_value: number;
  q_value: number | null;
  significant: boolean;
  correlation: number;
  last_residual: number | null;
  window_days: number;
  computed_at: string;
}

export interface ExposuresResp {
  symbol: string;
  watch_id: number;
  significant_only: boolean;
  exposures: Exposure[];
}

// Phase 4: notes + liquidity types.
export interface Note {
  id: number;
  instrument_id: number | null;
  symbol: string | null;
  ts: string;
  body: string;
  linked_alert_id: number | null;
  linked_news_id: number | null;
  linked_social_post_id: number | null;
}

export interface RelatedNote {
  id: number;
  ts: string;
  body: string;
  cosine: number;
}

// Phase 5: candidate-basket editor.
export interface BucketSummary {
  id: number;
  kind: string;
  label: string;
  active: boolean;
  pc1_var_explained: number | null;
  selected_at: string | null;
  representative_id: number | null;
  representative_symbol: string | null;
}

export interface BucketCandidate {
  instrument_id: number;
  symbol: string;
  pc1_loading: number | null;
  last_pca_at: string | null;
  is_representative: boolean;
}

export interface BucketDetail extends BucketSummary {
  candidates: BucketCandidate[];
}

export interface PcaRefitResult {
  ok: boolean;
  representative_id: number;
  representative_symbol: string;
  pc1_var_explained: number;
  n_obs: number;
  note: string;
}

export interface Liquidity {
  symbol: string;
  computed_at: string | null;
  as_of: string | null;
  adv_shares_21d: number | null;
  adv_dollar_21d: number | null;
  spread_avg_bps: number | null;
  pct_zero_volume: number | null;
  participation: number;
  position_size: number | null;
  rank_in_watchlist: number | null;
  watchlist_size: number | null;
  days_to_exit: number | null;
  cost_to_exit_bps: number | null;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  watchlist: () => fetch("/api/watchlist").then((r) => json<Watch[]>(r)),
  health: () => fetch("/api/health").then((r) => json<Health>(r)),
  addWatch: (symbol: string, direction: "BULL" | "BEAR") =>
    fetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, direction }),
    }).then((r) => json<Watch>(r)),
  removeWatch: (id: number) =>
    fetch(`/api/watchlist/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  alerts: (limit = 50) =>
    fetch(`/api/alerts?limit=${limit}`).then((r) => json<Alert[]>(r)),
  ackAlert: (id: number) =>
    fetch(`/api/alerts/${id}/ack`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r)),
  instrument: (symbol: string) =>
    fetch(`/api/instrument/${symbol}`).then((r) => json<InstrumentDetail>(r)),
  bars: (symbol: string, tf = "1m") =>
    fetch(`/api/instrument/${symbol}/bars?tf=${tf}`).then(
      (r) => json<{ symbol: string; tf: string; bars: Bar[] }>(r),
    ),
  exposures: (symbol: string, significantOnly = true) =>
    fetch(`/api/instrument/${symbol}/exposures?significant_only=${significantOnly}`).then(
      (r) => json<ExposuresResp>(r),
    ),

  // Notes (Phase 4)
  notes: (params: {
    scope?: "all" | "global" | "symbol";
    instrument_id?: number;
    since?: string;
  } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && String(v) !== "") q.set(k, String(v));
    }
    return fetch(`/api/notes${q.toString() ? `?${q}` : ""}`).then((r) => json<Note[]>(r));
  },
  createNote: (body: string, instrumentId?: number | null,
               linkedAlertId?: number | null) =>
    fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        body,
        instrument_id: instrumentId ?? undefined,
        linked_alert_id: linkedAlertId ?? undefined,
      }),
    }).then((r) => json<Note>(r)),
  deleteNote: (id: number) =>
    fetch(`/api/notes/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  noteFromAlert: (alertId: number, instrumentId?: number) =>
    fetch(`/api/notes/from-alert/${alertId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(instrumentId ? { instrument_id: instrumentId } : {}),
    }).then((r) => json<Note>(r)),
  relatedNotes: (symbol: string, cosineMin = 0.55) =>
    fetch(`/api/instrument/${symbol}/related_notes?cosine_min=${cosineMin}`).then(
      (r) => json<RelatedNote[]>(r),
    ),

  // Liquidity (Phase 4)
  liquidity: (symbol: string, participation = 0.10) =>
    fetch(`/api/instrument/${symbol}/liquidity?participation=${participation}`).then(
      (r) => json<Liquidity>(r),
    ),
  setPositionSize: (watchId: number, positionSize: number | null) =>
    fetch(`/api/watchlist/${watchId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thresholds: { position_size: positionSize } }),
    }).then((r) => json<{ ok: boolean }>(r)),

  // Buckets / candidate-basket editor (Phase 5)
  buckets: () => fetch("/api/buckets").then((r) => json<BucketSummary[]>(r)),
  bucket: (id: number) => fetch(`/api/buckets/${id}`).then((r) => json<BucketDetail>(r)),
  addCandidate: (bucketId: number, symbol: string) =>
    fetch(`/api/buckets/${bucketId}/candidates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    }).then((r) => json<{ ok: boolean; symbol: string; instrument_id: number }>(r)),
  removeCandidate: (bucketId: number, symbol: string) =>
    fetch(`/api/buckets/${bucketId}/candidates/${symbol}`, { method: "DELETE" }).then(
      (r) => json<{ ok: boolean }>(r),
    ),
  refitPca: (bucketId: number) =>
    fetch(`/api/buckets/${bucketId}/refit_pca`, { method: "POST" }).then(
      (r) => json<PcaRefitResult>(r),
    ),

  // News + social (Phase 2)
  news: (params: {
    source?: "news" | "x" | "all";
    sentiment?: "any" | "pos" | "neg";
    min_relevance?: number;
    limit?: number;
    ticker?: string;
  } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && String(v) !== "") q.set(k, String(v));
    }
    return fetch(`/api/news${q.toString() ? `?${q}` : ""}`).then((r) => json<NewsItem[]>(r));
  },
  newsForSymbol: (symbol: string, params: {
    source?: "news" | "x" | "all";
    sentiment?: "any" | "pos" | "neg";
    min_relevance?: number;
    limit?: number;
  } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && String(v) !== "") q.set(k, String(v));
    }
    return fetch(`/api/instrument/${symbol}/news${q.toString() ? `?${q}` : ""}`).then(
      (r) => json<NewsItem[]>(r),
    );
  },
  socialAccounts: (activeOnly = true) =>
    fetch(`/api/social/accounts?active=${activeOnly}`).then((r) => json<SocialAccount[]>(r)),
  addSocialAccount: (handle: string, label?: string) =>
    fetch("/api/social/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handle, label }),
    }).then((r) => json<SocialAccount>(r)),
  patchSocialAccount: (id: number, patch: Partial<{ label: string; active: boolean }>) =>
    fetch(`/api/social/accounts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => json<{ ok: boolean }>(r)),
  deleteSocialAccount: (id: number) =>
    fetch(`/api/social/accounts/${id}`, { method: "DELETE" }).then(
      (r) => json<{ ok: boolean }>(r),
    ),
  earnings: (windowDays = 14) =>
    fetch(`/api/earnings?window=${windowDays}d`).then((r) => json<EarningsRow[]>(r)),
  earningsForSymbol: (symbol: string) =>
    fetch(`/api/instrument/${symbol}/earnings`).then((r) => json<EarningsRow[]>(r)),
  noteFromNews: (newsId: number, instrumentId?: number) =>
    fetch(`/api/notes/from-news/${newsId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(instrumentId ? { instrument_id: instrumentId } : {}),
    }).then((r) => json<{ id: number; instrument_id: number | null }>(r)),
  noteFromSocial: (postId: number, instrumentId?: number) =>
    fetch(`/api/notes/from-social/${postId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(instrumentId ? { instrument_id: instrumentId } : {}),
    }).then((r) => json<{ id: number; instrument_id: number | null }>(r)),
};
