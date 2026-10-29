"""Inject a synthetic fraud ring into the live graph and detect it immediately.

Used by the dashboard's "Simulate fraud ring" button. The ring's transactions
start one minute after the latest transaction in the graph, so they behave
like new activity. Detection then runs only on them (cycle rule anchored at
the new transactions, fan rules on the new hub), which takes seconds instead
of the full ~10-minute scan.

Synthetic accounts sit in bank ``SIM`` and their transactions have
``synthetic: true``. ``remove_synthetic`` deletes all of it, together with the
alerts and rings it produced, so evaluations run on the original data.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from neo4j import Driver

from fraudring.detection.alerts import cycle_alert, fan_alert, write_alerts
from fraudring.detection.config import RuleConfig
from fraudring.detection.cycles import find_cycles
from fraudring.detection.fans import find_fans
from fraudring.detection.rings import attach_to_rings

Pattern = Literal["cycle", "fan_in", "fan_out"]
SIM_BANK = "SIM"

CREATE = """
UNWIND $accounts AS id
CREATE (:Account {id: id, bank: $bank, account: split(id, ':')[1], synthetic: true})
WITH count(*) AS ignored
UNWIND $edges AS e
MATCH (s:Account {id: e.src}), (d:Account {id: e.dst})
CREATE (s)-[:SENT {
  tx_id: e.tx_id, timestamp: e.ts, amount: e.usd, currency: 'US Dollar',
  amount_received: e.usd, receiving_currency: 'US Dollar', amount_usd: e.usd,
  format: 'ACH', is_laundering: true, is_self_loop: false, synthetic: true
}]->(d)
"""

SET_DEGREES = """
UNWIND $ids AS id
MATCH (a:Account {id: id})
SET a.out_degree = COUNT { (a)-[r:SENT]->() WHERE NOT r.is_self_loop },
    a.in_degree  = COUNT { ()-[r:SENT]->(a) WHERE NOT r.is_self_loop }
"""

REMOVE = """
MATCH (a:Account {bank: $bank})
OPTIONAL MATCH (a)<-[:INVOLVES]-(al:Alert)
OPTIONAL MATCH (al)-[:PART_OF]->(r:Ring)
WITH collect(DISTINCT a) AS accounts, collect(DISTINCT al) AS alerts, collect(DISTINCT r) AS rings
FOREACH (x IN alerts | DETACH DELETE x)
FOREACH (x IN accounts | DETACH DELETE x)
WITH rings
UNWIND rings AS r
WITH r WHERE NOT EXISTS { (r)<-[:PART_OF]-(:Alert) }
DETACH DELETE r
"""


@dataclass
class SimulationResult:
    pattern: str
    accounts: list[str]
    tx_ids: list[int]
    start: datetime
    alerts: list[str] = field(default_factory=list)
    rings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        return d


def _next_ids(driver: Driver) -> tuple[int, datetime]:
    """Next free tx_id and the latest timestamp, both read through their indexes."""
    tx = driver.execute_query(
        "MATCH ()-[s:SENT]->() WHERE s.tx_id IS NOT NULL RETURN s.tx_id AS v ORDER BY v DESC LIMIT 1"
    ).records
    ts = driver.execute_query(
        "MATCH ()-[s:SENT]->() WHERE s.timestamp IS NOT NULL RETURN s.timestamp AS v ORDER BY v DESC LIMIT 1"
    ).records
    next_tx = (tx[0]["v"] + 1) if tx else 0
    latest = ts[0]["v"].to_native() if ts else datetime(2022, 9, 1)
    return next_tx, latest


def _edges(pattern: Pattern, accounts: list[str], start: datetime, rng: random.Random):
    """(src, dst, timestamp, usd) for each transfer of the synthetic ring."""
    if pattern == "cycle":
        # A chain that returns home, passing on ~98% each hop (a small "fee").
        amount = rng.uniform(5_000, 15_000)
        for i, src in enumerate(accounts):
            yield src, accounts[(i + 1) % len(accounts)], start + timedelta(minutes=25 * i), round(amount * 0.98**i, 2)
    else:
        hub, others = accounts[0], accounts[1:]
        for i, other in enumerate(others):
            ts = start + timedelta(minutes=15 * i)
            usd = round(rng.uniform(2_000, 9_000), 2)
            yield (other, hub, ts, usd) if pattern == "fan_in" else (hub, other, ts, usd)


def inject_ring(driver: Driver, pattern: Pattern, size: int | None = None, cfg: RuleConfig | None = None) -> SimulationResult:
    """Write a synthetic ring of ``pattern``, detect it, and return what was flagged.

    ``size`` is the number of accounts. Defaults: 5 for a cycle, and one hub plus
    two more counterparties than the fan threshold for fans. It's clamped so the
    rules can always catch the ring.
    """
    cfg = cfg or RuleConfig()
    t0 = time.perf_counter()
    if pattern == "cycle":
        size = max(3, min(size or 5, cfg.cycle_max_hops))
    else:
        threshold = cfg.fan_in_min_senders if pattern == "fan_in" else cfg.fan_out_min_receivers
        size = max(threshold + 1, size or threshold + 3)

    run = uuid.uuid4().hex[:6]
    accounts = [f"{SIM_BANK}:{run}{i:02d}" for i in range(size)]
    next_tx, latest = _next_ids(driver)
    start = latest + timedelta(minutes=1)
    rng = random.Random(run)
    edges = [
        {"tx_id": next_tx + i, "src": s, "dst": d, "ts": ts, "usd": usd}
        for i, (s, d, ts, usd) in enumerate(_edges(pattern, accounts, start, rng))
    ]
    driver.execute_query(CREATE, accounts=accounts, edges=edges, bank=SIM_BANK)
    driver.execute_query(SET_DEGREES, ids=accounts)

    tx_ids = [e["tx_id"] for e in edges]
    if pattern == "cycle":
        alerts = [cycle_alert(c, cfg.cycle_amount_tolerance) for c in find_cycles(driver, cfg, tx_ids=tx_ids)]
    else:
        direction = "in" if pattern == "fan_in" else "out"
        alerts = [fan_alert(f) for f in find_fans(driver, cfg, direction, hubs=[accounts[0]])]
    write_alerts(driver, alerts)
    alert_ids = [a["id"] for a in alerts]
    rings = attach_to_rings(driver, alert_ids)

    return SimulationResult(
        pattern=pattern, accounts=accounts, tx_ids=tx_ids, start=start,
        alerts=alert_ids, rings=sorted(set(rings)), seconds=round(time.perf_counter() - t0, 2),
    )


def remove_synthetic(driver: Driver) -> None:
    driver.execute_query(REMOVE, bank=SIM_BANK)
