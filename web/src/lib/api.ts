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
};
