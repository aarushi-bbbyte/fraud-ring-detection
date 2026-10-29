"""Cycle rule: money that leaves an account and comes back to it.

A cycle is a simple path ``a -> n1 -> ... -> a`` where:
  * hops are time-ordered (each transfer happens at or after the previous one),
  * the last hop lands within ``window`` of the first,
  * each hop passes on a similar USD amount to the previous one (``tolerance``).

How the query is built, and why:

* Hops are written out one by one, with a WITH between them, instead of as a
  variable-length pattern (``-[*2..k]->``). A variable-length match can only
  check time order after the whole path exists, and that blows up past ~3
  hops on this graph. Explicit hops let each branch be dropped as soon as one
  transfer breaks the time, amount, or simple-path condition.
* One pass finds every length from 2 to ``max_hops``. At each depth the query
  records cycles that close back to the origin, then extends the path with
  OPTIONAL MATCH. Paths that can't go further survive as "dead" rows (cur is
  null), so the cycles they already found aren't lost. One query per length
  would repeat the expensive first expansion for every length.
* A cycle is found from its earliest transfer only, because hops are
  time-ordered. Ties in the minute-resolution timestamps can still find it
  more than once, and so can a branch that copies a row's earlier findings, so
  results are de-duplicated on the set of transactions.
* Self-loops never qualify: a self-loop at the first hop fails ``cur <> a``,
  and any later one would revisit a node already on the path. That avoids
  reading an ``is_self_loop`` property on every expanded edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from neo4j import Driver, Query

from fraudring.detection.config import RuleConfig

ANCHOR_BY_TIME = "r.timestamp >= $start AND r.timestamp < $end"
ANCHOR_BY_TX = "r.tx_id IN $tx_ids"

HOP_OK = (
    "prev_t <= r.timestamp <= deadline "
    "AND $amount_lo * prev_usd <= r.amount_usd <= $amount_hi * prev_usd"
)

CLOSE = f"""WITH a, t0, deadline, prev_t, prev_usd, cur, txs, amts, path,
     found + CASE WHEN cur IS NULL THEN [] ELSE
       [(cur)-[r:SENT]->(a) WHERE {HOP_OK} |
        {{tx_ids: txs + r.tx_id, amounts: amts + r.amount_usd, end: r.timestamp,
          accounts: [n IN path | n.id]}}]
     END AS found"""

EXTEND = f"""OPTIONAL MATCH (cur)-[r:SENT]->(nxt:Account)
WHERE {HOP_OK} AND NOT nxt IN path
WITH a, t0, deadline, found, nxt AS cur,
     r.timestamp AS prev_t, r.amount_usd AS prev_usd,
     txs + r.tx_id AS txs, amts + r.amount_usd AS amts, path + nxt AS path
WHERE cur IS NOT NULL OR size(found) > 0"""


@dataclass(frozen=True)
class Cycle:
    tx_ids: tuple[int, ...]
    accounts: tuple[str, ...]  # in flow order, starting at the origin
    amounts_usd: tuple[float, ...]
    start: datetime
    end: datetime

    @property
    def hops(self) -> int:
        return len(self.tx_ids)


def cycle_query(max_hops: int, anchor: str = ANCHOR_BY_TIME) -> str:
    """Build the Cypher finding cycles of 2..``max_hops`` hops.

    ``anchor`` filters the first transfer, either by a time range (detection
    runs) or by a list of transaction IDs (evaluating against known patterns).
    """
    if max_hops < 2:
        raise ValueError("a cycle needs at least 2 hops")
    parts = [
        f"""MATCH (a:Account)-[r:SENT]->(cur:Account)
WHERE {anchor} AND cur <> a
WITH a, r.timestamp AS t0, r.timestamp + duration({{minutes: $window_minutes}}) AS deadline,
     r.timestamp AS prev_t, r.amount_usd AS prev_usd,
     cur, [r.tx_id] AS txs, [r.amount_usd] AS amts, [a, cur] AS path, [] AS found"""
    ]
    for depth in range(2, max_hops + 1):
        parts.append(CLOSE)
        if depth < max_hops:
            parts.append(EXTEND)
    parts.append(
        """UNWIND found AS c
RETURN c.tx_ids AS tx_ids, c.accounts AS accounts, c.amounts AS amounts, t0 AS start, c.end AS end"""
    )
    return "\n".join(parts)


def query_params(cfg: RuleConfig) -> dict:
    return {
        "window_minutes": int(cfg.cycle_window_hours * 60),
        "amount_lo": 1 - cfg.cycle_amount_tolerance,
        "amount_hi": 1 + cfg.cycle_amount_tolerance,
    }


def find_cycles(
    driver: Driver,
    cfg: RuleConfig,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    tx_ids: list[int] | None = None,
    timeout: float | None = None,
) -> list[Cycle]:
    """Cycles of 2..``cfg.cycle_max_hops`` hops, de-duplicated.

    Pass either a time range for the first transfer (``start``/``end``) or
    explicit ``tx_ids``. With neither, the whole graph is scanned.
    """
    params = query_params(cfg)
    if tx_ids is not None:
        anchor = ANCHOR_BY_TX
        params["tx_ids"] = tx_ids
    else:
        anchor = ANCHOR_BY_TIME
        params["start"] = start or datetime(1900, 1, 1)
        params["end"] = end or datetime(2100, 1, 1)
    unique: dict[frozenset[int], Cycle] = {}
    with driver.session() as session:
        result = session.run(Query(cycle_query(cfg.cycle_max_hops, anchor), timeout=timeout), params)
        for r in result:
            unique.setdefault(
                frozenset(r["tx_ids"]),
                Cycle(
                    tx_ids=tuple(r["tx_ids"]),
                    accounts=tuple(r["accounts"]),
                    amounts_usd=tuple(r["amounts"]),
                    start=r["start"].to_native(),
                    end=r["end"].to_native(),
                ),
            )
    return list(unique.values())
