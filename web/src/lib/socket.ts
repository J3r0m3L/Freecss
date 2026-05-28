// Socket.IO client for live ticks/alerts/news (DESIGN.md §7.2).
import { io, type Socket } from "socket.io-client";

export const socket: Socket = io({ autoConnect: true, transports: ["polling", "websocket"] });

// Subscribe to a per-symbol tick channel; returns an unsubscribe fn.
export function onTick(symbol: string, cb: (q: TickEvent) => void): () => void {
  const evt = `tick:${symbol}`;
  socket.on(evt, cb);
  return () => socket.off(evt, cb);
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
