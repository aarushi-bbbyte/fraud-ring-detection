import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api, flaggedVolume } from "./api.js";
import { patternInfo, usdShort } from "./theme.js";
import { AnimatedNumber } from "./components/ui.jsx";
import Feed from "./pages/Feed.jsx";
import Alerts from "./pages/Alerts.jsx";
import Ring from "./pages/Ring.jsx";
import Account from "./pages/Account.jsx";
import Metrics from "./pages/Metrics.jsx";

const PATTERNS = [
  { value: "cycle", icon: "⟳" },
  { value: "fan_in", icon: "⇥" },
  { value: "fan_out", icon: "⇤" },
];
const METRICS_POLL_MS = 8000;
const TOAST_MS = 15000;

// The demo control: a pattern picker plus a prominent trigger, reachable from every page.
function SimulateControl({ busy, onSimulate }) {
  const [pattern, setPattern] = useState("cycle");
  return (
    <div className="simulate">
      <div className="picker" role="radiogroup" aria-label="Ring pattern">
        {PATTERNS.map((p) => (
          <button key={p.value} role="radio" aria-checked={pattern === p.value}
                  className={pattern === p.value ? "on" : ""} onClick={() => setPattern(p.value)}>
            <span aria-hidden>{p.icon}</span>{patternInfo(p.value).label}
          </button>
        ))}
      </div>
      <button className="sim-button" onClick={() => onSimulate(pattern)} disabled={busy}>
        {busy ? <span className="spinner" /> : <span aria-hidden>🚨</span>}
        {busy ? "Injecting ring…" : "Simulate fraud ring"}
      </button>
    </div>
  );
}

function Counters({ metrics, flagged }) {
  const g = metrics?.graph;
  const alerts = g ? Object.values(g.alerts).reduce((a, b) => a + b, 0) : null;
  const items = [
    { icon: "⇄", tint: "var(--safe-soft)", color: "var(--safe)", value: g?.transactions, label: <><span className="live-dot" />Transactions processed</> },
    { icon: "⚠", tint: "var(--danger-soft)", color: "var(--danger)", value: alerts, label: "Active alerts" },
    { icon: "◎", tint: "var(--amber-soft)", color: "var(--amber)", value: g?.rings, label: "Rings detected" },
    { icon: "$", tint: "rgba(144, 133, 233, 0.16)", color: "#9085e9", value: flagged, label: "Money flagged (sum of alerts)", format: usdShort },
  ];
  return (
    <section className="counters" aria-label="Live totals">
      {items.map((c, i) => (
        <div className="counter" key={i}>
          <div className="icon" style={{ background: c.tint, color: c.color }} aria-hidden>{c.icon}</div>
          <div>
            <div className="value"><AnimatedNumber value={c.value} format={c.format} /></div>
            <div className="label">{c.label}</div>
          </div>
        </div>
      ))}
    </section>
  );
}

function Toasts({ toasts, onOpen, onClose }) {
  return (
    <div className="toasts" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} layout initial={{ opacity: 0, x: 60, scale: 0.96 }}
                      animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0, x: 60 }}
                      transition={{ type: "spring", stiffness: 380, damping: 30 }}>
            {t.error ? (
              <div className="toast error">
                <span className="emoji">⚠️</span>
                <div><div className="title">Simulation failed</div><div className="body">{t.error}</div></div>
                <button className="close" onClick={() => onClose(t.id)} aria-label="Dismiss">×</button>
              </div>
            ) : (
              <div className="toast" role="button" tabIndex={0} onClick={() => t.ringId && onOpen(t, "ring")}
                   onKeyDown={(e) => e.key === "Enter" && t.ringId && onOpen(t, "ring")}>
                <span className="emoji">{t.ringId ? "🚨" : "ℹ️"}</span>
                <div>
                  <div className="title">{t.title}</div>
                  <div className="body">{t.body}</div>
                  {t.ringId && (
                    <div className="actions">
                      <a onClick={(e) => { e.stopPropagation(); onOpen(t, "ring"); }}>Open ring →</a>
                      <a onClick={(e) => { e.stopPropagation(); onOpen(t, "alerts"); }}>See in alerts</a>
                    </div>
                  )}
                </div>
                <button className="close" onClick={(e) => { e.stopPropagation(); onClose(t.id); }} aria-label="Dismiss">×</button>
              </div>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState(null);
  const [baseVolume, setBaseVolume] = useState(null);
  const [extraVolume, setExtraVolume] = useState(0);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [highlight, setHighlight] = useState(null);
  const volumeStarted = useRef(false);

  const refreshMetrics = useCallback(() => api.metrics().then(setMetrics).catch(() => {}), []);

  useEffect(() => {
    refreshMetrics();
    const timer = setInterval(refreshMetrics, METRICS_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshMetrics]);

  // Flagged volume is computed once per session from the alerts present at load.
  useEffect(() => {
    if (!metrics || volumeStarted.current) return;
    volumeStarted.current = true;
    const total = Object.values(metrics.graph.alerts).reduce((a, b) => a + b, 0);
    flaggedVolume(total).then(setBaseVolume).catch(() => {});
  }, [metrics]);

  const closeToast = useCallback((id) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);

  function pushToast(toast) {
    const id = Date.now() + Math.random();
    setToasts((ts) => [...ts, { ...toast, id }].slice(-3));
    setTimeout(() => closeToast(id), TOAST_MS);
  }

  async function simulate(pattern) {
    setBusy(true);
    const started = performance.now();
    try {
      const result = await api.simulate(pattern);
      const elapsed = (performance.now() - started) / 1000;
      const ringId = result.rings[0];
      const label = patternInfo(result.pattern).label.toLowerCase();
      if (!ringId) {
        pushToast({ title: "Ring injected, no alert raised", body: `${result.accounts.length}-account ${label}` });
      } else {
        const ring = await api.ring(ringId).catch(() => null);
        const total = ring?.ring.total_usd ?? 0;
        setExtraVolume((v) => v + total);
        setHighlight(result.alerts[0]);
        pushToast({
          ringId,
          title: `Fraud ring detected: ${ring?.ring.size ?? result.accounts.length}-account ${label}, ${usdShort(total)}`,
          body: `Alert raised ${elapsed.toFixed(1)} s after injection. Click to investigate.`,
        });
      }
      refreshMetrics();
    } catch (e) {
      pushToast({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  function openToast(toast, where) {
    navigate(where === "ring" ? `/rings/${encodeURIComponent(toast.ringId)}` : "/alerts?sort=recent");
    closeToast(toast.id);
  }

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden>◈</span>Fraud Ring Monitor</div>
        <nav className="nav">
          <NavLink to="/feed">Live feed</NavLink>
          <NavLink to="/alerts">Alerts</NavLink>
          <NavLink to="/metrics">Metrics</NavLink>
        </nav>
        <SimulateControl busy={busy} onSimulate={simulate} />
      </header>
      <Counters metrics={metrics} flagged={baseVolume == null ? null : baseVolume + extraVolume} />
      <main>
        <AnimatePresence mode="wait">
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<Navigate to="/alerts" replace />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/alerts" element={<Alerts highlightId={highlight} />} />
            <Route path="/rings/:id" element={<Ring />} />
            <Route path="/accounts/:id" element={<Account />} />
            <Route path="/metrics" element={<Metrics metrics={metrics} />} />
          </Routes>
        </AnimatePresence>
      </main>
      <Toasts toasts={toasts} onOpen={openToast} onClose={closeToast} />
    </>
  );
}
