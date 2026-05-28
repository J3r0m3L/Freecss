// Shared news/social row component (DESIGN.md §11.B, §11.C #4). One renderer
// for both Massive headlines (kind='news') and X tweets (kind='x') — payload
// shape is uniform.
import type { NewsItem, SentimentLabel } from "../lib/api";
import { api } from "../lib/api";

function sentChip(label: SentimentLabel, score: number) {
  const tone = label === "positive" ? "pos" : label === "negative" ? "neg" : "neu";
  const arrow = label === "positive" ? "↑" : label === "negative" ? "↓" : "·";
  return (
    <span className={`sent ${tone}`} title={`sentiment ${score.toFixed(2)}`}>
      {arrow} {Math.abs(score).toFixed(2)}
    </span>
  );
}

export function NewsRow({ item }: { item: NewsItem }) {
  const time = new Date(item.posted_at).toLocaleTimeString();
  const headline = item.title ?? item.body.slice(0, 200);
  const saveLabel = item.kind === "news" ? "Save to notes" : "Save tweet";

  async function save() {
    try {
      if (item.kind === "news") await api.noteFromNews(item.id);
      else await api.noteFromSocial(item.id);
      window.alert("Saved to notes.");
    } catch (e) {
      window.alert(`Save failed: ${(e as Error).message}`);
    }
  }

  return (
    <article className={`news-row ${item.kind}`}>
      <header>
        <span className={`kind ${item.kind}`}>{item.kind === "news" ? "📰" : "𝕏"}</span>
        <span className="ts">{time}</span>
        {sentChip(item.sentiment_label, item.sentiment)}
        <span className="rel" title={`relevance via ${item.relevance_source}`}>
          rel {item.relevance.toFixed(2)} <em>{item.relevance_source}</em>
        </span>
        {item.tickers.slice(0, 4).map((t) => (
          <span key={t} className="ticker">${t}</span>
        ))}
      </header>
      <h4>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noreferrer">{headline}</a>
        ) : (
          headline
        )}
      </h4>
      {item.kind === "news" && item.body ? <p className="snippet">{item.body}</p> : null}
      <footer>
        <span className="source">{item.source ?? "—"}</span>
        <button className="save" onClick={save}>{saveLabel}</button>
      </footer>
    </article>
  );
}

export function NewsList({ items, empty = "No matching items." }:
  { items: NewsItem[]; empty?: string }) {
  if (!items.length) return <div className="empty">{empty}</div>;
  return (
    <div className="news-list">
      {items.map((it) => <NewsRow key={`${it.kind}-${it.id}`} item={it} />)}
    </div>
  );
}
