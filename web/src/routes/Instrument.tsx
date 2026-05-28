// Per-symbol drill-down (`/instrument/:symbol`) — DESIGN.md §11.C.
// Phase 1: Tape tab with 1m candles (lightweight-charts) + live last-price line
// updates via Socket.IO. Microstructure / Context / News & Social / Notes /
// Earnings tabs land in their respective later phases.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { api, type Bar, type Alert } from "../lib/api";
import { onTick } from "../lib/socket";

type TabId = "tape" | "micro" | "context" | "news" | "notes" | "earnings";

function toUtc(ts: string): UTCTimestamp {
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

function TapeChart({ symbol, bars, alerts }: { symbol: string; bars: Bar[]; alerts: Alert[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const c = createChart(wrap.current, {
      layout: { background: { color: "#18181b" }, textColor: "#71717a" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#27272a" },
      width: wrap.current.clientWidth,
      height: 360,
    });
    const s = c.addCandlestickSeries({
      upColor: "#22c55e", downColor: "#ef4444",
      borderUpColor: "#22c55e", borderDownColor: "#ef4444",
      wickUpColor: "#22c55e", wickDownColor: "#ef4444",
    });
    chart.current = c;
    series.current = s;
    const ro = new ResizeObserver(() => {
      if (wrap.current && chart.current) {
        chart.current.applyOptions({ width: wrap.current.clientWidth });
      }
    });
    ro.observe(wrap.current);
    return () => {
      ro.disconnect();
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    if (!series.current) return;
    const data: CandlestickData[] = bars.map((b) => ({
      time: toUtc(b.ts),
      open: b.o, high: b.h, low: b.l, close: b.c,
    }));
    series.current.setData(data);
    if (alerts.length && chart.current) {
      series.current.setMarkers(
        alerts.slice(0, 30).map((a) => ({
          time: toUtc(a.ts) as Time,
          position: "aboveBar",
          color: a.severity === "critical" ? "#ef4444" : "#f59e0b",
          shape: "circle",
          text: `${a.kind}/${a.severity}`,
        })),
      );
    }
  }, [bars, alerts]);

  // Live last price overlays via Socket.IO — extends the most-recent candle.
  useEffect(() => {
    if (!series.current) return;
    return onTick(symbol, (q) => {
      if (!series.current || q.last == null) return;
      const ts = toUtc(q.ts);
      const last = bars[bars.length - 1];
      if (!last) return;
      const lastTs = toUtc(last.ts);
      series.current.update({
        time: ts >= lastTs ? ts : lastTs,
        open: last.o, high: Math.max(last.h, q.last), low: Math.min(last.l, q.last), close: q.last,
      });
    });
  }, [symbol, bars]);

  return <div className="chart" ref={wrap} />;
}

export function Instrument() {
  const { symbol = "" } = useParams();
  const sym = symbol.toUpperCase();
  const [tab, setTab] = useState<TabId>("tape");

  const detailQ = useQuery({ queryKey: ["instrument", sym], queryFn: () => api.instrument(sym) });
  const barsQ = useQuery({
    queryKey: ["bars", sym],
    queryFn: () => api.bars(sym, "1m"),
    refetchInterval: 60_000,
  });
  const alertsQ = useQuery({ queryKey: ["alerts"], queryFn: () => api.alerts(50) });

  const symAlerts = useMemo(
    () => (alertsQ.data ?? []).filter((a) => a.symbol === sym),
    [alertsQ.data, sym],
  );

  if (detailQ.isLoading) return <div className="empty">Loading {sym}…</div>;
  if (detailQ.error) return <div className="empty down">{(detailQ.error as Error).message}</div>;
  const d = detailQ.data!;
  const bb = d.watch?.direction === "BULL" ? "🐂" : d.watch?.direction === "BEAR" ? "🐻" : "";

  return (
    <div className="drill">
      <Link to="/" className="backlink">← watchlist</Link>
      <h2>
        {d.symbol} {bb} <span className="muted" style={{ fontSize: 13 }}>{d.display_name}</span>
      </h2>
      <div className="sub">
        {d.asset_class}
        {d.snapshot ? (
          <>
            {" · "}<span className="mono">{d.snapshot.last?.toFixed(2)}</span>
            {" · "}<span className="muted">{new Date(d.snapshot.ts).toLocaleTimeString()}</span>
          </>
        ) : null}
      </div>
      <div className="tabs">
        {(["tape", "micro", "context", "news", "notes", "earnings"] as TabId[]).map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t === "tape" ? "Tape" :
             t === "micro" ? "Microstructure" :
             t === "context" ? "Context" :
             t === "news" ? "News & Social" :
             t === "notes" ? "Notes" : "Earnings"}
          </button>
        ))}
      </div>

      {tab === "tape" ? (
        <>
          <TapeChart symbol={sym} bars={barsQ.data?.bars ?? []} alerts={symAlerts} />
          <h3 style={{ marginTop: 16, fontSize: 13, color: "var(--muted)" }}>Recent alerts</h3>
          {symAlerts.length === 0 ? (
            <div className="muted" style={{ padding: "8px 0", fontSize: 13 }}>None.</div>
          ) : (
            symAlerts.slice(0, 15).map((a) => (
              <div key={a.id} className="alert-row">
                <span className="ts">{new Date(a.ts).toLocaleTimeString()}</span>
                <span className={`sev ${a.severity}`}>{a.severity}</span>
                <span>{a.kind}</span>
                <span className="body">{JSON.stringify(a.payload)}</span>
              </div>
            ))
          )}
        </>
      ) : (
        <div className="empty">
          The {tab} tab populates in a later phase per DESIGN.md §11.C.
        </div>
      )}
    </div>
  );
}
