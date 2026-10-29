import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { time, usd } from "../theme.js";
import { Empty, Page, PatternBadge, Skeleton, SyntheticBadge } from "../components/ui.jsx";

const KEEP = 120;
const FLUSH_MS = 250; // batch incoming events so fast replay doesn't re-render per transaction

export default function Feed() {
  const [start, setStart] = useState("2022-09-05T12:00");
  const [rate, setRate] = useState(5);
  const [running, setRunning] = useState(true);
  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({ seen: 0, flagged: 0 });
  const buffer = useRef([]);

  useEffect(() => {
    if (!running) return;
    const source = new EventSource(api.streamUrl(start, rate));
    source.onmessage = (event) => buffer.current.push(JSON.parse(event.data));
    const timer = setInterval(() => {
      if (!buffer.current.length) return;
      const batch = buffer.current.reverse();
      buffer.current = [];
      setRows((prev) => [...batch, ...prev].slice(0, KEEP));
      setCounts((c) => ({
        seen: c.seen + batch.length,
        flagged: c.flagged + batch.filter((tx) => tx.rules.length).length,
      }));
    }, FLUSH_MS);
    return () => {
      source.close();
      clearInterval(timer);
    };
  }, [start, rate, running]);

  function restart(newStart) {
    setRows([]);
    setCounts({ seen: 0, flagged: 0 });
    setStart(newStart);
  }

  return (
    <Page
      title="Live transaction feed"
      subtitle="The dataset replayed in time order. Transfers covered by a detection alert flash red; simulated rings flash amber."
    >
      <div className="controls">
        <label>
          Replay from
          <input type="datetime-local" value={start} min="2022-09-01T00:00" max="2022-09-18T16:00"
                 onChange={(e) => e.target.value && restart(e.target.value)} />
        </label>
        <label>
          Speed
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))}>
            {[1, 5, 20, 50].map((r) => <option key={r} value={r}>{r} tx/s</option>)}
          </select>
        </label>
        <button className="btn" onClick={() => setRunning(!running)}>{running ? "⏸ Pause" : "▶ Resume"}</button>
        <span className="muted" style={{ marginLeft: "auto" }}>
          {running && <span className="live-dot" />}
          {counts.seen.toLocaleString()} streamed · <span style={{ color: "var(--danger)" }}>{counts.flagged.toLocaleString()} flagged</span>
        </span>
      </div>
      <div className="card flush">
        <div className="feed">
          <div className="feed-row head">
            <span>Time</span><span>From</span><span /><span>To</span><span className="num">Amount</span><span>Flags</span>
          </div>
          {rows.map((tx) => (
            <div key={tx.tx_id} className={`feed-row ${tx.synthetic ? "synthetic" : tx.rules.length ? "flagged" : ""}`}>
              <span className="mono muted">{time(tx.timestamp)}</span>
              <Link className="mono acct" to={`/accounts/${encodeURIComponent(tx.src)}`}>{tx.src}</Link>
              <span className="arrow">→</span>
              <Link className="mono acct" to={`/accounts/${encodeURIComponent(tx.dst)}`}>{tx.dst}</Link>
              <span className="num" style={{ fontWeight: 600 }} title={`${tx.amount.toLocaleString()} ${tx.currency}`}>{usd(tx.amount_usd)}</span>
              <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {tx.synthetic && <SyntheticBadge />}
                {tx.rules.map((r) => <PatternBadge key={r} pattern={r} />)}
              </span>
            </div>
          ))}
          {!rows.length && running && (
            <div style={{ padding: 16, display: "grid", gap: 14 }}>
              {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={18} />)}
            </div>
          )}
          {!rows.length && !running && <Empty icon="⏸" title="Feed paused">Press Resume to keep streaming.</Empty>}
        </div>
      </div>
    </Page>
  );
}
