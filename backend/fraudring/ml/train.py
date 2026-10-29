"""Train and compare two account-level XGBoost models: tabular-only vs tabular + graph.

Task: label = 1 if the account sent or received any laundering transaction.

Features never touch ``is_laundering``, ``pattern`` or ``attempt_id``. Those
only define the label.

* Tabular (per account, transaction data only): in/out transaction counts,
  distinct counterparties in/out, total and mean USD in/out, number of
  currencies and payment formats used. Self-loops are excluded.
* Graph: whether the account is in a ring detected by the Phase 2 rules, which
  rules flagged it (cycle / fan-in / fan-out), and PageRank over the full
  transaction graph. GDS estimates ~46 MiB for that projection plus ~39 MiB
  for PageRank, well within the 1 GB heap.

Both models use XGBoost defaults with ``scale_pos_weight`` = negatives /
positives for the imbalance, on the same stratified 80/20 split. Risk scores
written back to Neo4j come from 5-fold out-of-fold predictions of the
tabular + graph model, so no account is scored by a model trained on it.

Usage (from backend/, after ``python -m fraudring.detection.run``):
    python -m fraudring.ml.train
"""

from __future__ import annotations

import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from neo4j import Driver  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

from fraudring.db import get_driver  # noqa: E402
from fraudring.results import RESULTS_DIR, write_csv  # noqa: E402

SEED = 42
TABULAR = [
    "n_out", "n_in", "distinct_out", "distinct_in",
    "usd_out_total", "usd_out_mean", "usd_in_total", "usd_in_mean",
    "n_currencies", "n_formats",
]
GRAPH = ["in_ring", "flagged_cycle", "flagged_fan_in", "flagged_fan_out", "pagerank"]

FEATURES = """
MATCH (a:Account) WHERE a.bank <> 'SIM'
CALL (a) {
  OPTIONAL MATCH (a)-[s:SENT]->(b) WHERE NOT s.is_self_loop
  RETURN count(s) AS n_out, count(DISTINCT b) AS distinct_out,
         coalesce(sum(s.amount_usd), 0.0) AS usd_out_total, coalesce(avg(s.amount_usd), 0.0) AS usd_out_mean,
         collect(DISTINCT s.currency) AS cur_out, collect(DISTINCT s.format) AS fmt_out
}
CALL (a) {
  OPTIONAL MATCH (b)-[s:SENT]->(a) WHERE NOT s.is_self_loop
  RETURN count(s) AS n_in, count(DISTINCT b) AS distinct_in,
         coalesce(sum(s.amount_usd), 0.0) AS usd_in_total, coalesce(avg(s.amount_usd), 0.0) AS usd_in_mean,
         collect(DISTINCT s.receiving_currency) AS cur_in, collect(DISTINCT s.format) AS fmt_in
}
CALL (a) {
  OPTIONAL MATCH (a)<-[:INVOLVES]-(al:Alert)
  RETURN collect(DISTINCT al.rule) AS rules
}
RETURN a.id AS id, n_out, n_in, distinct_out, distinct_in,
       usd_out_total, usd_out_mean, usd_in_total, usd_in_mean,
       size(cur_out + [c IN cur_in WHERE NOT c IN cur_out]) AS n_currencies,
       size(fmt_out + [f IN fmt_in WHERE NOT f IN fmt_out]) AS n_formats,
       EXISTS { (a)-[:IN_RING]->(:Ring) } AS in_ring,
       'cycle' IN rules AS flagged_cycle, 'fan_in' IN rules AS flagged_fan_in, 'fan_out' IN rules AS flagged_fan_out,
       EXISTS { (a)-[s:SENT]-() WHERE s.is_laundering } AS label
"""

PAGERANK = """
CALL gds.pageRank.stream($name)
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).id AS id, score
"""

WRITE_SCORES = """
UNWIND $rows AS row
MATCH (a:Account {id: row.id})
SET a.risk_score = row.risk, a.pagerank = row.pagerank, a.in_ring = row.in_ring
"""

# An alert is as risky as the riskiest account it flags at its core.
ALERT_RISK = """
MATCH (al:Alert)
OPTIONAL MATCH (al)-[c:INVOLVES]->(a:Account) WHERE c.role IN ['origin', 'member', 'hub']
WITH al, max(a.risk_score) AS risk
SET al.risk = risk
"""


def load_features(driver: Driver) -> pd.DataFrame:
    with driver.session() as session:
        df = pd.DataFrame([dict(r) for r in session.run(FEATURES)])
    name = "ml-accounts"
    driver.execute_query("CALL gds.graph.drop($name, false) YIELD graphName", name=name)
    driver.execute_query("CALL gds.graph.project($name, 'Account', 'SENT')", name=name)
    try:
        with driver.session() as session:
            pagerank = {r["id"]: r["score"] for r in session.run(PAGERANK, name=name)}
    finally:
        driver.execute_query("CALL gds.graph.drop($name, false) YIELD graphName", name=name)
    df["pagerank"] = df["id"].map(pagerank).fillna(0.0)
    for col in ["in_ring", "flagged_cycle", "flagged_fan_in", "flagged_fan_out", "label"]:
        df[col] = df[col].astype(int)
    return df


