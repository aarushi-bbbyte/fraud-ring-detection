"""Threshold sweep for the detection rules, used to choose the defaults in RuleConfig.

For every setting it records:
  * capture: share of ground-truth attempts of that pattern the rule finds,
  * runtime of the rule query,
  * alert volume, because looser thresholds always capture more; the cost is
    more alerts, most of them on normal accounts.

Cycles. Capture is measured over all 54 CYCLE attempts by running the same
query from every ground-truth cycle transaction. That gives exactly what a full
scan would return for those starting edges. An attempt counts as captured only
if a detected cycle consists of exactly its transactions. Runtime and alert
volume come from scanning one fixed day of starting edges (SLICE), because a
full scan at every setting would take hours. Slice runtimes compare settings
with each other but don't scale linearly to the full graph: one day's working
set fits in the page cache, and a full scan doesn't. At the defaults, the
slice takes ~15 s and a measured full scan takes ~9 min.

Fans. The fan query is cheap enough to run on the full graph for every
setting. An attempt counts as captured if its hub is flagged and the flagged
window contains at least one of the attempt's transactions.

Usage (from backend/):
    python -m fraudring.detection.sweep              # both rules
    python -m fraudring.detection.sweep --only fans
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from neo4j import Driver  # noqa: E402

from fraudring.config import REPO_ROOT  # noqa: E402
from fraudring.db import get_driver  # noqa: E402
from fraudring.detection.config import RuleConfig  # noqa: E402
from fraudring.detection.cycles import find_cycles  # noqa: E402
from fraudring.detection.degrees import degrees_missing, update_degrees  # noqa: E402
from fraudring.detection.fans import find_fans  # noqa: E402

RESULTS = REPO_ROOT / "results"

CYCLE_HOPS = [4, 6, 8, 10, 12]
CYCLE_WINDOWS = [24.0, 48.0, 72.0, 96.0, 120.0]
FAN_WINDOWS = [24.0, 48.0, 72.0, 96.0, 120.0]
FAN_MIN_COUNTS = [3, 5, 8, 10, 12, 15]
SLICE = (datetime(2022, 9, 5), datetime(2022, 9, 6))

# Ordinal blue ramp (light -> dark) for the ordered window sizes; chart chrome tokens.
WINDOW_COLORS = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#fcfcfb"


@dataclass
class Attempt:
    tx_ids: set[int]
    hub: str | None = None


def ground_truth(driver: Driver, pattern: str) -> dict[int, Attempt]:
    records = driver.execute_query(
        "MATCH (a:Account)-[s:SENT {pattern: $p}]->(b:Account) "
        "RETURN s.attempt_id AS id, s.tx_id AS tx, a.id AS src, b.id AS dst",
        p=pattern,
    ).records
    attempts: dict[int, Attempt] = defaultdict(lambda: Attempt(set()))
    for r in records:
        att = attempts[r["id"]]
        att.tx_ids.add(r["tx"])
        if pattern == "FAN-IN":
            att.hub = r["dst"]
        elif pattern == "FAN-OUT":
            att.hub = r["src"]
    return dict(attempts)


def laundering_tx_ids(driver: Driver) -> set[int]:
    """All labeled laundering transactions (5,177 in HI-Small), fetched once.

    Checking alerts against this set avoids sending hundreds of thousands of
    transaction IDs back to the database at the loosest thresholds.
    """
    records = driver.execute_query(
        "MATCH ()-[s:SENT]->() WHERE s.is_laundering RETURN s.tx_id AS tx"
    ).records
    return {r["tx"] for r in records}


def edge_count(driver: Driver, start: datetime | None = None, end: datetime | None = None) -> int:
    if start is None:
        query = "MATCH ()-[s:SENT]->() WHERE NOT s.is_self_loop RETURN count(s) AS n"
    else:
        query = (
            "MATCH ()-[s:SENT]->() WHERE s.timestamp >= $start AND s.timestamp < $end "
            "AND NOT s.is_self_loop RETURN count(s) AS n"
        )
    return driver.execute_query(query, start=start, end=end).records[0]["n"]


# --- cycles -------------------------------------------------------------------

def sweep_cycles(driver: Driver, base: RuleConfig) -> list[dict]:
    attempts = ground_truth(driver, "CYCLE")
    anchors = sorted(set().union(*(a.tx_ids for a in attempts.values())))
    labeled = laundering_tx_ids(driver)
    share = edge_count(driver, *SLICE) / edge_count(driver)
    print(f"cycles: {len(attempts)} attempts; slice holds {share:.1%} of non-self-loop edges")

    print("  warm-up run")
    find_cycles(driver, replace(base, cycle_max_hops=4, cycle_window_hours=24.0), start=SLICE[0], end=SLICE[1])

    rows = []
    for window in CYCLE_WINDOWS:
        widest = replace(base, cycle_max_hops=max(CYCLE_HOPS), cycle_window_hours=window)
        found = find_cycles(driver, widest, tx_ids=anchors)
        for hops in CYCLE_HOPS:
            sets = {frozenset(c.tx_ids) for c in found if c.hops <= hops}
            captured = sum(frozenset(a.tx_ids) in sets for a in attempts.values())

            cfg = replace(base, cycle_max_hops=hops, cycle_window_hours=window)
            t = time.perf_counter()
            cycles = find_cycles(driver, cfg, start=SLICE[0], end=SLICE[1])
            seconds = time.perf_counter() - t
            laundering = sum(set(c.tx_ids) <= labeled for c in cycles)

            row = {
                "max_hops": hops,
                "window_h": window,
                "amount_tolerance": base.cycle_amount_tolerance,
                "attempts": len(attempts),
                "captured": captured,
                "capture_pct": round(100 * captured / len(attempts), 1),
                "slice_seconds": round(seconds, 1),
                "slice_cycles": len(cycles),
                "slice_laundering_cycles": laundering,
            }
            rows.append(row)
            print(f"  hops<={hops:>2} window={window:>5.0f}h  capture {captured}/{len(attempts)}"
                  f"  slice {seconds:6.1f}s  cycles {len(cycles):>4} ({laundering} laundering)", flush=True)
    return rows


def sweep_tolerance(driver: Driver, base: RuleConfig, tolerances=(0.1, 0.2, 0.3)) -> list[dict]:
    """Sensitivity of the chosen cycle defaults to the amount tolerance."""
    attempts = ground_truth(driver, "CYCLE")
    anchors = sorted(set().union(*(a.tx_ids for a in attempts.values())))
    labeled = laundering_tx_ids(driver)
    rows = []
    for tol in tolerances:
        cfg = replace(base, cycle_amount_tolerance=tol)
        sets = {frozenset(c.tx_ids) for c in find_cycles(driver, cfg, tx_ids=anchors)}
        captured = sum(frozenset(a.tx_ids) in sets for a in attempts.values())
        t = time.perf_counter()
        cycles = find_cycles(driver, cfg, start=SLICE[0], end=SLICE[1])
        seconds = time.perf_counter() - t
        rows.append({
            "amount_tolerance": tol,
            "max_hops": cfg.cycle_max_hops,
            "window_h": cfg.cycle_window_hours,
            "captured": captured,
            "capture_pct": round(100 * captured / len(attempts), 1),
            "slice_seconds": round(seconds, 1),
            "slice_cycles": len(cycles),
            "slice_laundering_cycles": sum(set(c.tx_ids) <= labeled for c in cycles),
        })
        print(f"  tolerance {tol:.0%}: capture {captured}/{len(attempts)}  slice {seconds:.1f}s  cycles {len(cycles)}")
    return rows


# --- fans ---------------------------------------------------------------------

def sweep_fans(driver: Driver, base: RuleConfig) -> list[dict]:
    rows = []
    labeled = laundering_tx_ids(driver)
    for direction, pattern in (("in", "FAN-IN"), ("out", "FAN-OUT")):
        attempts = ground_truth(driver, pattern)
        print(f"fan-{direction}: {len(attempts)} attempts")
        for window in FAN_WINDOWS:
            for min_count in FAN_MIN_COUNTS:
                cfg = replace(base, fan_window_hours=window,
                              fan_in_min_senders=min_count, fan_out_min_receivers=min_count)
                t = time.perf_counter()
                hits = find_fans(driver, cfg, direction)
                seconds = time.perf_counter() - t
                by_hub = {h.hub: set(h.tx_ids) for h in hits}
                captured = sum(bool(by_hub.get(a.hub, set()) & a.tx_ids) for a in attempts.values())
                rows.append({
                    "direction": direction,
                    "window_h": window,
                    "min_count": min_count,
                    "attempts": len(attempts),
                    "captured": captured,
                    "capture_pct": round(100 * captured / len(attempts), 1),
                    "hubs_flagged": len(hits),
                    "hubs_with_laundering_tx": sum(not labeled.isdisjoint(h.tx_ids) for h in hits),
                    "seconds": round(seconds, 1),
                })
                print(f"  W={window:>5.0f}h d>={min_count:>2}  capture {captured}/{len(attempts)}"
                      f"  flagged {len(hits):>6,}  {seconds:6.1f}s", flush=True)
    return rows


# --- output -------------------------------------------------------------------

def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def read_csv(path: Path) -> list[dict]:
    """Read a sweep CSV back with numeric columns as numbers."""
    def num(v: str):
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: num(v) for k, v in row.items()} for row in csv.DictReader(f)]


def style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED)


def plot_lines(ax, rows, x, y, windows) -> None:
    """One line per window. A line drawn exactly under a later one says so in the legend."""
    series = {w: sorted((r[x], r[y]) for r in rows if r["window_h"] == w) for w in windows}
    for i, (window, color) in enumerate(zip(windows, WINDOW_COLORS)):
        label = f"{window:.0f} h window"
        same = [w for w in windows[i + 1:] if series[w] == series[window]]
        if same:
            label += f" (hidden: same as {same[-1]:.0f} h)"
        ax.plot(*zip(*series[window]), color=color, linewidth=2, marker="o", markersize=5, label=label)


def plot_cycles(rows: list[dict], path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), facecolor=SURFACE)
    panels = [
        ("capture_pct", "Ground-truth cycles captured", "% of 54 attempts"),
        ("slice_seconds", "Runtime per day of start edges", "seconds (2022-09-05, warm cache)"),
        ("slice_cycles", "Cycles flagged per day", "cycles on 2022-09-05"),
    ]
    for ax, (y, title, ylabel) in zip(axes, panels):
        plot_lines(ax, rows, "max_hops", y, CYCLE_WINDOWS)
        style(ax, title, "max hops", ylabel)
        ax.set_xticks(CYCLE_HOPS)
        ax.set_ylim(bottom=0)
    axes[0].set_ylim(0, 100)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")
    fig.suptitle(f"Cycle rule sweep (amount tolerance ±{rows[0]['amount_tolerance']:.0%})",
                 x=0.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def plot_fans(rows: list[dict], path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.4), facecolor=SURFACE)
    for row_axes, direction in zip(axes, ("in", "out")):
        sub = [r for r in rows if r["direction"] == direction]
        n = sub[0]["attempts"]
        panels = [
            ("capture_pct", f"Fan-{direction}: ground-truth attempts captured", f"% of {n} attempts"),
            ("hubs_flagged", f"Fan-{direction}: accounts flagged", "accounts (log scale)"),
            ("seconds", f"Fan-{direction}: full-graph runtime", "seconds"),
        ]
        for ax, (y, title, ylabel) in zip(row_axes, panels):
            plot_lines(ax, sub, "min_count", y, FAN_WINDOWS)
            style(ax, title, "min distinct counterparties", ylabel)
            ax.set_xticks(FAN_MIN_COUNTS)
        row_axes[2].set_ylim(bottom=0)
        row_axes[0].set_ylim(0, 100)
        row_axes[1].set_yscale("log")
        row_axes[0].legend(frameon=False, fontsize=9, loc="upper right")
    fig.suptitle("Fan rule sweep", x=0.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["cycles", "fans", "tolerance"])
    parser.add_argument("--replot", action="store_true", help="redraw plots from the saved CSVs")
    args = parser.parse_args(argv)

    if args.replot:
        plot_cycles(read_csv(RESULTS / "sweep_cycles.csv"), RESULTS / "sweep_cycles.png")
        plot_fans(read_csv(RESULTS / "sweep_fans.csv"), RESULTS / "sweep_fans.png")
        return 0

    base = RuleConfig()
    driver = get_driver()
    try:
        if degrees_missing(driver):
            print("computing account degrees...")
            update_degrees(driver)
        if args.only in (None, "cycles"):
            rows = sweep_cycles(driver, base)
            write_csv(rows, RESULTS / "sweep_cycles.csv")
            plot_cycles(rows, RESULTS / "sweep_cycles.png")
        if args.only in (None, "fans"):
            rows = sweep_fans(driver, base)
            write_csv(rows, RESULTS / "sweep_fans.csv")
            plot_fans(rows, RESULTS / "sweep_fans.png")
        if args.only == "tolerance":
            write_csv(sweep_tolerance(driver, base), RESULTS / "sweep_cycle_tolerance.csv")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
