// Settings (DESIGN.md §11.E). Phase 2 ships the X-account editor; other panels
// (global thresholds, quiet hours, credentials presence) ride the existing
// /api/settings endpoint and will get richer controls in Phase 4.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SocialAccount } from "../lib/api";

interface SettingsResp {
  settings: Record<string, unknown>;
  credentials: Record<string, boolean>;
  data_adapter: string;
  notifier: string;
}

function CredentialsBlock({ creds }: { creds: Record<string, boolean> }) {
  return (
    <div className="creds">
      <h3>Credentials (.env presence)</h3>
      <ul>
        {Object.entries(creds).map(([k, v]) => (
          <li key={k}>
            <span className={`dot ${v ? "ok" : "missing"}`} /> {k}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AccountsBlock() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["social"], queryFn: () => api.socialAccounts(false) });
  const [handle, setHandle] = useState("");
  const [label, setLabel] = useState("");

  const addM = useMutation({
    mutationFn: () => api.addSocialAccount(handle.trim(), label.trim() || undefined),
    onSuccess: () => {
      setHandle("");
      setLabel("");
      qc.invalidateQueries({ queryKey: ["social"] });
    },
  });
  const toggleM = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.patchSocialAccount(id, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["social"] }),
  });
  const delM = useMutation({
    mutationFn: (id: number) => api.deleteSocialAccount(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["social"] }),
  });

  return (
    <div className="accounts">
      <h3>Curated X accounts</h3>
      <form
        className="add-account"
        onSubmit={(e) => {
          e.preventDefault();
          if (handle.trim()) addM.mutate();
        }}
      >
        <input
          placeholder="@handle (without @)" value={handle}
          onChange={(e) => setHandle(e.target.value)}
        />
        <input
          placeholder="Label (optional)" value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <button type="submit" disabled={!handle.trim() || addM.isPending}>
          {addM.isPending ? "Adding…" : "Add"}
        </button>
      </form>
      {addM.error ? (
        <div className="empty down">{(addM.error as Error).message}</div>
      ) : null}
      {q.isLoading ? (
        <div className="muted">Loading accounts…</div>
      ) : (
        <table className="accounts-table">
          <thead>
            <tr><th>Handle</th><th>Label</th><th>Last polled</th><th>Active</th><th></th></tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((a: SocialAccount) => (
              <tr key={a.id} className={a.active ? "" : "muted"}>
                <td>@{a.handle}</td>
                <td>{a.label ?? "—"}</td>
                <td>{a.last_polled_at ?? "never"}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={a.active}
                    onChange={(e) => toggleM.mutate({ id: a.id, active: e.target.checked })}
                  />
                </td>
                <td>
                  <button onClick={() => delM.mutate(a.id)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function Settings() {
  const q = useQuery<SettingsResp>({
    queryKey: ["settings"],
    queryFn: () => fetch("/api/settings").then((r) => r.json()),
  });
  return (
    <div className="settings-page">
      <header className="page-head">
        <Link to="/" className="backlink">← watchlist</Link>
        <h2>Settings</h2>
      </header>
      {q.isLoading || !q.data ? (
        <div className="empty">Loading…</div>
      ) : (
        <>
          <div className="row">
            <span>Data adapter: <strong>{q.data.data_adapter}</strong></span>
            <span>Notifier: <strong>{q.data.notifier}</strong></span>
          </div>
          <CredentialsBlock creds={q.data.credentials} />
          <AccountsBlock />
        </>
      )}
    </div>
  );
}
