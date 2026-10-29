import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Graph from "../components/Graph.jsx";
import { api, time, usd, RULE_LABEL } from "../api.js";

export default function Ring() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    api.ring(id).then(setData).catch((e) => setError(e.message));
  }, [id]);

  const graph = useMemo(() => {
    if (!data) return null;
    return {
      nodes: data.nodes.map((n) => ({ id: n.id, kind: n.core ? "core" : "other" })),
      edges: data.edges.map((e) => ({
        id: String(e.tx_id), source: e.source, target: e.target, flagged: true,
        label: `${usd(e.amount_usd)} · ${time(e.timestamp).slice(5)}`,
      })),
    };
  }, [data]);

  const openAccount = useCallback((acc) => navigate(`/accounts/${encodeURIComponent(acc)}`), [navigate]);

  if (error) return <p className="banner error">{error}</p>;
  if (!data) return <p className="muted">Loading ring…</p>;

  const onlyCycles = data.alerts.every((a) => a.rule === "cycle");
  const synthetic = data.nodes.some((n) => n.bank === "SIM");

  return (
    <>
      <h1>
        Ring {data.ring.id} {synthetic && <span className="badge sim">synthetic</span>}
      </h1>
      <div className="stats" style={{ marginBottom: 16 }}>
        <div className="stat"><div className="value">{data.ring.size}</div><div className="label">accounts</div></div>
        <div className="stat"><div className="value">{data.ring.alert_count}</div><div className="label">alerts</div></div>
        <div className="stat"><div className="value">{usd(data.ring.total_usd)}</div><div className="label">flagged volume</div></div>
        <div className="stat"><div className="value">{data.edges.length}</div><div className="label">transfers shown</div></div>
      </div>
      <div className="grid2">
        <div>
          <Graph nodes={graph.nodes} edges={graph.edges}
                 layout={onlyCycles && data.nodes.length <= 15 ? "circle" : "cose"} onNodeClick={openAccount} />
          {data.truncated && <p className="muted">Showing the first {data.edges.length} transfers.</p>}
          <p className="muted">Arrows show the direction money moved. Click an account to open it.</p>
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Why these accounts were flagged</h2>
          {data.alerts.map((a) => (
            <div key={a.id} className="reason">
              <span className="badge rule">{RULE_LABEL[a.rule]}</span> {a.reason}
              <div className="muted mono">{time(a.start)} → {time(a.end)}</div>
            </div>
          ))}
          <h2>Accounts</h2>
          <table>
            <tbody>
              {[...data.nodes]
                .sort((a, b) => b.core - a.core || (b.risk_score ?? 0) - (a.risk_score ?? 0))
                .slice(0, 40)
                .map((n) => (
                  <tr key={n.id}>
                    <td className="mono"><Link to={`/accounts/${encodeURIComponent(n.id)}`}>{n.id}</Link></td>
                    <td>{n.roles.join(", ")}</td>
                    <td className="num">{n.risk_score != null ? `${(n.risk_score * 100).toFixed(0)}%` : ""}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          {data.nodes.length > 40 && <p className="muted">and {data.nodes.length - 40} more</p>}
        </div>
      </div>
    </>
  );
}
