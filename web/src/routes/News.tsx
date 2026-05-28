// Global news + social feed (DESIGN.md §11.B). Union of Massive headlines and
// curated X posts across the active watchlist. Source / sentiment / relevance
// filters mirror the API query params; the rail appends live items from the
// `news` Socket.IO channel without a refetch.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type NewsItem } from "../lib/api";
import { onNews } from "../lib/socket";
import { NewsList } from "../components/NewsList";

type Source = "all" | "news" | "x";
type Sent = "any" | "pos" | "neg";

export function News() {
  const [source, setSource] = useState<Source>("all");
  const [sentiment, setSentiment] = useState<Sent>("any");
  const [minRel, setMinRel] = useState<number>(0.5);
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["news", source, sentiment, minRel],
    queryFn: () => api.news({ source, sentiment, min_relevance: minRel, limit: 100 }),
    refetchInterval: 60_000,
  });

  // Live rail: prepend items pushed on the `news` channel; dedupe by (kind,id).
  useEffect(() => {
    return onNews((n) => {
      qc.setQueryData<NewsItem[]>(
        ["news", source, sentiment, minRel],
        (prev) => {
          if (!prev) return [n as NewsItem];
          if (prev.some((x) => x.kind === n.kind && x.id === n.id)) return prev;
          if ((source !== "all" && n.kind !== source)) return prev;
          if (n.relevance < minRel) return prev;
          if (sentiment === "pos" && n.sentiment <= 0) return prev;
          if (sentiment === "neg" && n.sentiment >= 0) return prev;
          return [n as NewsItem, ...prev].slice(0, 200);
        },
      );
    });
  }, [qc, source, sentiment, minRel]);

  return (
    <div className="news-page">
      <header className="page-head">
        <Link to="/" className="backlink">← watchlist</Link>
        <h2>News & Social</h2>
        <div className="filters">
          <label>
            Source:
            <select value={source} onChange={(e) => setSource(e.target.value as Source)}>
              <option value="all">All</option>
              <option value="news">News only</option>
              <option value="x">X only</option>
            </select>
          </label>
          <label>
            Sentiment:
            <select value={sentiment} onChange={(e) => setSentiment(e.target.value as Sent)}>
              <option value="any">Any</option>
              <option value="pos">Positive</option>
              <option value="neg">Negative</option>
            </select>
          </label>
          <label>
            Min relevance:
            <input
              type="number" min={0} max={1} step={0.05} value={minRel}
              onChange={(e) => setMinRel(Number(e.target.value))}
            />
          </label>
        </div>
      </header>
      {q.isLoading ? (
        <div className="empty">Loading…</div>
      ) : q.error ? (
        <div className="empty down">{(q.error as Error).message}</div>
      ) : (
        <NewsList items={q.data ?? []} empty="No items match the current filters." />
      )}
    </div>
  );
}
