import { useState } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, RULE_LABEL } from "./api.js";
import Feed from "./pages/Feed.jsx";
import Alerts from "./pages/Alerts.jsx";
import Ring from "./pages/Ring.jsx";
import Account from "./pages/Account.jsx";
import Metrics from "./pages/Metrics.jsx";

// The demo control lives in the top bar so it's reachable from every page.
function SimulateButton({ onResult }) {
  const [pattern, setPattern] = useState("cycle");
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    const started = performance.now();
    try {
      const result = await api.simulate(pattern);
      onResult({ ...result, elapsed: (performance.now() - started) / 1000 });
    } catch (e) {
      onResult({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="simulate">
      <select value={pattern} onChange={(e) => setPattern(e.target.value)} aria-label="Ring pattern">
        <option value="cycle">Cycle</option>
        <option value="fan_in">Fan-in</option>
        <option value="fan_out">Fan-out</option>
      </select>
      <button className="primary" onClick={run} disabled={busy}>
        {busy ? "Injecting…" : "Simulate fraud ring"}
      </button>
    </div>
  );
}

function SimulationBanner({ result, onClose }) {
  if (!result) return null;
  if (result.error) {
    return (
      <div className="banner error">
        Simulation failed: {result.error}
        <button className="link" onClick={onClose}>dismiss</button>
      </div>
    );
  }
  const ring = result.rings[0];
  return (
    <div className="banner">
      <span className="badge sim">synthetic</span>
      <span>
        {RULE_LABEL[result.pattern]} ring of {result.accounts.length} accounts injected —{" "}
        <strong>{result.alerts.length ? "alert raised" : "no alert raised"}</strong> in {result.elapsed.toFixed(1)} s.
      </span>
      {ring && <Link to={`/rings/${encodeURIComponent(ring)}`}>View ring →</Link>}
      <Link to="/alerts?sort=recent">See in alerts</Link>
      <button className="link" onClick={onClose}>dismiss</button>
    </div>
  );
}

export default function App() {
  const [simulation, setSimulation] = useState(null);

  return (
    <>
      <header className="topbar">
        <span className="brand">Fraud Ring Monitor</span>
        <nav className="nav">
          <NavLink to="/feed">Live feed</NavLink>
          <NavLink to="/alerts">Alerts</NavLink>
          <NavLink to="/metrics">Metrics</NavLink>
        </nav>
        <SimulateButton onResult={setSimulation} />
      </header>
      {simulation && <div style={{ height: 12 }} />}
      <SimulationBanner result={simulation} onClose={() => setSimulation(null)} />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/alerts" replace />} />
          <Route path="/feed" element={<Feed />} />
          <Route path="/alerts" element={<Alerts refreshKey={simulation?.alerts?.[0]} />} />
          <Route path="/rings/:id" element={<Ring />} />
          <Route path="/accounts/:id" element={<Account />} />
          <Route path="/metrics" element={<Metrics />} />
        </Routes>
      </main>
    </>
  );
}
