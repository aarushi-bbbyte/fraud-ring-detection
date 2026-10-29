"""Precision, recall and F1 of the rule-based alerts against the laundering labels.

Evaluated per transaction, because that's where the labels are: a transaction
is predicted positive if any alert of the rule includes it.

Recall is reported twice:
  * against all 5,177 laundering transactions,
  * against the 3,209 that belong to a typed attempt in the patterns file.
The other 1,968 laundering transactions have no pattern type, so no
pattern-specific rule can be expected to target them.

Per pattern type the script also reports attempt-level recall: the share of
attempts with at least one flagged transaction. That's what an investigator
needs to find the rest of the attempt.

Usage (from backend/, after ``python -m fraudring.detection.run``):
    python -m fraudring.evaluation.rules
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from fraudring.config import REPO_ROOT  # noqa: E402
from fraudring.db import get_driver  # noqa: E402

RESULTS = REPO_ROOT / "results"
RULES = ["cycle", "fan_in", "fan_out"]
ALL_RULES = "any rule"
UNTYPED = "(untyped)"


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def load(driver) -> tuple[dict[str, set[int]], dict[int, tuple[str, int | None]]]:
    flagged: dict[str, set[int]] = defaultdict(set)
    for r in driver.execute_query(
        "MATCH (al:Alert) UNWIND al.tx_ids AS tx RETURN al.rule AS rule, collect(DISTINCT tx) AS txs"
    ).records:
        flagged[r["rule"]] = set(r["txs"])
    flagged[ALL_RULES] = set().union(*(flagged[rule] for rule in RULES))

    labels = {
        r["tx"]: (r["pattern"] or UNTYPED, r["attempt"])
        for r in driver.execute_query(
            "MATCH ()-[s:SENT]->() WHERE s.is_laundering "
            "RETURN s.tx_id AS tx, s.pattern AS pattern, s.attempt_id AS attempt"
        ).records
    }
    return flagged, labels


def overall(flagged: dict[str, set[int]], labels: dict) -> list[dict]:
    laundering = set(labels)
    typed = {tx for tx, (pattern, _) in labels.items() if pattern != UNTYPED}
    rows = []
    for rule in RULES + [ALL_RULES]:
        pred = flagged[rule]
        tp_all, tp_typed = len(pred & laundering), len(pred & typed)
        precision = tp_all / len(pred) if pred else 0.0
        recall_all = tp_all / len(laundering)
        recall_typed = tp_typed / len(typed)
        rows.append({
            "rule": rule,
            "flagged_tx": len(pred),
            "true_positives": tp_all,
            "precision": round(precision, 4),
            "recall_all": round(recall_all, 4),
            "f1_all": round(f1(precision, recall_all), 4),
            "recall_typed": round(recall_typed, 4),
            "f1_typed": round(f1(precision, recall_typed), 4),
        })
    return rows


def by_pattern(flagged: dict[str, set[int]], labels: dict) -> list[dict]:
    txs: dict[str, set[int]] = defaultdict(set)
    attempts: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for tx, (pattern, attempt) in labels.items():
        txs[pattern].add(tx)
        if attempt is not None:
            attempts[pattern][attempt].add(tx)
    rows = []
    for pattern in sorted(txs, key=lambda p: (p == UNTYPED, p)):
        row = {"pattern": pattern, "laundering_tx": len(txs[pattern])}
        for rule in RULES + [ALL_RULES]:
            row[f"recall_{rule.replace(' ', '_')}"] = round(len(txs[pattern] & flagged[rule]) / len(txs[pattern]), 4)
        if attempts[pattern]:
            hit = sum(bool(a & flagged[ALL_RULES]) for a in attempts[pattern].values())
            row["attempts"] = len(attempts[pattern])
            row["attempt_recall_any_rule"] = round(hit / len(attempts[pattern]), 4)
        else:
            row["attempts"] = ""
            row["attempt_recall_any_rule"] = ""
        rows.append(row)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def plot_heatmap(rows: list[dict], path: Path) -> None:
    """Transaction recall per pattern type (rows) and rule (columns)."""
    cols = RULES + [ALL_RULES]
    data = [[r[f"recall_{c.replace(' ', '_')}"] * 100 for c in cols] for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, 0.5 * len(rows) + 1.6), facecolor="#fcfcfb")
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("blue", ["#f0efec", "#86b6ef", "#2a78d6", "#104281"])
    ax.imshow(data, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i, line in enumerate(data):
        for j, v in enumerate(line):
            ax.text(j, i, f"{v:.0f}%", ha="center", va="center", fontsize=9,
                    color="#ffffff" if v >= 55 else "#0b0b0b")
    ax.set_xticks(range(len(cols)), [c.replace("_", "-") for c in cols])
    ax.set_yticks(range(len(rows)), [f"{r['pattern']}  ({r['laundering_tx']})" for r in rows])
    ax.tick_params(colors="#52514e", length=0)
    ax.xaxis.tick_top()
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("Share of laundering transactions flagged, by pattern type and rule",
                 loc="left", fontsize=11, color="#0b0b0b", pad=28)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def main() -> int:
    driver = get_driver()
    try:
        flagged, labels = load(driver)
    finally:
        driver.close()
    if not flagged[ALL_RULES]:
        print("No alerts found. Run python -m fraudring.detection.run first.", file=sys.stderr)
        return 1

    summary = overall(flagged, labels)
    patterns = by_pattern(flagged, labels)
    write_csv(summary, RESULTS / "rule_eval_overall.csv")
    write_csv(patterns, RESULTS / "rule_eval_by_pattern.csv")
    plot_heatmap(patterns, RESULTS / "rule_eval_by_pattern.png")

    print(f"\n{'rule':<10}{'flagged':>9}{'prec':>8}{'rec(all)':>10}{'F1(all)':>9}{'rec(typed)':>12}{'F1(typed)':>11}")
    for r in summary:
        print(f"{r['rule']:<10}{r['flagged_tx']:>9,}{r['precision']:>8.3f}{r['recall_all']:>10.3f}"
              f"{r['f1_all']:>9.3f}{r['recall_typed']:>12.3f}{r['f1_typed']:>11.3f}")
    print(f"\n{'pattern':<16}{'tx':>6}" + "".join(f"{c:>10}" for c in RULES + ["any"]) + f"{'attempts hit':>14}")
    for r in patterns:
        cells = "".join(f"{r[f'recall_{c}']:>10.2f}" for c in RULES + ["any_rule"])
        att = f"{r['attempt_recall_any_rule']:.2f} of {r['attempts']}" if r["attempts"] != "" else "-"
        print(f"{r['pattern']:<16}{r['laundering_tx']:>6}{cells}{att:>14}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
