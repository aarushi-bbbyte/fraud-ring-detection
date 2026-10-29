import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { PATTERN, time, usd } from "../theme.js";
import { Empty, Page, PatternBadge, RiskMeter, SkeletonRows, SyntheticBadge } from "../components/ui.jsx";

const PAGE = 50;
const POLL_MS = 4000;
const RULES = ["cycle", "fan_in", "fan_out"];

export default function Alerts({ highlightId }) {
  const [params, setParams] = useSearchParams();
  const sort = params.get("sort") || "risk";
  const rule = params.get("rule") || "";
  const page = Number(params.get("page") || 0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    const load = () =>
      api
        .alerts({ sort, limit: PAGE, offset: page * PAGE, ...(rule && { rule }) })
        .then((d) => !cancelled && (setData(d), setError(null)))
        .catch((e) => !cancelled && setError(e.message));
    load();
    // Poll so a simulated ring's alert shows up without a manual refresh.
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sort, rule, page]);

  const set = (key, value) => {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  return (
    <Page
      title="Alerts"
      subtitle="Every account group a detection rule flagged, with the reason in plain words."
      actions={
        <div className="controls" style={{ margin: 0 }}>
          <select value={sort} onChange={(e) => set("sort", e.target.value)} aria-label="Sort">
            <option value="risk">Highest risk first</option>
            <option value="recent">Most recent first</option>
          </select>
          <select value={rule} onChange={(e) => set("rule", e.target.value)} aria-label="Rule">
            <option value="">All rules</option>
            {RULES.map((r) => <option key={r} value={r}>{PATTERN[r].label}</option>)}
          </select>
        </div>
      }
    >
      {error && <div className="toast error" style={{ marginBottom: 16 }}>⚠️ {error}</div>}
      <div className="card flush">
        <table>
          <thead>
            <tr>
              <th style={{ width: 170 }}>Risk</th><th style={{ width: 150 }}>Pattern</th><th>Why it was flagged</th>
              <th className="num">Total</th><th>Window</th><th></th>
            </tr>
          </thead>
          <tbody>
            {!data && <SkeletonRows cols={6} />}
            {data?.items.map((a) => (
              <tr key={a.id} className={`${a.synthetic ? "synthetic" : ""} ${a.id === highlightId ? "pulse" : ""}`}>
                <td><RiskMeter value={a.risk} /></td>
                <td>
                  <div style={{ display: "grid", gap: 6, justifyItems: "start" }}>
                    <PatternBadge pattern={a.rule} />
                    {a.synthetic && <SyntheticBadge />}
                  </div>
                </td>
                <td className="reason">{a.reason}</td>
                <td className="num" style={{ fontWeight: 600 }}>{usd(a.total_usd)}</td>
                <td className="mono muted">{time(a.start)}<br />{time(a.end)}</td>
                <td>{a.ring && <Link className="btn ghost" to={`/rings/${encodeURIComponent(a.ring)}`}>Open ring →</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && (
          <Empty icon="✅" title="No alerts here">Nothing matches this filter. Try "All rules" or simulate a ring.</Empty>
        )}
        <div className="pager">
          <button className="btn" disabled={page === 0} onClick={() => set("page", String(page - 1))}>← Previous</button>
          <span className="muted">Page {page + 1}{data ? ` of ${Math.max(1, Math.ceil(data.total / PAGE)).toLocaleString()}` : ""}</span>
          <button className="btn" disabled={!data || (page + 1) * PAGE >= data.total} onClick={() => set("page", String(page + 1))}>Next →</button>
          <span className="muted" style={{ marginLeft: "auto" }}>
            {data ? `${data.total.toLocaleString()} alerts` : ""} · risk = model score, or the rule's measured precision for new alerts
          </span>
        </div>
      </div>
    </Page>
  );
}
