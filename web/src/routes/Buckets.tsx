// Candidate-basket editor (Phase 5 — DESIGN.md §16). Left rail lists the 80
// buckets; right pane lets the user add/remove ETFs from the selected bucket's
// candidate basket and trigger an on-demand PCA refit (no need to wait for the
// quarterly cron).
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type BucketCandidate,
  type BucketDetail,
  type BucketSummary,
} from "../lib/api";

function PcaCohesion({ x }: { x: number | null }) {
  if (x == null) return <span className="muted mono">no PCA yet</span>;
  const pct = (x * 100).toFixed(1);
  const tone = x >= 0.85 ? "up" : x >= 0.5 ? "warn-text" : "down";
  return <span className={`mono ${tone}`}>{pct}% PC1</span>;
}

function BucketRow({ b, selected, onClick }:
                   { b: BucketSummary; selected: boolean; onClick: () => void }) {
  return (
    <li className={`bucket-row${selected ? " selected" : ""}`} onClick={onClick}>
      <div className="bucket-label">
        {b.label}
        <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>
          {b.kind}
        </span>
      </div>
      <div className="bucket-meta">
        <span className="mono ticker">{b.representative_symbol ?? "—"}</span>
        <PcaCohesion x={b.pc1_var_explained} />
      </div>
    </li>
  );
}

function CandidateRow({ c, bucketId, canRemove }:
                      { c: BucketCandidate; bucketId: number; canRemove: boolean }) {
  const qc = useQueryClient();
  const delM = useMutation({
    mutationFn: () => api.removeCandidate(bucketId, c.symbol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket", bucketId] });
      qc.invalidateQueries({ queryKey: ["buckets"] });
    },
  });
  return (
    <tr className={c.is_representative ? "rep-row" : ""}>
      <td className="mono">{c.symbol}</td>
      <td className="mono num">
        {c.pc1_loading == null ? "—" : c.pc1_loading.toFixed(3)}
      </td>
      <td className="muted">{c.last_pca_at ? new Date(c.last_pca_at).toLocaleDateString() : "—"}</td>
      <td>
        {c.is_representative ? (
          <span className="rep-chip">rep</span>
        ) : canRemove ? (
          <button onClick={() => delM.mutate()} disabled={delM.isPending}>
            {delM.isPending ? "…" : "remove"}
          </button>
        ) : null}
      </td>
    </tr>
  );
}

function BucketDetailPane({ bucket }: { bucket: BucketDetail }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");

  const addM = useMutation({
    mutationFn: () => api.addCandidate(bucket.id, draft.trim().toUpperCase()),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey: ["bucket", bucket.id] });
      qc.invalidateQueries({ queryKey: ["buckets"] });
    },
  });
  const refitM = useMutation({
    mutationFn: () => api.refitPca(bucket.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket", bucket.id] });
      qc.invalidateQueries({ queryKey: ["buckets"] });
    },
  });

  return (
    <div className="bucket-detail">
      <header>
        <div>
          <h3>{bucket.label}</h3>
          <div className="muted" style={{ fontSize: 12 }}>
            {bucket.kind} · rep <span className="mono">{bucket.representative_symbol ?? "—"}</span> · <PcaCohesion x={bucket.pc1_var_explained} />
            {bucket.selected_at ? (
              <> · last PCA {new Date(bucket.selected_at).toLocaleDateString()}</>
            ) : null}
          </div>
        </div>
        <button
          className="refit-btn"
          onClick={() => refitM.mutate()}
          disabled={refitM.isPending}
        >
          {refitM.isPending ? "Refitting…" : "Refit PCA"}
        </button>
      </header>
      {refitM.error ? (
        <div className="empty down">{(refitM.error as Error).message}</div>
      ) : null}

      <form
        className="add-candidate"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) addM.mutate();
        }}
      >
        <input
          placeholder="ETF symbol (e.g. SOXX)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" disabled={!draft.trim() || addM.isPending}>
          {addM.isPending ? "Adding…" : "Add candidate"}
        </button>
      </form>
      {addM.error ? (
        <div className="empty down">{(addM.error as Error).message}</div>
      ) : null}

      <table className="candidates-table">
        <thead>
          <tr><th>Symbol</th><th className="num">|PC1 loading|</th><th>Last PCA</th><th></th></tr>
        </thead>
        <tbody>
          {bucket.candidates.map((c) => (
            <CandidateRow key={c.instrument_id} c={c} bucketId={bucket.id}
                          canRemove={!c.is_representative} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Buckets() {
  const buckets = useQuery({ queryKey: ["buckets"], queryFn: api.buckets });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Auto-select the first bucket once loaded.
  if (selectedId == null && buckets.data && buckets.data.length > 0) {
    setSelectedId(buckets.data[0].id);
  }

  const detail = useQuery({
    queryKey: ["bucket", selectedId ?? -1],
    queryFn: () => api.bucket(selectedId!),
    enabled: selectedId != null,
  });

  return (
    <div className="buckets-page">
      <header className="page-head">
        <Link to="/" className="backlink">← watchlist</Link>
        <h2>Factor buckets — candidate-basket editor</h2>
        <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
          Add/remove ETFs from a bucket. PCA picks the rep with the highest |PC1 loading|.
        </span>
      </header>
      <div className="buckets-layout">
        <aside>
          {buckets.isLoading ? (
            <div className="empty">Loading buckets…</div>
          ) : (
            <ul className="bucket-list">
              {(buckets.data ?? []).map((b) => (
                <BucketRow
                  key={b.id} b={b}
                  selected={b.id === selectedId}
                  onClick={() => setSelectedId(b.id)}
                />
              ))}
            </ul>
          )}
        </aside>
        <section>
          {detail.isLoading || !detail.data ? (
            <div className="empty">Pick a bucket on the left.</div>
          ) : (
            <BucketDetailPane bucket={detail.data} />
          )}
        </section>
      </div>
    </div>
  );
}
