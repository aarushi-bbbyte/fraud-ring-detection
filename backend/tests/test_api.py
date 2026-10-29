"""API end to end on the test database: simulate a ring, then find it through every endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fraudring.api.app import create_app


@pytest.fixture
def client(graph):
    graph.send("N:1", "N:2", 1, 100)  # a little ordinary data so the graph isn't empty
    graph.commit()
    with TestClient(create_app(graph.driver)) as c:
        yield c


def test_simulated_cycle_is_alerted_and_explorable(client):
    sim = client.post("/simulate/ring", json={"pattern": "cycle", "size": 5}).json()
    assert len(sim["accounts"]) == 5
    assert len(sim["alerts"]) == 1 and len(sim["rings"]) == 1

    alerts = client.get("/alerts", params={"sort": "recent"}).json()
    assert alerts["items"][0]["id"] == sim["alerts"][0]
    assert alerts["items"][0]["synthetic"] is True
    assert alerts["items"][0]["reason"].startswith("Part of a 5-hop cycle")

    ring = client.get(f"/rings/{sim['rings'][0]}").json()
    assert {n["id"] for n in ring["nodes"]} == set(sim["accounts"])
    assert len(ring["edges"]) == 5
    assert all(e["rules"] == ["cycle"] for e in ring["edges"])

    account = client.get(f"/accounts/{sim['accounts'][0]}").json()
    assert account["rings"] == sim["rings"]
    assert account["reasons"] and len(account["neighbourhood"]["edges"]) == 2

    assert client.delete("/simulate").status_code == 200
    assert client.get(f"/rings/{sim['rings'][0]}").status_code == 404
    assert client.get("/alerts").json()["total"] == 0


@pytest.mark.parametrize("pattern", ["fan_in", "fan_out"])
def test_simulated_fans_are_alerted(client, pattern):
    sim = client.post("/simulate/ring", json={"pattern": pattern}).json()
    assert len(sim["alerts"]) == 1
    alert = client.get("/alerts").json()["items"][0]
    assert alert["rule"] == pattern


def test_metrics_and_unknown_ids(client):
    m = client.get("/metrics").json()
    assert m["graph"]["accounts"] == 2
    assert client.get("/rings/nope").status_code == 404
    assert client.get("/accounts/nope").status_code == 404
