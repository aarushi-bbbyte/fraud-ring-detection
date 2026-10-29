"""Per-account degree properties used by the detection rules.

``in_degree``/``out_degree`` count non-self-loop SENT edges. Stored on the node
so the fan rules can skip accounts that can't reach the threshold, or are
high-volume hubs, without expanding their edges first.
"""

from __future__ import annotations

from neo4j import Driver

UPDATE_DEGREES = """
MATCH (a:Account)
CALL (a) {
  SET a.out_degree = COUNT { (a)-[r:SENT]->() WHERE NOT r.is_self_loop },
      a.in_degree  = COUNT { ()-[r:SENT]->(a) WHERE NOT r.is_self_loop }
} IN TRANSACTIONS OF 20000 ROWS
"""


def degrees_missing(driver: Driver) -> bool:
    records, _, _ = driver.execute_query(
        "MATCH (a:Account) WHERE a.out_degree IS NULL RETURN count(a) > 0 AS missing"
    )
    return records[0]["missing"]


def update_degrees(driver: Driver) -> None:
    """Recompute degrees for every account (about 4 minutes on HI-Small)."""
    with driver.session() as session:
        session.run(UPDATE_DEGREES).consume()
