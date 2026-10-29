import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, time, usd, RULE_LABEL } from "../api.js";

const KEEP = 200;

export default function Feed() {
  const [start, setStart] = useState("2022-09-05T12:00");
  const [rate, setRate] = useState(5);
  const [running, setRunning] = useState(true);
  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({ seen: 0, flagged: 0 });

  useEffect(() => {
    if (!running) return;
    const source = new EventSource(api.streamUrl(start, rate));
    source.onmessage = (event) => {
      const tx = JSON.parse(event.data);
      setRows((prev) => [tx, ...prev].slice(0, KEEP));
      setCounts((c) => ({ seen: c.seen + 1, flagged: c.flagged + (tx.rules.length ? 1 : 0) }));
    };
    return () => source.close();
  }, [start, rate, running]);

  function restart(newStart) {
    setRows([]);
    setCounts({ seen: 0, flagged: 0 });
    setStart(newStart);
  }

  return (
    <>
      <h1>Live transaction feed</h1>
      <div className="controls">
        <label>
          Replay from{" "}
          <input type="datetime-local" value={start} min="2022-09-01T00:00" max="2022-09-18T16:00"
                 onChange={(e) => e.target.value && restart(e.target.value)} />
        </label>
        <label>
          Speed{" "}
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))}>
            {[1, 5, 20, 50].map((r) => <option key={r} value={r}>{r} tx/s</option>)}
          </select>
        </label>
        <button onClick={() => setRunning(!running)}>{running ? "Pause" : "Resume"}</button>
        <span className="muted">
          {counts.seen.toLocaleString()} shown · {counts.flagged.toLocaleString()} flagged by a rule
        </span>
      </div>
      <p className="muted">
        Replays the dataset in time order. Transfers covered by a detection alert are highlighted;
        simulated rings appear here as soon as they're injected.
      </p>
      <table>
        <thead>
          <tr>
            <th>Time</th><th>From</th><th>To</th><th className="num">Amount (USD)</th><th>Paid</th><th>Flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((tx) => (
            <tr key={tx.tx_id} className={tx.synthetic ? "synthetic" : tx.rules.length ? "flagged" : ""}>
              <td className="mono">{time(tx.timestamp)}</td>
              <td className="mono"><Link to={`/accounts/${encodeURIComponent(tx.src)}`}>{tx.src}</Link></td>
              <td className="mono"><Link to={`/accounts/${encodeURIComponent(tx.dst)}`}>{tx.dst}</Link></td>
              <td className="num">{usd(tx.amount_usd)}</td>
              <td className="muted">{tx.amount.toLocaleString()} {tx.currency}</td>
              <td>
                {tx.synthetic && <span className="badge sim">synthetic</span>}
                {tx.rules.map((r) => <span key={r} className="badge flag">{RULE_LABEL[r]}</span>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <p className="muted">{running ? "Waiting for transactions…" : "Paused."}</p>}
    </>
  );
}
