// Watchlist Grid — default route `/` (DESIGN.md §11.A).
// Phase 1: live last price (Socket.IO), spread, adverse red dot driven by recent
// alerts for that symbol, and a sticky-header "last alert" chip fed by both the
// REST /api/alerts seed and the Socket.IO `alerts` channel for real-time pushes.
// News mini-stack, sparkline, and the morning-digest chip arrive in Phase 2+.
import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, type Watch, type Snapshot, type Alert } from "../lib/api";
import { onTick, onAlert, type AlertEvent } from "../lib/socket";

function spreadBps(s: Snapshot | null): number | null {
  if (!s || s.bid == null || s.ask == null || s.last == null || s.last === 0) return null;
  return ((s.ask - s.bid) / s.last) * 10_000;
}

function Card({
  w, onRemove, hot,
}: { w: Watch; onRemove: (id: number) => void; hot: boolean }) {
  const [snap, setSnap] = useState<Snapshot | null>(w.snapshot);
  const navigate = useNavigate();
  useEffect(() => onTick(w.symbol, (q) => setSnap(q)), [w.symbol]);

  const bps = spreadBps(snap);
  return (
    <div
      className={`card${hot ? " adverse-hot" : ""}`}
      onClick={() => navigate(`/instrument/${w.symbol}`)}
    >
      <div className="row">
        <span className="sym">
          {w.symbol} {w.direction === "BULL" ? "🐂" : "🐻"}
          {hot ? <span className="adverse-dot" title="recent adverse alert" /> : null}
        </span>
        <span className="price">{snap?.last != null ? snap.last.toFixed(2) : "—"}</span>
      </div>
      <div className="meta">
        <span className="mono">{bps != null ? `${bps.toFixed(1)} bps` : "— bps"}</span>
        {" · "}
        <span>{w.display_name}</span>
        {" · "}
        <span
          className="muted"
          style={{ cursor: "pointer" }}
          onClick={(e) => {
            e.stopPropagation();
            onRemove(w.id);
          }}
          title="Remove from watchlist"
        >
          remove
        </span>
      </div>
    </div>
  );
}

export function Grid() {
  const qc = useQueryClient();
  const { data: watches = [], isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: api.watchlist,
    refetchInterval: 15_000,
  });
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 5_000,
  });
  const { data: alertsSeed = [] } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.alerts(50),
    refetchInterval: 30_000,
  });

  // Merge socket-pushed alerts with the REST seed; dedupe by id.
  const [live, setLive] = useState<AlertEvent[]>([]);
  useEffect(() => onAlert((a) => setLive((prev) => [a, ...prev].slice(0, 50))), []);

  const merged: Alert[] = useMemo(() => {
    const seen = new Set<number>();
    const out: Alert[] = [];
    for (const a of live) {
      if (seen.has(a.id)) continue;
      seen.add(a.id);
      out.push({ ...a, payload: a.payload, notified_via: null, acked_at: null, quiet_queued: false });
    }
    for (const a of alertsSeed) {
      if (seen.has(a.id)) continue;
      seen.add(a.id);
      out.push(a);
    }
    return out;
  }, [alertsSeed, live]);

  // A watch is "hot" if it has an adverse alert in the last 15 min (dedup window §8).
  const cutoff = Date.now() - 15 * 60 * 1000;
  const hotSymbols = new Set(
    merged.filter((a) => a.adverse && Date.parse(a.ts) >= cutoff).map((a) => a.symbol),
  );
  const lastAlert = merged[0];

  const add = useMutation({
    mutationFn: (v: { symbol: string; direction: "BULL" | "BEAR" }) =>
      api.addWatch(v.symbol, v.direction),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
  const remove = useMutation({
    mutationFn: api.removeWatch,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const [symbol, setSymbol] = useState("");
  const [direction, setDirection] = useState<"BULL" | "BEAR">("BULL");

  const feedStatus = health?.feed.status ?? "no_data";

  return (
    <>
      <header className="topbar">
        <h1>
          <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
            Deleveraging Watch
          </Link>
        </h1>
        <span className="badge">
          <span className={`dot ${feedStatus}`} /> feed: {feedStatus}
          {health?.feed.last_tick_age_s != null
            ? ` (${health.feed.last_tick_age_s.toFixed(0)}s)`
            : ""}
        </span>
        <span className="badge">adapter: {health?.feed.adapter ?? "—"}</span>
        {lastAlert ? (
          <Link to={`/instrument/${lastAlert.symbol}`} className="badge"
                style={{ textDecoration: "none" }}>
            last: <span className={`sev ${lastAlert.severity}`}>{lastAlert.severity}</span>{" "}
            {lastAlert.symbol} · {lastAlert.kind}
          </Link>
        ) : null}
        <div className="spacer" />
        <form
          className="add-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!symbol.trim()) return;
            add.mutate({ symbol: symbol.trim().toUpperCase(), direction });
            setSymbol("");
          }}
        >
          <input
            placeholder="SYMBOL"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          />
          <select value={direction} onChange={(e) => setDirection(e.target.value as "BULL" | "BEAR")}>
            <option value="BULL">🐂 BULL</option>
            <option value="BEAR">🐻 BEAR</option>
          </select>
          <button type="submit" disabled={add.isPending}>
            Add
          </button>
        </form>
      </header>

      {add.error ? (
        <div className="empty down">{(add.error as Error).message}</div>
      ) : null}

      {isLoading ? (
        <div className="empty">Loading…</div>
      ) : watches.length === 0 ? (
        <div className="empty">No watches yet. Add a symbol to start tracking.</div>
      ) : (
        <div className="grid">
          {watches.map((w) => (
            <Card
              key={w.id}
              w={w}
              onRemove={(id) => remove.mutate(id)}
              hot={hotSymbols.has(w.symbol)}
            />
          ))}
        </div>
      )}
    </>
  );
}
