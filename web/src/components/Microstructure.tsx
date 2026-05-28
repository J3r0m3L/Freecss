// Microstructure tab (DESIGN.md §11.C #2). Displays the latest liquidity_daily
// snapshot — ADV in shares/dollars, session-avg spread, pct_zero_volume, rank
// in watchlist — and exposes the per-watch position_size editor so the
// exit-liquidity calc updates live (days_to_exit, cost_to_exit_bps).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type InstrumentDetail } from "../lib/api";

function fmtShares(n: number | null): string {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return n.toFixed(0);
}

function fmtUsd(n: number | null): string {
  if (n == null) return "—";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}k`;
  return `$${n.toFixed(0)}`;
}

function fmtPct(x: number | null, digits = 1): string {
  if (x == null) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

function fmtBps(x: number | null): string {
  if (x == null) return "—";
  return `${x.toFixed(1)} bps`;
}

function fmtDays(x: number | null): string {
  if (x == null) return "—";
  if (x >= 100) return `${Math.round(x)}d`;
  if (x >= 1) return `${x.toFixed(1)}d`;
  return `${(x * 24).toFixed(1)}h`;
}

export function Microstructure({
  symbol, detail,
}: { symbol: string; detail: InstrumentDetail }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["liquidity", symbol],
    queryFn: () => api.liquidity(symbol),
    refetchInterval: 60_000,
  });

  const [draft, setDraft] = useState<string>(
    detail.watch?.position_size != null ? String(detail.watch.position_size) : "",
  );
  useEffect(() => {
    setDraft(detail.watch?.position_size != null
      ? String(detail.watch.position_size) : "");
  }, [detail.watch?.position_size]);

  const setSize = useMutation({
    mutationFn: () => {
      if (!detail.watch) throw new Error("no active watch");
      const parsed = draft.trim() === "" ? null : Number(draft);
      if (parsed !== null && (!isFinite(parsed) || parsed < 0)) {
        throw new Error("position must be a non-negative number");
      }
      return api.setPositionSize(detail.watch.id, parsed);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["liquidity", symbol] });
      qc.invalidateQueries({ queryKey: ["instrument", symbol] });
    },
  });

  if (q.isLoading) return <div className="empty">Loading liquidity…</div>;
  if (q.error) return <div className="empty down">{(q.error as Error).message}</div>;
  const l = q.data!;

  const stale = l.computed_at ? (
    <span className="muted" style={{ fontSize: 11 }}>
      computed {new Date(l.computed_at).toLocaleString()} · as of {l.as_of}
    </span>
  ) : (
    <span className="muted" style={{ fontSize: 11 }}>
      No snapshot yet — liquidity_refresh runs at 16:35 ET.
    </span>
  );

  return (
    <div className="micro-panel">
      <div className="micro-grid">
        <div className="micro-cell">
          <span className="label">ADV (21d, shares)</span>
          <span className="value mono">{fmtShares(l.adv_shares_21d)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">ADV (21d, $)</span>
          <span className="value mono">{fmtUsd(l.adv_dollar_21d)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">Session-avg spread</span>
          <span className="value mono">{fmtBps(l.spread_avg_bps)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">Zero-vol bars today</span>
          <span className="value mono">{fmtPct(l.pct_zero_volume)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">Liquidity rank</span>
          <span className="value mono">
            {l.rank_in_watchlist == null
              ? "—"
              : `${l.rank_in_watchlist} / ${l.watchlist_size}`}
          </span>
        </div>
      </div>

      <h4>Exit liquidity</h4>
      <form
        className="position-form"
        onSubmit={(e) => {
          e.preventDefault();
          setSize.mutate();
        }}
      >
        <label>
          Position size (shares)
          <input
            type="number" min={0} step="any" value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. 5000"
          />
        </label>
        <button type="submit" disabled={setSize.isPending}>
          {setSize.isPending ? "Saving…" : "Save"}
        </button>
      </form>
      {setSize.error ? (
        <div className="empty down">{(setSize.error as Error).message}</div>
      ) : null}

      <div className="micro-grid">
        <div className="micro-cell">
          <span className="label">Participation (assumed)</span>
          <span className="value mono">{fmtPct(l.participation, 0)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">Days to exit</span>
          <span className="value mono">{fmtDays(l.days_to_exit)}</span>
        </div>
        <div className="micro-cell">
          <span className="label">Est. cost to exit</span>
          <span className="value mono">{fmtBps(l.cost_to_exit_bps)}</span>
        </div>
      </div>

      <div className="micro-stamp">{stale}</div>
    </div>
  );
}
