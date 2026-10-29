import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { patternInfo, riskColor } from "../theme.js";

export function PatternBadge({ pattern }) {
  const { label, color } = patternInfo(pattern);
  return <span className="badge" style={{ "--c": color }}>{label}</span>;
}

export function SyntheticBadge() {
  return <span className="badge sim">Simulated</span>;
}

/** Risk as a coloured bar plus the number, so colour is never the only cue. */
export function RiskMeter({ value }) {
  if (value == null) return <span className="muted">–</span>;
  const color = riskColor(value);
  return (
    <span className="risk" title={`Risk ${(value * 100).toFixed(1)}%`}>
      <span className="bar"><span style={{ width: `${Math.max(value * 100, 3)}%`, background: color }} /></span>
      <span className="val" style={{ color }}>{(value * 100).toFixed(value < 0.1 ? 1 : 0)}%</span>
    </span>
  );
}

export function Skeleton({ width = "100%", height = 16, style }) {
  return <div className="skeleton" style={{ width, height, ...style }} />;
}

export function SkeletonRows({ rows = 8, cols = 5 }) {
  return Array.from({ length: rows }, (_, i) => (
    <tr key={i}>
      {Array.from({ length: cols }, (_, j) => (
        <td key={j}><Skeleton width={j === 2 ? "90%" : "60%"} /></td>
      ))}
    </tr>
  ));
}

export function Empty({ icon = "🛰️", title, children }) {
  return (
    <div className="empty">
      <div className="icon">{icon}</div>
      <div className="title">{title}</div>
      {children && <div>{children}</div>}
    </div>
  );
}

/** Tweens from the previous value to the new one, for the live counters. */
export function AnimatedNumber({ value, format = (v) => Math.round(v).toLocaleString(), duration = 900 }) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef(value ?? 0);

  useEffect(() => {
    if (value == null) return;
    const start = performance.now();
    const begin = from.current;
    let frame;
    const step = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(begin + (value - begin) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
      else from.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      from.current = value;
    };
  }, [value, duration]);

  return <>{value == null ? "…" : format(shown)}</>;
}

export function Page({ title, subtitle, actions, children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
    >
      <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 260 }}>
          <h1>{title}</h1>
          {subtitle && <p className="subtitle">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </motion.div>
  );
}