def model(pos_weight: float) -> XGBClassifier:
    return XGBClassifier(scale_pos_weight=pos_weight, random_state=SEED, n_jobs=-1)


def evaluate(df: pd.DataFrame) -> tuple[list[dict], dict, list[dict]]:
    y = df["label"].to_numpy()
    idx_train, idx_test = train_test_split(np.arange(len(df)), test_size=0.2, stratify=y, random_state=SEED)
    pos_weight = (y[idx_train] == 0).sum() / max((y[idx_train] == 1).sum(), 1)

    metrics, curves, importances = [], {}, []
    for name, cols in (("tabular", TABULAR), ("tabular + graph", TABULAR + GRAPH)):
        X = df[cols].to_numpy(dtype=float)
        clf = model(pos_weight).fit(X[idx_train], y[idx_train])
        proba = clf.predict_proba(X[idx_test])[:, 1]
        pred = (proba >= 0.5).astype(int)
        metrics.append({
            "model": name,
            "features": len(cols),
            "precision": round(precision_score(y[idx_test], pred, zero_division=0), 4),
            "recall": round(recall_score(y[idx_test], pred), 4),
            "f1": round(f1_score(y[idx_test], pred), 4),
            "pr_auc": round(average_precision_score(y[idx_test], proba), 4),
            "test_accounts": len(idx_test),
            "test_positives": int(y[idx_test].sum()),
        })
        curves[name] = precision_recall_curve(y[idx_test], proba)
        gain = clf.get_booster().get_score(importance_type="gain")
        ranked = sorted(((cols[int(k[1:])], v) for k, v in gain.items()), key=lambda kv: -kv[1])
        total = sum(v for _, v in ranked)
        importances += [{"model": name, "rank": i + 1, "feature": f, "gain_share": round(v / total, 4)}
                        for i, (f, v) in enumerate(ranked[:10])]
    curves["prevalence"] = y[idx_test].mean()
    return metrics, curves, importances


def plot_pr(curves: dict, metrics: list[dict], path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.6), facecolor="#fcfcfb")
    colors = {"tabular": "#2a78d6", "tabular + graph": "#eb6834"}
    for m in metrics:
        precision, recall, _ = curves[m["model"]]
        ax.plot(recall, precision, color=colors[m["model"]], linewidth=2,
                label=f"{m['model']} (PR-AUC {m['pr_auc']:.3f})")
    ax.axhline(curves["prevalence"], color="#898781", linewidth=1, linestyle="--",
               label=f"random ({curves['prevalence']:.3f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("recall", color="#898781")
    ax.set_ylabel("precision", color="#898781")
    ax.set_title("Account risk model: precision-recall on held-out 20%", loc="left", fontsize=11)
    ax.set_facecolor("#fcfcfb")
    ax.grid(True, color="#e1e0d9", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"wrote {path}")


def write_scores(driver: Driver, df: pd.DataFrame) -> None:
    """Out-of-fold risk scores from the tabular + graph model, written to accounts and alerts."""
    X = df[TABULAR + GRAPH].to_numpy(dtype=float)
    y = df["label"].to_numpy()
    pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    risk = cross_val_predict(model(pos_weight), X, y, cv=folds, method="predict_proba")[:, 1]
    rows = [
        {"id": i, "risk": float(r), "pagerank": float(p), "in_ring": bool(ring)}
        for i, r, p, ring in zip(df["id"], risk, df["pagerank"], df["in_ring"])
    ]
    for start in range(0, len(rows), 10_000):
        driver.execute_query(WRITE_SCORES, rows=rows[start : start + 10_000])
    with driver.session() as session:
        session.run(ALERT_RISK).consume()


def main() -> int:
    driver = get_driver()
    try:
        t = time.perf_counter()
        df = load_features(driver)
        print(f"{len(df):,} accounts, {df['label'].sum():,} positive ({df['label'].mean():.2%}); "
              f"features loaded in {time.perf_counter() - t:.0f}s")
        metrics, curves, importances = evaluate(df)
        write_csv(metrics, RESULTS_DIR / "ml_metrics.csv")
        write_csv(importances, RESULTS_DIR / "ml_feature_importance.csv")
        plot_pr(curves, metrics, RESULTS_DIR / "ml_pr_curve.png")
        for m in metrics:
            print(f"  {m['model']:<16} P {m['precision']:.3f}  R {m['recall']:.3f}  "
                  f"F1 {m['f1']:.3f}  PR-AUC {m['pr_auc']:.3f}")
        t = time.perf_counter()
        write_scores(driver, df)
        print(f"risk scores written in {time.perf_counter() - t:.0f}s")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
