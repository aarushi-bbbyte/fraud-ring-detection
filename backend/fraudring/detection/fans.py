"""Fan-in and fan-out rules: many distinct counterparties within one time window.

Fan-in: one account receives from at least ``min_count`` distinct senders
within ``window``. Fan-out is the mirror image.

Windows slide: one starts at every edge of the hub, so a burst is never split
across a bucket boundary. For each hub the rule reports the single window with
the most distinct counterparties, which is the strongest evidence and the one
an investigator would look at first.

Cost control:
  * Hubs with fewer edges than ``min_count`` can't qualify and are skipped
    using the stored degree, without expanding their edges.
  * Hubs above ``hub_degree_cap`` are skipped (see RuleConfig).
  * A window starting at edge i can only hold ``min_count`` distinct
    counterparties if edge ``i + min_count - 1`` is still inside it. That check
    is O(1), so distinct counting only runs for windows that can qualify.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from neo4j import Driver, Query

from fraudring.detection.config import RuleConfig

Direction = Literal["in", "out"]

_PATTERN = {"in": "(c:Account)-[r:SENT]->(h)", "out": "(h)-[r:SENT]->(c:Account)"}
_DEGREE = {"in": "in_degree", "out": "out_degree"}


@dataclass(frozen=True)
class FanAlert:
    direction: Direction
    hub: str
    counterparties: int  # distinct counterparties in the window
    tx_ids: tuple[int, ...]
    counterparty_ids: tuple[str, ...]  # one per transaction, aligned with tx_ids
    start: datetime  # first transaction in the window
    end: datetime  # last transaction in the window
    total_usd: float

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def fan_query(direction: Direction) -> str:
    return f"""
MATCH (h:Account)
WHERE $min_count <= h.{_DEGREE[direction]} <= $hub_cap
  AND ($hubs IS NULL OR h.id IN $hubs)
CALL (h) {{
  MATCH {_PATTERN[direction]}
  WHERE NOT r.is_self_loop
  WITH c, r ORDER BY r.timestamp
  WITH collect(r.timestamp) AS ts, collect(c.id) AS cps, collect(r.tx_id) AS txs,
       collect(r.amount_usd) AS usd
  UNWIND range(0, size(ts) - $min_count) AS i
  WITH ts, cps, txs, usd, i, ts[i] + duration({{minutes: $window_minutes}}) AS window_end
  WHERE ts[i + $min_count - 1] <= window_end
  WITH ts, cps, txs, usd, [j IN range(i, size(ts) - 1) WHERE ts[j] <= window_end] AS idx
  CALL (cps, idx) {{
    UNWIND idx AS j
    RETURN count(DISTINCT cps[j]) AS n
  }}
  WITH ts, cps, txs, usd, idx, n
  WHERE n >= $min_count
  ORDER BY n DESC, ts[idx[0]]
  LIMIT 1
  RETURN n, [j IN idx | txs[j]] AS tx_ids, [j IN idx | cps[j]] AS cp_ids,
         ts[idx[0]] AS start, ts[idx[-1]] AS end,
         reduce(s = 0.0, j IN idx | s + usd[j]) AS total_usd
}}
RETURN h.id AS hub, n, tx_ids, cp_ids, start, end, total_usd
"""


def find_fans(
    driver: Driver,
    cfg: RuleConfig,
    direction: Direction,
    *,
    hubs: list[str] | None = None,
    timeout: float | None = None,
) -> list[FanAlert]:
    """Best qualifying window per hub, for every hub that has one."""
    min_count = cfg.fan_in_min_senders if direction == "in" else cfg.fan_out_min_receivers
    params = {
        "min_count": min_count,
        "window_minutes": int(cfg.fan_window_hours * 60),
        "hub_cap": cfg.hub_degree_cap,
        "hubs": hubs,
    }
    with driver.session() as session:
        result = session.run(Query(fan_query(direction), timeout=timeout), params)
        return [
            FanAlert(
                direction=direction,
                hub=r["hub"],
                counterparties=r["n"],
                tx_ids=tuple(r["tx_ids"]),
                counterparty_ids=tuple(r["cp_ids"]),
                start=r["start"].to_native(),
                end=r["end"].to_native(),
                total_usd=r["total_usd"],
            )
            for r in result
        ]
