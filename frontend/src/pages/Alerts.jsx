import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, time, usd, RULE_LABEL } from "../api.js";

const PAGE = 50;
const POLL_MS = 4000;

export default function Alerts({ refreshKey }) {
  const [params, setParams] = useSearchParams();
  const sort = params.get("sort") || "risk";
  const rule = params.get("rule") || "";
  const page = Number(params.get("page") || 0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
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
  }, [sort, rule, page, refreshKey]);

  const set = (key, value) => {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  return (
    <>
      <h1>Alerts</h1>
      <div className="controls">
        <label>
          Sort{" "}
          <select value={sort} onChange={(e) => set("sort", e.target.value)}>
            <option value="risk">Highest risk first</option>
            <option value="recent">Most recent first</option>
          </select>
        </label>
        <label>
          Rule{" "}
          <select value={rule} onChange={(e) => set("rule", e.target.value)}>
            <option value="">All</option>
            {Object.entries(RULE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {data && <span className="muted">{data.total.toLocaleString()} alerts</span>}
      </div>
      {error && <p className="banner error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th className="num">Risk</th><th>Rule</th><th>Why it was flagged</th>
            <th className="num">Total (USD)</th><th>Window</th><th>Ring</th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((a) => (
            <tr key={a.id} className={a.synthetic ? "synthetic" : ""}>
              <td className="num">{(a.risk * 100).toFixed(1)}%</td>
              <td>
                <span className="badge rule">{RULE_LABEL[a.rule]}</span>
                {a.synthetic && <span className="badge sim">synthetic</span>}
              </td>
              <td>{a.reason}</td>
              <td className="num">{usd(a.total_usd)}</td>
              <td className="mono">{time(a.start)}<br />{time(a.end)}</td>
              <td>{a.ring && <Link to={`/rings/${encodeURIComponent(a.ring)}`}>open</Link>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="controls" style={{ marginTop: 12 }}>
        <button disabled={page === 0} onClick={() => set("page", String(page - 1))}>← Previous</button>
        <span className="muted">Page {page + 1}</span>
        <button disabled={!data || (page + 1) * PAGE >= data.total} onClick={() => set("page", String(page + 1))}>
          Next →
        </button>
      </div>
      <p className="muted">
        Risk is the model's risk score where available, otherwise the rule's measured precision on the labelled data.
      </p>
    </>
  );
}
