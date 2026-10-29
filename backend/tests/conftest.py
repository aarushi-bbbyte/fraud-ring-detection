"""Fixtures for tests that need a real Neo4j.

They run against the throwaway ``neo4j-test`` container, never the main
database. Start it with:

    docker compose --profile test up -d neo4j-test
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from neo4j import Driver, GraphDatabase

from fraudring.config import get_settings
from fraudring.detection.degrees import update_degrees
from fraudring.schema import ensure_schema

T0 = datetime(2022, 9, 1)
# Refuse to wipe anything bigger than a hand-built test graph.
MAX_TEST_NODES = 10_000


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


class GraphBuilder:
    """Collects accounts and transfers, then writes them in the loader's graph model."""

    def __init__(self, driver: Driver):
        self.driver = driver
        self.edges: list[dict] = []

    def send(self, src: str, dst: str, hours: float, usd: float = 1000.0) -> int:
        tx_id = len(self.edges)
        self.edges.append(
            {
                "tx_id": tx_id, "src": src, "dst": dst, "ts": at(hours), "usd": usd,
                "self": src == dst,
            }
        )
        return tx_id

    def commit(self) -> None:
        accounts = sorted({e["src"] for e in self.edges} | {e["dst"] for e in self.edges})
        self.driver.execute_query(
            "UNWIND $ids AS id CREATE (:Account {id: id, bank: split(id, ':')[0], account: id})",
            ids=accounts,
        )
        self.driver.execute_query(
            """
            UNWIND $edges AS e
            MATCH (s:Account {id: e.src}), (d:Account {id: e.dst})
            CREATE (s)-[:SENT {tx_id: e.tx_id, timestamp: e.ts, amount: e.usd, currency: 'US Dollar',
                               amount_usd: e.usd, is_self_loop: e.self, is_laundering: false}]->(d)
            """,
            edges=self.edges,
        )
        update_degrees(self.driver)


@pytest.fixture(scope="session")
def test_driver():
    settings = get_settings()
    uri = os.getenv("NEO4J_TEST_URI", "bolt://localhost:7688")
    if uri == settings.neo4j_uri:
        pytest.exit("NEO4J_TEST_URI must not point at the main database")
    driver = GraphDatabase.driver(
        uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        notifications_disabled_classifications=["UNRECOGNIZED"],
    )
    try:
        driver.verify_connectivity()
    except Exception:  # noqa: BLE001
        driver.close()
        pytest.skip("neo4j-test is not running: docker compose --profile test up -d neo4j-test")
    ensure_schema(driver)
    yield driver
    driver.close()


@pytest.fixture
def graph(test_driver) -> GraphBuilder:
    nodes = test_driver.execute_query("MATCH (n) RETURN count(n) AS n").records[0]["n"]
    if nodes > MAX_TEST_NODES:
        pytest.exit(f"test database has {nodes:,} nodes; refusing to wipe it")
    test_driver.execute_query("MATCH (n) DETACH DELETE n")
    return GraphBuilder(test_driver)
