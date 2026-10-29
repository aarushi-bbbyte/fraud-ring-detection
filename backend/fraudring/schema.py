"""Constraints and indexes for the transaction graph.

Created before loading so every per-row ``MERGE``/``MATCH`` on ``Account.id`` is
an index seek instead of a label scan. The relationship indexes support the
time-window filters the detection rules use.
"""

from __future__ import annotations

from neo4j import Driver

SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.id IS UNIQUE",
    "CREATE INDEX sent_timestamp IF NOT EXISTS FOR ()-[s:SENT]-() ON (s.timestamp)",
    "CREATE INDEX sent_tx_id IF NOT EXISTS FOR ()-[s:SENT]-() ON (s.tx_id)",
    "CREATE INDEX sent_pattern IF NOT EXISTS FOR ()-[s:SENT]-() ON (s.pattern)",
]


def ensure_schema(driver: Driver) -> None:
    with driver.session() as session:
        for statement in SCHEMA_STATEMENTS:
            session.run(statement).consume()
        session.run("CALL db.awaitIndexes(300)").consume()
