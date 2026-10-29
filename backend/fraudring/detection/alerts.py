"""Turning rule hits into stored alerts with human-readable reasons.

Graph model:
    (:Alert {id, rule, reason, tx_ids, start, end, total_usd, ...})
    (:Alert)-[:INVOLVES {role}]->(:Account)

``tx_ids`` points back to the SENT edges that triggered the alert (indexed),
so a ring can be drawn without storing the edges twice.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from neo4j import Driver

from fraudring.detection.cycles import Cycle
from fraudring.detection.fans import FanAlert

WRITE_ALERTS = """
UNWIND $alerts AS al
MERGE (x:Alert {id: al.id})
SET x += al.props, x.updated_at = localdatetime()
WITH x, al
CALL (x) {
  MATCH (x)-[old:INVOLVES]->()
  DELETE old
}
WITH x, al
UNWIND al.involves AS inv
MATCH (a:Account {id: inv.account})
MERGE (x)-[:INVOLVES {role: inv.role}]->(a)
"""


def humanize(delta: timedelta) -> str:
    """Short duration for reasons: '45 min', '7.5 h', '2 d 3 h'."""
    minutes = delta.total_seconds() / 60
    if minutes < 120:
        return f"{minutes:.0f} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} h"
    days, rem = divmod(round(hours), 24)
    return f"{days} d {rem} h"


def usd(amount: float) -> str:
    return f"${amount:,.0f}"


def cycle_alert(c: Cycle, tolerance: float) -> dict:
    origin = c.accounts[0]
    reason = (
        f"Part of a {c.hops}-hop cycle: {usd(c.amounts_usd[0])} left {origin} and "
        f"{usd(c.amounts_usd[-1])} came back {humanize(c.end - c.start)} later, "
        f"through {c.hops - 1} other account{'s' if c.hops > 2 else ''} "
        f"(each hop within ±{tolerance:.0%} of the previous amount)."
    )
    key = ",".join(map(str, sorted(c.tx_ids)))
    return {
        "id": "cycle-" + hashlib.sha1(key.encode()).hexdigest()[:12],
        "props": {
            "rule": "cycle",
            "reason": reason,
            "tx_ids": list(c.tx_ids),
            "accounts": list(c.accounts),
            "start": c.start,
            "end": c.end,
            "total_usd": round(sum(c.amounts_usd), 2),
            "hops": c.hops,
        },
        "involves": [{"account": origin, "role": "origin"}]
        + [{"account": a, "role": "member"} for a in c.accounts[1:]],
    }


def fan_alert(f: FanAlert) -> dict:
    verb, side = ("received from", "sender") if f.direction == "in" else ("sent to", "receiver")
    reason = (
        f"Fan-{f.direction}: {verb} {f.counterparties} distinct accounts "
        f"within {humanize(f.end - f.start)} ({len(f.tx_ids)} transfers, {usd(f.total_usd)} total)."
    )
    return {
        "id": f"fan_{f.direction}-{f.hub}",
        "props": {
            "rule": f"fan_{f.direction}",
            "reason": reason,
            "hub": f.hub,
            "tx_ids": list(f.tx_ids),
            "start": f.start,
            "end": f.end,
            "total_usd": round(f.total_usd, 2),
            "counterparties": f.counterparties,
        },
        "involves": [{"account": f.hub, "role": "hub"}]
        + [{"account": a, "role": side} for a in sorted(set(f.counterparty_ids))],
    }


def clear_alerts(driver: Driver) -> None:
    """Remove all alerts and rings, so a full detection run starts from scratch."""
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n:Alert OR n:Ring "
            "CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS"
        ).consume()


def write_alerts(driver: Driver, alerts: list[dict], batch_size: int = 1000) -> None:
    for i in range(0, len(alerts), batch_size):
        driver.execute_query(WRITE_ALERTS, alerts=alerts[i : i + batch_size])
