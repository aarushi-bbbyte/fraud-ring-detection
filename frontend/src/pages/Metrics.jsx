import { api } from "../api.js";
import { COLORS, pct } from "../theme.js";
import { Page, PatternBadge, Skeleton } from "../components/ui.jsx";

// Exported matplotlib figures, kept on a light "paper" frame since they're drawn for print.
const FIGURES = [
  ["sweep_cycles.png", "Cycle rule threshold sweep: capture, runtime and alert volume by max hops and window"],
  ["sweep_fans.png", "Fan rule threshold sweep: capture, flagged accounts and runtime by threshold and window"],
];

function Bar({ value, color = COLORS.safe, label }) {
  return (
    <div className="bar-row">
      <span>{label}</span>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(value * 100, 0.8)}%`, background: color }} /></div>
      <span className="num" style={{ fontWeight: 600 }}>{pct(value, 0)}</span>
    </div>
  );
}

function ModelChart({ rows }) {
  const series = [
    { model: "tabular", color: COLORS.series1, label: "Tabular only" },
    { model: "tabular + graph", color: COLORS.series2, label: "Tabular + graph" },
  ];
  const metrics = [["precision", "Precision"], ["recall", "Recall"], ["f1", "F1"], ["pr_auc", "PR-AUC"]];
  return (
    <>
      <div className="legend" style={{ marginTop: 0, marginBottom: 14 }}>
        {series.map((s) => <span key={s.model}><span className="dot" style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <div className="bars" style={{ gap: 16 }}>
        {metrics.map(([key, name]) => (
          <div key={key} className="bar-row" style={{ alignItems: "start" }}>
            <span style={{ fontWeight: 600 }}>{name}</span>
            <div className="bar-pair">
              {series.map((s) => {
                const r = rows.find((x) => x.model === s.model);
                return (
                  <div key={s.model} style={{ display: "grid", gridTemplateColumns: "1fr 60px", gap: 10, alignItems: "center" }}>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${r[key] * 100}%`, background: s.color }} /></div>
                    <span className="num" style={{ fontSize: 14 }}>{key === "pr_auc" ? r[key].toFixed(3) : pct(r[key])}</span>
                  </div>
                );
              })}
            </div>
            <span />
          </div>
        ))}
      </div>
    </>
  );
}

export default function Metrics({ metrics: m }) {
  if (!m) {
    return (
      <Page title="Metrics">
        <div className="tiles">{Array.from({ length: 5 }, (_, i) => <div key={i} className="tile"><Skeleton height={30} width="60%" /></div>)}</div>
        <Skeleton height={300} />
      </Page>
    );
  }

  const ml = m.ml.metrics;
  const best = ml.find((r) => r.model === "tabular + graph");
  const base = ml.find((r) => r.model === "tabular");
  const anyRule = m.rules.overall.find((r) => r.rule === "any rule");

  return (
    <Page title="Metrics" subtitle="How well the rules and the risk model find the dataset's labelled laundering.">
      <div className="tiles">
        <div className="tile"><div className="value">{pct(anyRule?.recall_typed)}</div><div className="label">of pattern-typed laundering flagged by a rule</div></div>
        <div className="tile"><div className="value">{pct(anyRule?.recall_all)}</div><div className="label">of all laundering flagged by a rule</div></div>
        {best && base && (
          <div className="tile">
            <div className="value" style={{ color: "var(--safe)" }}>+{((best.pr_auc / base.pr_auc - 1) * 100).toFixed(0)}%</div>
            <div className="label">PR-AUC from graph features ({base.pr_auc.toFixed(3)} → {best.pr_auc.toFixed(3)})</div>
          </div>
        )}
        <div className="tile"><div className="value">{m.graph.rings.toLocaleString()}</div><div className="label">rings detected</div></div>
      </div>

      <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="card">
          <h2>Rules: share of laundering transactions flagged, by pattern</h2>
          <div className="bars">
            {m.rules.by_pattern.map((r) => (
              <Bar key={r.pattern} value={r.recall_any_rule} label={<PatternBadge pattern={r.pattern} />} />
            ))}
          </div>
          <p className="muted" style={{ marginBottom: 0, marginTop: 14 }}>
            Rules catch the shapes they encode (cycles, fans, scatter/gather) and miss bipartite, stack and random patterns.
          </p>
        </div>
        {ml.length > 0 && (
          <div className="card">
            <h2>Risk model (RQ1): do graph features help?</h2>
            <ModelChart rows={ml} />
            <p className="muted" style={{ marginBottom: 0, marginTop: 14 }}>
              XGBoost, default settings, held-out 20% of {ml[0].test_accounts.toLocaleString()} accounts
              ({ml[0].test_positives.toLocaleString()} positive), threshold 0.5.
            </p>
          </div>
        )}
      </div>

      <div className="card flush" style={{ marginTop: 20 }}>
        <div style={{ padding: "18px 20px 4px" }}><h2>Rule-based detection vs labels (per transaction)</h2></div>
        <table>
          <thead>
            <tr>
              <th>Rule</th><th className="num">Flagged tx</th><th className="num">Precision</th>
              <th className="num">Recall (all)</th><th className="num">Recall (typed)</th><th className="num">F1 (all)</th>
            </tr>
          </thead>
          <tbody>
            {m.rules.overall.map((r) => (
              <tr key={r.rule}>
                <td>{r.rule === "any rule" ? <strong>Any rule</strong> : <PatternBadge pattern={r.rule} />}</td>
                <td className="num">{r.flagged_tx.toLocaleString()}</td>
                <td className="num">{pct(r.precision)}</td>
                <td className="num">{pct(r.recall_all)}</td>
                <td className="num">{pct(r.recall_typed)}</td>
                <td className="num">{r.f1_all.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {m.ml.importance.length > 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <h2>Top features of the tabular + graph model (share of gain)</h2>
          <div className="bars">
            {m.ml.importance.filter((r) => r.model === "tabular + graph").map((r) => (
              <Bar key={r.feature} value={r.gain_share} label={<span className="mono">{r.feature}</span>}
                   color={["in_ring", "pagerank"].includes(r.feature) || r.feature.startsWith("flagged_") ? COLORS.series2 : COLORS.series1} />
            ))}
          </div>
          <div className="legend">
            <span><span className="dot" style={{ background: COLORS.series1 }} />tabular feature</span>
            <span><span className="dot" style={{ background: COLORS.series2 }} />graph feature</span>
          </div>
        </div>
      )}

      <h2 style={{ marginTop: 28 }}>Threshold sweeps</h2>
      <div className="stack">
        {FIGURES.filter(([name]) => m.images.includes(name)).map(([name, caption]) => (
          <div key={name} className="card">
            <p className="figcap">{caption}</p>
            <div className="figure"><img src={api.resultImage(name)} alt={caption} loading="lazy" /></div>
          </div>
        ))}
      </div>
      <p className="muted">Full CSVs and plots are in <span className="mono">results/</span>.</p>
    </Page>
  );
}
