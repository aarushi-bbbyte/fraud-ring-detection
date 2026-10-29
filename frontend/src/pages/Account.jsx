import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Graph from "../components/Graph.jsx";
import { api, time, usd, RULE_LABEL } from "../api.js";

export default function Account() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.account(id).then(setData).catch((e) => setError(e.message));
  }, [id]);

  const graph = useMemo(() => {
    if (!data) return null;
    const { nodes, edges } = data.neighbourhood;
    return {
      nodes: nodes.map((n) => ({ id: n.id, kind: n.id === id ? "focus" : "other" })),
      edges: edges.map((e) => ({
        id: String(e.tx_id), source: e.source, target: e.target, flagged: e.rules.length > 0,
        label: usd(e.amount_usd),
      })),
    };
  }, [data, id]);

  const openAccount = useCallback((acc) => navigate(`/accounts/${encodeURIComponent(acc)}`), [navigate]);

  if (error) return <p className="banner error">{error}</p>;
  if (!data) return <p className="muted">Loading account…</p>;

  const a = data.account;
  const transfers = [...data.neighbourhood.edges].sort((x, y) => y.timestamp.localeCompare(x.timestamp));

  return (
    <>
      <h1 className="mono">{a.id}</h1>
      <div className="stats" style={{ marginBottom: 16 }}>
        <div className="stat">
          <div className="value">{data.risk_score != null ? `${(data.risk_score * 100).toFixed(1)}%` : "–"}</div>
          <div className="label">model risk score</div>
        </div>
        <div className="stat"><div className="value">{a.in_degree ?? "–"}</div><div className="label">incoming transfers</div></div>
        <div className="stat"><div className="value">{a.out_degree ?? "–"}</div><div className="label">outgoing transfers</div></div>
        <div className="stat"><div className="value">{data.alerts.length}</div><div className="label">alerts</div></div>
      </div>
      <div className="grid2">
        <div>
          <Graph nodes={graph.nodes} edges={graph.edges} onNodeClick={openAccount} />
          <p className="muted">Most recent transfers in and out (up to 25 each).</p>
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Why it was flagged</h2>
          {data.alerts.length === 0 && <p className="muted">No detection rule flagged this account.</p>}
          {data.alerts.map((al) => (
            <div key={al.id} className="reason">
              <span className="badge rule">{RULE_LABEL[al.rule]}</span>
              <span className="muted">as {al.role}</span> — {al.reason}{" "}
              {al.ring && <Link to={`/rings/${encodeURIComponent(al.ring)}`}>ring →</Link>}
            </div>
          ))}
        </div>
      </div>
      <h2>Recent transfers</h2>
      <table>
        <thead>
          <tr><th>Time</th><th>From</th><th>To</th><th className="num">Amount (USD)</th><th>Flags</th></tr>
        </thead>
        <tbody>
          {transfers.map((e) => (
            <tr key={e.tx_id} className={e.rules.length ? "flagged" : ""}>
              <td className="mono">{time(e.timestamp)}</td>
              <td className="mono">{e.source === id ? "this account" : <Link to={`/accounts/${encodeURIComponent(e.source)}`}>{e.source}</Link>}</td>
              <td className="mono">{e.target === id ? "this account" : <Link to={`/accounts/${encodeURIComponent(e.target)}`}>{e.target}</Link>}</td>
              <td className="num">{usd(e.amount_usd)}</td>
              <td>{e.rules.map((r) => <span key={r} className="badge flag">{RULE_LABEL[r]}</span>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
