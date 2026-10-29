import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import FlowGraph from "../components/FlowGraph.jsx";
import { api } from "../api.js";
import { riskColor, time, usd } from "../theme.js";
import { Empty, Page, PatternBadge, Skeleton } from "../components/ui.jsx";

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
      links: edges.map((e) => ({
        id: String(e.tx_id), source: e.source, target: e.target, amount: e.amount_usd,
        timestamp: e.timestamp, flagged: e.rules.length > 0,
      })),
    };
  }, [data, id]);

  const openAccount = useCallback((acc) => navigate(`/accounts/${encodeURIComponent(acc)}`), [navigate]);

  if (error) {
    return (
      <Page title="Account not found">
        <div className="card"><Empty icon="🔍" title="No account with this ID"><Link to="/alerts">Back to alerts</Link></Empty></div>
      </Page>
    );
  }
  if (!data) {
    return (
      <Page title="Loading account…">
        <div className="tiles">{Array.from({ length: 4 }, (_, i) => <div key={i} className="tile"><Skeleton height={30} width="50%" /></div>)}</div>
        <Skeleton height={600} />
      </Page>
    );
  }

  const a = data.account;
  const risk = data.risk_score;
  const transfers = [...data.neighbourhood.edges].sort((x, y) => y.timestamp.localeCompare(x.timestamp));

  return (
    <Page title={<span className="mono" style={{ fontSize: 26 }}>{a.id}</span>} subtitle={`Bank ${a.bank} · most recent transfers in and out (up to 25 each)`}>
      <div className="tiles">
        <div className="tile">
          <div className="value" style={{ color: risk != null ? riskColor(risk) : undefined }}>
            {risk != null ? `${(risk * 100).toFixed(1)}%` : "–"}
          </div>
          <div className="label">model risk score</div>
        </div>
        <div className="tile"><div className="value">{a.in_degree?.toLocaleString() ?? "–"}</div><div className="label">incoming transfers</div></div>
        <div className="tile"><div className="value">{a.out_degree?.toLocaleString() ?? "–"}</div><div className="label">outgoing transfers</div></div>
        <div className="tile"><div className="value" style={{ color: data.alerts.length ? "var(--danger)" : "var(--safe)" }}>{data.alerts.length}</div><div className="label">alerts</div></div>
      </div>
      <div className="grid2">
        <FlowGraph nodes={graph.nodes} links={graph.links} onNodeClick={openAccount} height={520} />
        <div className="card" style={{ alignSelf: "start" }}>
          <h2>Why it was flagged</h2>
          {data.alerts.length === 0 && <Empty icon="🟢" title="Not flagged">No detection rule flagged this account.</Empty>}
          {data.alerts.map((al) => (
            <div key={al.id} className="reason-item">
              <PatternBadge pattern={al.rule} /> <span className="muted">as {al.role}</span>
              <div style={{ marginTop: 6 }}>{al.reason}</div>
              {al.ring && <div className="meta"><Link to={`/rings/${encodeURIComponent(al.ring)}`}>Open ring →</Link></div>}
            </div>
          ))}
        </div>
      </div>
      <h2 style={{ marginTop: 28 }}>Recent transfers</h2>
      <div className="card flush">
        <table>
          <thead><tr><th>Time</th><th>From</th><th>To</th><th className="num">Amount</th><th>Flags</th></tr></thead>
          <tbody>
            {transfers.map((e) => (
              <tr key={e.tx_id} style={e.rules.length ? { background: "var(--danger-soft)" } : undefined}>
                <td className="mono muted">{time(e.timestamp)}</td>
                <td className="mono">{e.source === id ? <span className="muted">this account</span> : <Link to={`/accounts/${encodeURIComponent(e.source)}`}>{e.source}</Link>}</td>
                <td className="mono">{e.target === id ? <span className="muted">this account</span> : <Link to={`/accounts/${encodeURIComponent(e.target)}`}>{e.target}</Link>}</td>
                <td className="num" style={{ fontWeight: 600 }}>{usd(e.amount_usd)}</td>
                <td>{e.rules.map((r) => <PatternBadge key={r} pattern={r} />)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {transfers.length === 0 && <Empty icon="💤" title="No transfers">This account hasn't sent or received money (excluding self-transfers).</Empty>}
      </div>
    </Page>
  );
}
