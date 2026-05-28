// Factor-exposure table for the Context tab (DESIGN.md §9, §11.C).
// Shows BH-FDR-significant buckets by default, sorted by |β|. Residual is
// colored red if adverse to the watch direction, green if aligned (the cells
// to actually investigate).
import type { Exposure } from "../lib/api";

function fmtNum(x: number | null | undefined, digits = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toFixed(digits);
}

function fmtPct(x: number | null | undefined, digits = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

function fmtP(p: number | null | undefined): string {
  if (p == null) return "—";
  if (p < 0.001) return "<0.001";
  return p.toFixed(3);
}

function residualClass(direction: "BULL" | "BEAR" | undefined,
                       residual: number | null): string {
  if (residual == null || direction == null) return "";
  // Residual adverse if its sign opposes the thesis (BULL → red on negative).
  const adverse = (direction === "BULL" && residual < 0)
               || (direction === "BEAR" && residual > 0);
  return adverse ? "adverse" : "aligned";
}

export function ContextTable({
  rows, direction, significantOnly, onToggleSignificant,
}: {
  rows: Exposure[];
  direction: "BULL" | "BEAR" | undefined;
  significantOnly: boolean;
  onToggleSignificant: (v: boolean) => void;
}) {
  return (
    <>
      <div className="context-controls">
        <label>
          <input type="checkbox" checked={significantOnly}
                 onChange={(e) => onToggleSignificant(e.target.checked)} />
          Significant only (BH-FDR @ q=0.05)
        </label>
      </div>
      {rows.length === 0 ? (
        <div className="empty">
          {significantOnly
            ? "No exposures survived BH-FDR. Either factor_refresh hasn't run yet or this watch has no statistically significant factor loadings."
            : "No exposures persisted yet — factor_refresh runs at 16:30 ET daily."}
        </div>
      ) : (
        <table className="exposures-table">
          <thead>
            <tr>
              <th>Bucket</th>
              <th>Rep</th>
              <th className="num">β</th>
              <th className="num">ρ</th>
              <th className="num">R²</th>
              <th className="num">p</th>
              <th className="num">q</th>
              <th className="num">Residual today</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.bucket_id}>
                <td>
                  {r.bucket_label}
                  <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>
                    {r.bucket_kind}
                  </span>
                </td>
                <td className="mono">{r.representative}</td>
                <td className="num mono">{fmtNum(r.beta)}</td>
                <td className="num mono">{fmtNum(r.correlation)}</td>
                <td className="num mono">{fmtNum(r.r_squared)}</td>
                <td className="num mono">{fmtP(r.p_value)}</td>
                <td className="num mono">{fmtP(r.q_value)}</td>
                <td className={`num mono ${residualClass(direction, r.last_residual)}`}>
                  {fmtPct(r.last_residual)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
