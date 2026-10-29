"""Run all detection rules, store alerts, and group them into rings.

Usage (from backend/):
    python -m fraudring.detection.run
    python -m fraudring.detection.run --cycle-max-hops 8 --fan-window-hours 72
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field, fields

from neo4j import Driver

from fraudring.db import get_driver
from fraudring.detection.alerts import clear_alerts, cycle_alert, fan_alert, write_alerts
from fraudring.detection.config import RuleConfig
from fraudring.detection.cycles import find_cycles
from fraudring.detection.degrees import degrees_missing, update_degrees
from fraudring.detection.fans import find_fans
from fraudring.detection.rings import build_rings
from fraudring.schema import ensure_schema


@dataclass
class DetectionSummary:
    cycles: int = 0
    fan_in: int = 0
    fan_out: int = 0
    rings: list[list[str]] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)


def run_detection(driver: Driver, cfg: RuleConfig) -> DetectionSummary:
    """Full detection pass over the whole graph. Replaces any previous alerts and rings."""
    ensure_schema(driver)
    if degrees_missing(driver):
        update_degrees(driver)
    summary = DetectionSummary()

    def timed(name, fn):
        t = time.perf_counter()
        out = fn()
        summary.seconds[name] = time.perf_counter() - t
        return out

    cycles = timed("cycle", lambda: find_cycles(driver, cfg))
    fans_in = timed("fan_in", lambda: find_fans(driver, cfg, "in"))
    fans_out = timed("fan_out", lambda: find_fans(driver, cfg, "out"))
    summary.cycles, summary.fan_in, summary.fan_out = len(cycles), len(fans_in), len(fans_out)

    alerts = [cycle_alert(c, cfg.cycle_amount_tolerance) for c in cycles]
    alerts += [fan_alert(f) for f in fans_in + fans_out]
    clear_alerts(driver)
    timed("write_alerts", lambda: write_alerts(driver, alerts))
    summary.rings = timed("rings", lambda: build_rings(driver))
    return summary


def parse_args(argv: list[str] | None = None) -> RuleConfig:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    defaults = RuleConfig()
    for f in fields(RuleConfig):
        parser.add_argument(f"--{f.name.replace('_', '-')}", type=type(getattr(defaults, f.name)), default=getattr(defaults, f.name))
    return RuleConfig(**vars(parser.parse_args(argv)))


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    print(cfg)
    driver = get_driver()
    try:
        s = run_detection(driver, cfg)
    finally:
        driver.close()
    sizes = [len(r) for r in s.rings]
    print(f"cycles: {s.cycles:,}   fan-in: {s.fan_in:,}   fan-out: {s.fan_out:,}")
    print(f"rings: {len(sizes):,}   largest: {sizes[:5]}   singletons: {sizes.count(1)}")
    print("timings: " + ", ".join(f"{k} {v:.1f}s" for k, v in s.seconds.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
