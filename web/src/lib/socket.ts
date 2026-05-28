// Socket.IO client for live ticks/alerts/news (DESIGN.md §7.2).
import { io, type Socket } from "socket.io-client";

export const socket: Socket = io({ autoConnect: true, transports: ["polling", "websocket"] });

// Subscribe to a per-symbol tick channel; returns an unsubscribe fn.
export function onTick(symbol: string, cb: (q: TickEvent) => void): () => void {
  const evt = `tick:${symbol}`;
  socket.on(evt, cb);
  return () => socket.off(evt, cb);
}

export function onAlert(cb: (a: AlertEvent) => void): () => void {
  socket.on("alerts", cb);
  return () => socket.off("alerts", cb);
}

export function onNews(cb: (n: NewsEvent) => void): () => void {
  socket.on("news", cb);
  return () => socket.off("news", cb);
}

// Mirrors the REST NewsItem shape (DESIGN.md §7.2 news channel).
export interface NewsEvent {
  id: number;
  kind: "news" | "x";
  title: string | null;
  body: string;
  url: string | null;
  source: string | null;
  posted_at: string;
  relevance: number;
  relevance_source: "symbol" | "sector" | "semantic";
  sentiment: number;
  sentiment_label: "positive" | "negative" | "neutral";
  sentiment_conf: number;
  tickers: string[];
}

export interface TickEvent {
  symbol: string;
  ts: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  bid_size: number | null;
  ask_size: number | null;
}

export interface AlertEvent {
  id: number;
  symbol: string;
  kind: string;
  severity: "info" | "warn" | "high" | "critical";
  adverse: boolean;
  ts: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
}
