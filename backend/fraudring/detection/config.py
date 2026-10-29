"""Detection thresholds.

Defaults come from the threshold sweep (``python -m fraudring.detection.sweep``),
with results in ``results/sweep_*.csv`` and ``results/sweep_*.png``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleConfig:
    # Cycle rule: money leaves an account and returns to it.
    # 12 hops / 96 h captures 47 of 54 ground-truth cycles. The other 7 aren't
    # time-ordered chains (5) or break the amount tolerance (2). Runtime is flat
    # in max hops, because the first expansion dominates, so a lower hop cap
    # loses capture without saving time. 120 h captures no more than 96 h but
    # flags ~25% more cycles.
    cycle_max_hops: int = 12
    cycle_window_hours: float = 96.0
    # Each hop must pass on a similar amount: |usd_i / usd_(i-1) - 1| <= tolerance.
    # This is what keeps long cycle searches tractable, since only ~5% of random
    # hop pairs pass at 20%.
    cycle_amount_tolerance: float = 0.20

    # Fan rules: many distinct counterparties within one sliding window.
    # 96 h covers the longest ground-truth fan (96 h). >=8 is the knee: going
    # from >=5 to >=8 cuts flagged accounts by 65% (in) / 77% (out) for 20 / 6
    # points of capture. At >=8 the rules catch essentially every ground-truth
    # attempt that has 8+ counterparties; smaller ones look like normal accounts.
    fan_window_hours: float = 96.0
    fan_in_min_senders: int = 8
    fan_out_min_receivers: int = 8

    # Accounts with more non-self-loop edges than this (in the fan's direction)
    # are treated as high-volume hubs and not scored by the fan rules. Exact
    # sliding-window counting is quadratic in degree, and these few accounts
    # (15 in HI-Small, up to 168k edges) would dominate the runtime. No
    # ground-truth pattern account exceeds degree 227.
    hub_degree_cap: int = 1000
