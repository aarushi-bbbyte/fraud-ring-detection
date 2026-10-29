import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import FlowGraph from "../components/FlowGraph.jsx";
import { api } from "../api.js";
import { time, usd, usdShort } from "../theme.js";
import { Empty, Page, PatternBadge, RiskMeter, Skeleton, SyntheticBadge } from "../components/ui.jsx";

export default function Ring() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.ring(id).then(setData).catch((e) => setError(e.message));
  }, [id]);

  const graph = useMemo(() => {
    if (!data) return null;
    return {
      nodes: data.nodes.map((n) => ({ id: n.id, kind: n.core ? "core" : "other" })),
      links: data.edges.map((e) => ({
        id: String(e.tx_id), source: e.source, target: e.target, amount: e.amount_usd,
        timestamp: e.timestamp, flagged: true,
      })),
    };
  }, [data]);

  const openAccount = useCallback((acc) => navigate(`/accounts/${encodeURIComponent(acc)}`), [navigate]);

  if (error) {
    return (
      <Page title="Ring not found">
        <div className="card"><Empty icon="🔍" title="This ring doesn't exist (any more)">
          Rings are rebuilt on each detection run, and simulated rings are removed on cleanup.{" "}
          <Link to="/alerts">Back to alerts</Link>
        </Empty></div>
      </Page>
    );
  }

  if (!data) {
    return (
      <Page title="Loading ring…">
        <div className="tiles">{Array.from({ length: 4 }, (_, i) => <div key={i} className="tile"><Skeleton height={30} width="50%" /><Skeleton style={{ marginTop: 8 }} width="70%" /></div>)}</div>
        <div className="grid2"><Skeleton height={600} /><Skeleton height={600} /></div>
      </Page>
    );
  }

  const synthetic = data.nodes.some((n) => n.bank === "SIM");
  const rules = [...new Set(data.alerts.map((a) => a.rule))];

  return (
    <Page
      title={<span style={{ display: "inline-flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        Ring {data.ring.id.replace(/^ring-/, "")}
        {rules.map((r) => <PatternBadge key={r} pattern={r} />)}
        {synthetic && <SyntheticBadge />}
      </span>}
      subtitle="Accounts linked by the transfers that triggered these alerts. Money flows along the arrows."
    >
      <div className="tiles">
        <div className="tile"><div className="value">{data.ring.size}</div><div className="label">accounts</div></div>
        <div className="tile"><div className="value">{data.ring.alert_count}</div><div className="label">alerts</div></div>
        <div className="tile"><div className="value" style={{ color: "var(--danger)" }}>{usdShort(data.ring.total_usd)}</div><div className="label">flagged volume</div></div>
        <div className="tile"><div className="value">{data.edges.length}</div><div className="label">transfers</div></div>
      </div>
      <div className="grid2">
        <div>
          <FlowGraph nodes={graph.nodes} links={graph.links} onNodeClick={openAccount} />
          {data.truncated && <p className="muted">Showing the first {data.edges.length} transfers.</p>}
        </div>
        <div className="stack" style={{ alignContent: "start" }}>
          <div className="card">
            <h2>Why these accounts were flagged</h2>
            {data.alerts.map((a) => (
              <div key={a.id} className="reason-item">
                <PatternBadge pattern={a.rule} /> <span style={{ marginLeft: 6 }}>{a.reason}</span>
                <div className="meta">{time(a.start)} → {time(a.end)} · {usd(a.total_usd)}</div>
              </div>
            ))}
          </div>
          <div className="card flush">
            <div style={{ padding: "18px 20px 6px" }}><h2 style={{ margin: 0 }}>Accounts</h2></div>
            <table>
              <tbody>
                {[...data.nodes]
                  .sort((a, b) => b.core - a.core || (b.risk_score ?? 0) - (a.risk_score ?? 0))
                  .slice(0, 30)
                  .map((n) => (
                    <tr key={n.id}>
                      <td className="mono"><Link to={`/accounts/${encodeURIComponent(n.id)}`}>{n.id}</Link>
                        <div className="muted" style={{ fontFamily: "var(--font)", fontSize: 13 }}>{n.roles.join(", ")}</div></td>
                      <td style={{ width: 150 }}><RiskMeter value={n.risk_score} /></td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {data.nodes.length > 30 && <p className="muted" style={{ padding: "0 20px 14px" }}>and {data.nodes.length - 30} more</p>}
          </div>
        </div>
      </div>
    </Page>
  );
}
