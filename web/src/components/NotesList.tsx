// Notes list + composer (DESIGN.md §11.D). Same component renders the
// per-symbol drill-down feed and the global /notes feed; difference is what
// scope/instrument we pass to `api.notes()`.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Note } from "../lib/api";

interface Props {
  // Per-symbol mode if both are set; global mode if instrumentId is null.
  scope: "symbol" | "global";
  instrumentId?: number | null;
  // Tag the query so per-symbol and global lists invalidate independently.
  queryKey: readonly unknown[];
  emptyHint?: string;
}

function chip(note: Note): string | null {
  if (note.linked_alert_id) return `alert #${note.linked_alert_id}`;
  if (note.linked_news_id) return `news #${note.linked_news_id}`;
  if (note.linked_social_post_id) return `x #${note.linked_social_post_id}`;
  return null;
}

export function NotesList({ scope, instrumentId, queryKey, emptyHint }: Props) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");

  const q = useQuery({
    queryKey,
    queryFn: () => api.notes(
      scope === "symbol"
        ? { scope: "symbol", instrument_id: instrumentId ?? undefined }
        : { scope: "global" },
    ),
  });

  const addM = useMutation({
    mutationFn: () => api.createNote(draft.trim(),
                                     scope === "symbol" ? instrumentId : null),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey });
    },
  });
  const delM = useMutation({
    mutationFn: (id: number) => api.deleteNote(id),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  return (
    <div className="notes-block">
      <form
        className="note-composer"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) addM.mutate();
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            scope === "symbol"
              ? "Note on this symbol… (markdown, links ok)"
              : "Global market note… (auto-embedded, surfaces on related drill-downs)"
          }
          rows={2}
        />
        <button type="submit" disabled={!draft.trim() || addM.isPending}>
          {addM.isPending ? "Saving…" : "Save"}
        </button>
      </form>

      {q.isLoading ? (
        <div className="muted">Loading…</div>
      ) : (q.data ?? []).length === 0 ? (
        <div className="empty">{emptyHint ?? "No notes yet."}</div>
      ) : (
        <ul className="notes-list">
          {(q.data ?? []).map((n) => {
            const tag = chip(n);
            return (
              <li key={n.id} className="note">
                <header>
                  <span className="ts">{new Date(n.ts).toLocaleString()}</span>
                  {n.symbol ? <span className="ticker">${n.symbol}</span> : null}
                  {tag ? <span className="note-link">{tag}</span> : null}
                  <button
                    className="del"
                    onClick={() => delM.mutate(n.id)}
                    title="Delete note"
                  >
                    ✕
                  </button>
                </header>
                <pre className="body">{n.body}</pre>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
