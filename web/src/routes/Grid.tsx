// Watchlist Grid — default route `/` (DESIGN.md §11.A).
// Phase 0: one card per watch with live last price (via Socket.IO tick channel),
// direction badge, spread, and an add/remove form. News mini-stack, sparkline,
// volume-z and adverse dot arrive in later phases.
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Watch, type Snapshot } from "../lib/api";
import { onTick } from "../lib/socket";

function spreadBps(s: Snapshot | null): number | null {
  if (!s || s.bid == null || s.ask == null || s.last == null || s.last === 0) return null;
  return ((s.ask - s.bid) / s.last) * 10_000;
}

function Card({ w, onRemove }: { w: Watch; onRemove: (id: number) => void }) {
  const [snap, setSnap] = useState<Snapshot | null>(w.snapshot);
  useEffect(() => onTick(w.symbol, (q) => setSnap(q)), [w.symbol]);

  const bps = spreadBps(snap);
  return (
    <div className="card" onClick={() => (window.location.href = `/instrument/${w.symbol}`)}>
      <div className="row">
        <span className="sym">
          {w.symbol} {w.direction === "BULL" ? "🐂" : "🐻"}
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
        <h1>Deleveraging Watch</h1>
        <span className="badge">
          <span className={`dot ${feedStatus}`} /> feed: {feedStatus}
          {health?.feed.last_tick_age_s != null
            ? ` (${health.feed.last_tick_age_s.toFixed(0)}s)`
            : ""}
        </span>
        <span className="badge">adapter: {health?.feed.adapter ?? "—"}</span>
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
            <Card key={w.id} w={w} onRemove={(id) => remove.mutate(id)} />
          ))}
        </div>
      )}
    </>
  );
}
