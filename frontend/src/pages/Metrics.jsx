import { useEffect, useState } from "react";
import { api, RULE_LABEL } from "../api.js";

const pct = (v) => (v === "" || v == null ? "–" : `${(v * 100).toFixed(1)}%`);

// Static charts produced by the evaluation scripts, served from results/.
const CHARTS = [
  ["rule_eval_by_pattern.png", "Rule recall by laundering pattern"],
  ["ml_pr_curve.png", "Account risk model: tabular vs tabular + graph features"],
  ["sweep_cycles.png", "Cycle rule threshold sweep"],
  ["sweep_fans.png", "Fan rule threshold sweep"],
];

export default function Metrics() {
  const [m, setM] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="banner error">{error}</p>;
  if (!m) return <p className="muted">Loading metrics…</p>;

  const g = m.graph;
  return (
    <>
      <h1>Metrics</h1>
      <div className="stats">
        <div className="stat"><div className="value">{g.accounts.toLocaleString()}</div><div className="label">accounts</div></div>
        <div className="stat"><div className="value">{g.transactions.toLocaleString()}</div><div className="label">transactions</div></div>
        {Object.entries(g.alerts).map(([rule, n]) => (
          <div className="stat" key={rule}><div className="value">{n.toLocaleString()}</div><div className="label">{RULE_LABEL[rule]} alerts</div></div>
        ))}
        <div className="stat"><div className="value">{g.rings.toLocaleString()}</div><div className="label">rings</div></div>
      </div>

      <h2>Rule-based detection vs dataset labels (per transaction)</h2>
      <table>
        <thead>
          <tr>
            <th>Rule</th><th className="num">Flagged tx</th><th className="num">Precision</th>
            <th className="num">Recall (all laundering)</th><th className="num">F1 (all)</th>
            <th className="num">Recall (typed patterns)</th><th className="num">F1 (typed)</th>
          </tr>
        </thead>
        <tbody>
          {m.rules.overall.map((r) => (
            <tr key={r.rule}>
              <td>{RULE_LABEL[r.rule] ?? r.rule}</td>
              <td className="num">{r.flagged_tx.toLocaleString()}</td>
              <td className="num">{pct(r.precision)}</td>
              <td className="num">{pct(r.recall_all)}</td>
              <td className="num">{pct(r.f1_all)}</td>
              <td className="num">{pct(r.recall_typed)}</td>
              <td className="num">{pct(r.f1_typed)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Recall by laundering pattern</h2>
      <table>
        <thead>
          <tr>
            <th>Pattern</th><th className="num">Laundering tx</th><th className="num">Cycle</th><th className="num">Fan-in</th>
            <th className="num">Fan-out</th><th className="num">Any rule</th><th className="num">Attempts hit</th>
          </tr>
        </thead>
        <tbody>
          {m.rules.by_pattern.map((r) => (
            <tr key={r.pattern}>
              <td>{r.pattern}</td>
              <td className="num">{r.laundering_tx.toLocaleString()}</td>
              <td className="num">{pct(r.recall_cycle)}</td>
              <td className="num">{pct(r.recall_fan_in)}</td>
              <td className="num">{pct(r.recall_fan_out)}</td>
              <td className="num">{pct(r.recall_any_rule)}</td>
              <td className="num">{r.attempts === "" ? "–" : `${pct(r.attempt_recall_any_rule)} of ${r.attempts}`}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {m.ml.metrics.length > 0 && (
        <>
          <h2>Account risk model (RQ1): do graph features help?</h2>
          <table>
            <thead>
              <tr>
                <th>Model</th><th className="num">Features</th><th className="num">Precision</th>
                <th className="num">Recall</th><th className="num">F1</th><th className="num">PR-AUC</th>
              </tr>
            </thead>
            <tbody>
              {m.ml.metrics.map((r) => (
                <tr key={r.model}>
                  <td>{r.model}</td>
                  <td className="num">{r.features}</td>
                  <td className="num">{pct(r.precision)}</td>
                  <td className="num">{pct(r.recall)}</td>
                  <td className="num">{pct(r.f1)}</td>
                  <td className="num">{r.pr_auc.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            XGBoost with default settings, held-out 20% of {m.ml.metrics[0].test_accounts.toLocaleString()} accounts
            ({m.ml.metrics[0].test_positives.toLocaleString()} positive). Threshold 0.5.
          </p>
          <h2>Top features (tabular + graph model, share of total gain)</h2>
          <table>
            <tbody>
              {m.ml.importance
                .filter((r) => r.model === "tabular + graph")
                .map((r) => (
                  <tr key={r.feature}>
                    <td>{r.rank}. {r.feature}</td>
                    <td className="num">{pct(r.gain_share)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}

      <h2>Charts</h2>
      <div className="images">
        {CHARTS.filter(([name]) => m.images.includes(name)).map(([name, title]) => (
          <figure key={name} style={{ margin: 0 }}>
            <figcaption className="muted" style={{ marginBottom: 6 }}>{title}</figcaption>
            <img src={api.resultImage(name)} alt={title} />
          </figure>
        ))}
      </div>
    </>
  );
}
