"""Neo4j driver construction."""

from __future__ import annotations

from neo4j import Driver, GraphDatabase

from fraudring.config import Settings, get_settings


def get_driver(settings: Settings | None = None) -> Driver:
    """Create a driver and fail fast if the database is unreachable or the password is wrong."""
    settings = settings or get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        # "Property does not exist" warnings fire whenever a subset happens to
        # contain no edges with e.g. attempt_id. They're expected here, not typos.
        notifications_disabled_classifications=["UNRECOGNIZED"],
    )
    driver.verify_connectivity()
    return driver
