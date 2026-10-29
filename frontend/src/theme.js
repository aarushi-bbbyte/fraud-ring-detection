// Shared colours and formatters, so risk and pattern colours mean the same thing on every page.

export const COLORS = {
  safe: "#2dd4bf",
  danger: "#f05252",
  amber: "#f5a524",
  ink: "#e8eef9",
  ink2: "#a9b6cc",
  muted: "#7c8aa5",
  surface: "#111a2e",
  line: "#24324f",
  // Chart series (validated categorical slots for a dark surface).
  series1: "#3987e5",
  series2: "#d95926",
};

// Risk scale: green -> amber -> red, always shown next to the number itself.
const RISK_STOPS = [
  [0, [12, 163, 12]],
  [0.5, [250, 178, 25]],
  [1, [208, 59, 59]],
];

export function riskColor(r) {
  const v = Math.min(Math.max(r ?? 0, 0), 1);
  const i = v <= 0.5 ? 0 : 1;
  const [a, ca] = RISK_STOPS[i];
  const [b, cb] = RISK_STOPS[i + 1];
  const t = (v - a) / (b - a);
  const mix = ca.map((c, k) => Math.round(c + (cb[k] - c) * t));
  return `rgb(${mix.join(",")})`;
}

// One colour per pattern type. Badges always carry the name too, so colour is never the only cue.
export const PATTERN = {
  cycle: { label: "Cycle", color: "#9085e9" },
  fan_in: { label: "Fan-in", color: "#3987e5" },
  fan_out: { label: "Fan-out", color: "#d55181" },
  CYCLE: { label: "Cycle", color: "#9085e9" },
  "FAN-IN": { label: "Fan-in", color: "#3987e5" },
  "FAN-OUT": { label: "Fan-out", color: "#d55181" },
  "GATHER-SCATTER": { label: "Gather-scatter", color: "#199e70" },
  "SCATTER-GATHER": { label: "Scatter-gather", color: "#2dd4bf" },
  BIPARTITE: { label: "Bipartite", color: "#c98500" },
  STACK: { label: "Stack", color: "#d95926" },
  RANDOM: { label: "Random", color: "#7c8aa5" },
  "(untyped)": { label: "Untyped", color: "#56637d" },
  "any rule": { label: "Any rule", color: "#e8eef9" },
};

export const patternInfo = (key) => PATTERN[key] ?? { label: key, color: COLORS.muted };

export const usd = (v) =>
  v == null ? "–" : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

/** $42.3k, $1.2M, $3.4B: for counters and headlines. */
export function usdShort(v) {
  if (v == null) return "–";
  const abs = Math.abs(v);
  for (const [div, suffix] of [[1e9, "B"], [1e6, "M"], [1e3, "k"]]) {
    if (abs >= div) return `$${(v / div).toFixed(abs >= div * 100 ? 0 : 1)}${suffix}`;
  }
  return `$${v.toFixed(0)}`;
}

export const time = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "–");
export const pct = (v, digits = 1) => (v === "" || v == null ? "–" : `${(v * 100).toFixed(digits)}%`);
