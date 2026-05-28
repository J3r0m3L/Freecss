// "Related market notes" panel (DESIGN.md §11.D, §7.1). Global notes whose
// FinBERT embedding has cosine ≥ 0.55 with this instrument's profile embedding.
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function RelatedNotes({ symbol, cosineMin = 0.55 }:
                             { symbol: string; cosineMin?: number }) {
  const q = useQuery({
    queryKey: ["related-notes", symbol, cosineMin],
    queryFn: () => api.relatedNotes(symbol, cosineMin),
  });

  if (q.isLoading) return <div className="muted">Loading related notes…</div>;
  const items = q.data ?? [];
  if (items.length === 0) {
    return (
      <div className="empty" style={{ padding: "12px 0", fontSize: 12 }}>
        No global notes match this symbol's profile (cosine ≥ {cosineMin}).
      </div>
    );
  }
  return (
    <div className="related-notes">
      <h4>Related market notes</h4>
      <ul>
        {items.map((n) => (
          <li key={n.id}>
            <div className="meta">
              <span className="ts">{new Date(n.ts).toLocaleDateString()}</span>
              <span className="cosine mono">cos {n.cosine.toFixed(2)}</span>
            </div>
            <pre>{n.body}</pre>
          </li>
        ))}
      </ul>
    </div>
  );
}
