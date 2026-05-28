// Global notes feed (DESIGN.md §11.D /notes route). The composer here writes
// GLOBAL notes (instrument_id NULL), which the backend FinBERT-embeds on
// insert so they show up via cosine on per-symbol drill-downs.
import { Link } from "react-router-dom";
import { NotesList } from "../components/NotesList";

export function Notes() {
  return (
    <div className="notes-page">
      <header className="page-head">
        <Link to="/" className="backlink">← watchlist</Link>
        <h2>Notes — global market log</h2>
        <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
          Global notes auto-surface on related drill-downs (cosine ≥ 0.55).
        </span>
      </header>
      <NotesList
        scope="global"
        queryKey={["notes", "global"]}
        emptyHint="No global notes yet. Add one above — these surface on related drill-downs automatically."
      />
    </div>
  );
}
