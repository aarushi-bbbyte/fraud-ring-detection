"""Grouping alerts into rings with GDS weakly connected components.

Which accounts may join two alerts into one ring matters more than the
algorithm:

* Core accounts are cycle members and fan hubs. They are what the rules
  actually flagged.
* Counterparties are the many senders/receivers around a fan hub. Most are
  ordinary accounts that happened to pay a busy hub.

WCC runs only over core accounts. Two core accounts are linked by a transaction
only if, at both ends, it is part of the alert that makes that account core.
So a cycle's own edges link its members, and a scatter hub's payment that also
falls in a gather hub's fan-in window links those two hubs. A routine payment
between two busy hubs flagged for unrelated reasons does not. An account
that is core in two alerts also joins them, being one node in the projection.
Counterparties then join the ring of each alert they appear in, but never
merge rings.

Looser glue produced giant "rings" on HI-Small: 67k accounts when
counterparties could merge rings, and 13k when any transaction between two
core accounts could.

Graph model:
    (:Ring {id, size, alert_count, total_usd})
    (:Account)-[:IN_RING]->(:Ring)<-[:PART_OF]-(:Alert)
"""

from __future__ import annotations

from neo4j import Driver

GRAPH_NAME = "flagged-core"
CORE_ROLES = ["origin", "member", "hub"]

PROJECT = """
CALL () {
  MATCH (a:Account)<-[c:INVOLVES]-(:Alert)
  WHERE c.role IN $core
  RETURN DISTINCT a AS s, null AS d
  UNION
  MATCH (al:Alert)
  UNWIND al.tx_ids AS tid
  MATCH (s:Account)-[:SENT {tx_id: tid}]->(d:Account)
  WHERE EXISTS { (s)<-[c:INVOLVES]-(x:Alert) WHERE c.role IN $core AND tid IN x.tx_ids }
    AND EXISTS { (d)<-[c:INVOLVES]-(x:Alert) WHERE c.role IN $core AND tid IN x.tx_ids }
  RETURN DISTINCT s, d
}
WITH gds.graph.project($name, s, d) AS g
RETURN g.nodeCount AS nodes
"""

COMPONENTS = """
CALL gds.wcc.stream($name)
YIELD nodeId, componentId
RETURN gds.util.asNode(nodeId).id AS account, componentId AS component
"""

# Members are every account of every alert in the ring; stats are recomputed from them.
FILL_RING = """
CALL (r) {
  MATCH (r)<-[:PART_OF]-(:Alert)-[:INVOLVES]->(a:Account)
  WITH DISTINCT a
  MERGE (a)-[:IN_RING]->(r)
}
CALL (r) {
  MATCH (r)<-[:PART_OF]-(al:Alert)
  RETURN count(al) AS alerts, sum(al.total_usd) AS total
}
CALL (r) {
  MATCH (r)<-[:IN_RING]-(a:Account)
  RETURN count(a) AS size
}
SET r.alert_count = alerts, r.total_usd = total, r.size = size
"""

WRITE_RINGS = """
UNWIND $rings AS ring
CREATE (r:Ring {id: ring.id})
WITH r, ring
CALL (r, ring) {
  UNWIND ring.core AS aid
  MATCH (:Account {id: aid})<-[c:INVOLVES]-(al:Alert)
  WHERE c.role IN $core
  WITH DISTINCT al
  MERGE (al)-[:PART_OF]->(r)
}
""" + FILL_RING

# An existing ring that already holds one of this alert's core accounts as core.
FIND_RING = """
MATCH (al:Alert {id: $id})-[c:INVOLVES]->(:Account)<-[c2:INVOLVES]-(other:Alert)-[:PART_OF]->(r:Ring)
WHERE c.role IN $core AND c2.role IN $core AND other <> al
RETURN r.id AS ring
LIMIT 1
"""

ATTACH = """
MATCH (al:Alert {id: $alert})
MERGE (r:Ring {id: $ring})
MERGE (al)-[:PART_OF]->(r)
WITH r
""" + FILL_RING


def drop_projection(driver: Driver) -> None:
    driver.execute_query("CALL gds.graph.drop($name, false) YIELD graphName", name=GRAPH_NAME)


def build_rings(driver: Driver) -> list[list[str]]:
    """Recompute rings from current alerts. Returns each ring's accounts, largest ring first."""
    driver.execute_query("MATCH (r:Ring) DETACH DELETE r")
    if not driver.execute_query("MATCH (al:Alert) RETURN count(al) > 0 AS any").records[0]["any"]:
        return []
    drop_projection(driver)
    driver.execute_query(PROJECT, name=GRAPH_NAME, core=CORE_ROLES)
    try:
        records = driver.execute_query(COMPONENTS, name=GRAPH_NAME).records
    finally:
        drop_projection(driver)

    components: dict[int, list[str]] = {}
    for r in records:
        components.setdefault(r["component"], []).append(r["account"])
    cores = sorted((sorted(c) for c in components.values()), key=lambda c: (-len(c), c[0]))
    payload = [{"id": f"ring-{i + 1}", "core": core} for i, core in enumerate(cores)]
    for i in range(0, len(payload), 500):
        driver.execute_query(WRITE_RINGS, rings=payload[i : i + 500], core=CORE_ROLES)

    rings = driver.execute_query(
        "MATCH (r:Ring)<-[:IN_RING]-(a:Account) RETURN r.id AS id, collect(a.id) AS accounts"
    ).records
    return sorted((sorted(r["accounts"]) for r in rings), key=lambda a: (-len(a), a[0]))


def attach_to_rings(driver: Driver, alert_ids: list[str]) -> list[str]:
    """Place newly written alerts into rings without recomputing all of them.

    An alert joins the ring of another alert that shares one of its core
    accounts, or else starts a new ring. That's the same rule as the full
    rebuild for the shared-account case. It doesn't look for linking
    transactions, so the next full run may still merge rings this left apart.
    Returns the ring ID of each alert.
    """
    ring_ids = []
    for alert_id in alert_ids:
        found = driver.execute_query(FIND_RING, id=alert_id, core=CORE_ROLES).records
        ring_id = found[0]["ring"] if found else f"ring-{alert_id}"
        driver.execute_query(ATTACH, alert=alert_id, ring=ring_id)
        ring_ids.append(ring_id)
    return ring_ids
