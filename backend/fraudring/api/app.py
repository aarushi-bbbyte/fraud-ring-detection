"""FastAPI app serving alerts, rings, accounts, metrics, simulation and the live feed.

Run (from backend/):
    uvicorn fraudring.api.app:app --reload
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j import Driver
from pydantic import BaseModel, Field

from fraudring.db import get_driver
from fraudring.replay import FlagIndex, iter_transactions, tag
from fraudring.results import RESULTS_DIR, read_csv
from fraudring.simulate import inject_ring, remove_synthetic

# Alerts are ranked by the risk of their accounts once the ML model has scored
# them. Until then, by how often each rule's flags were actually laundering
# (transaction precision, results/rule_eval_overall.csv).
FALLBACK_PRIOR = {"cycle": 0.311, "fan_in": 0.014, "fan_out": 0.004}

ALERTS = """
MATCH (al:Alert)
WHERE $rule IS NULL OR al.rule = $rule
WITH al, coalesce(al.risk, $prior[al.rule]) AS risk
ORDER BY CASE WHEN $sort = 'recent' THEN al.updated_at END DESC, risk DESC, al.total_usd DESC
SKIP $offset LIMIT $limit
OPTIONAL MATCH (al)-[:PART_OF]->(r:Ring)
RETURN al {.id, .rule, .reason, .total_usd, .hops, .counterparties, .hub,
           start: toString(al.start), end: toString(al.end), transactions: size(al.tx_ids)} AS alert,
       risk, r.id AS ring, EXISTS { (al)-[:INVOLVES]->(:Account {bank: 'SIM'}) } AS synthetic
"""

RING = """
MATCH (r:Ring {id: $id})
CALL (r) {
  MATCH (r)<-[:PART_OF]-(al:Alert)
  RETURN collect(al {.id, .rule, .reason, .total_usd, .tx_ids,
                     start: toString(al.start), end: toString(al.end)}) AS alerts
}
CALL (r) {
  MATCH (r)<-[:PART_OF]-(:Alert)-[c:INVOLVES]->(a:Account)
  WITH a, collect(DISTINCT c.role) AS roles
  RETURN collect(a {.id, .bank, .risk_score, .in_degree, .out_degree, roles: roles}) AS accounts
}
RETURN r {.*} AS ring, alerts, accounts
"""

EDGES = """
UNWIND $tx_ids AS tid
MATCH (s:Account)-[t:SENT {tx_id: tid}]->(d:Account)
RETURN t.tx_id AS tx_id, s.id AS source, d.id AS target, t.amount AS amount, t.currency AS currency,
       t.amount_usd AS amount_usd, toString(t.timestamp) AS timestamp
"""

ACCOUNT = """
MATCH (a:Account {id: $id})
CALL (a) {
  OPTIONAL MATCH (a)<-[c:INVOLVES]-(al:Alert)
  OPTIONAL MATCH (al)-[:PART_OF]->(r:Ring)
  RETURN collect(CASE WHEN al IS NULL THEN null ELSE
           al {.id, .rule, .reason, .total_usd, role: c.role, ring: r.id} END) AS alerts
}
CALL (a) {
  OPTIONAL MATCH (a)-[s:SENT]->(b:Account) WHERE NOT s.is_self_loop
  WITH s, b ORDER BY s.timestamp DESC LIMIT $limit
  RETURN collect(CASE WHEN s IS NULL THEN null ELSE {tx_id: s.tx_id, source: $id, target: b.id,
           amount_usd: s.amount_usd, currency: s.currency, amount: s.amount,
           timestamp: toString(s.timestamp)} END) AS sent
}
CALL (a) {
  OPTIONAL MATCH (b:Account)-[s:SENT]->(a) WHERE NOT s.is_self_loop
  WITH s, b ORDER BY s.timestamp DESC LIMIT $limit
  RETURN collect(CASE WHEN s IS NULL THEN null ELSE {tx_id: s.tx_id, source: b.id, target: $id,
           amount_usd: s.amount_usd, currency: s.currency, amount: s.amount,
           timestamp: toString(s.timestamp)} END) AS received
}
RETURN a {.id, .bank, .account, .in_degree, .out_degree, .risk_score, .pagerank,
          .component_size, .in_ring} AS account, alerts, sent, received
"""

COUNTS = """
CALL () { MATCH (a:Account) RETURN count(a) AS accounts }
CALL () { MATCH ()-[s:SENT]->() RETURN count(s) AS transactions }
CALL () { MATCH (r:Ring) RETURN count(r) AS rings }
CALL () {
  MATCH (al:Alert)
  WITH al.rule AS rule, count(*) AS n
  RETURN collect({rule: rule, n: n}) AS alerts
}
RETURN accounts, transactions, rings, alerts
"""


class SimulateRequest(BaseModel):
    pattern: Literal["cycle", "fan_in", "fan_out"] = "cycle"
    size: int | None = Field(default=None, ge=2, le=40)


def _prior() -> dict[str, float]:
    rows = read_csv(RESULTS_DIR / "rule_eval_overall.csv")
    prior = {r["rule"]: r["precision"] for r in rows if r["rule"] in FALLBACK_PRIOR}
    return {**FALLBACK_PRIOR, **prior}


def create_app(driver: Driver | None = None) -> FastAPI:
    """Build the app. Tests pass their own driver; otherwise one is created from settings."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.driver = driver or get_driver()
        app.state.flags = FlagIndex(app.state.driver)
        app.state.prior = _prior()
        app.state.injected = []  # tagged transactions from simulated rings, in order
        app.state.injected_lock = threading.Lock()
        yield
        if driver is None:
            app.state.driver.close()

    app = FastAPI(title="Fraud-ring detection", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    if RESULTS_DIR.exists():
        app.mount("/results", StaticFiles(directory=RESULTS_DIR), name="results")

    def db(request: Request) -> Driver:
        return request.app.state.driver

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/alerts")
    def alerts(request: Request, limit: int = 50, offset: int = 0, rule: str | None = None,
               sort: Literal["risk", "recent"] = "risk") -> dict:
        records = db(request).execute_query(
            ALERTS, rule=rule, sort=sort, prior=request.app.state.prior,
            offset=max(offset, 0), limit=min(max(limit, 1), 500),
        ).records
        total = db(request).execute_query(
            "MATCH (al:Alert) WHERE $rule IS NULL OR al.rule = $rule RETURN count(al) AS n", rule=rule
        ).records[0]["n"]
        items = [
            r["alert"] | {"risk": r["risk"], "ring": r["ring"], "synthetic": r["synthetic"]}
            for r in records
        ]
        return {"total": total, "items": items}

    @app.get("/rings/{ring_id}")
    def ring(request: Request, ring_id: str, max_edges: int = 2000) -> dict:
        records = db(request).execute_query(RING, id=ring_id).records
        if not records:
            raise HTTPException(404, f"ring {ring_id} not found")
        rec = records[0]
        tx_rules: dict[int, set[str]] = {}
        for al in rec["alerts"]:
            for tx in al["tx_ids"]:
                tx_rules.setdefault(tx, set()).add(al["rule"])
        edges = db(request).execute_query(EDGES, tx_ids=list(tx_rules)[:max_edges]).records
        nodes = [
            a | {"core": any(role in ("origin", "member", "hub") for role in a["roles"])}
            for a in rec["accounts"]
        ]
        return {
            "ring": rec["ring"],
            "alerts": [{k: v for k, v in al.items() if k != "tx_ids"} for al in rec["alerts"]],
            "nodes": nodes,
            "edges": [dict(e) | {"rules": sorted(tx_rules[e["tx_id"]])} for e in edges],
            "truncated": len(tx_rules) > max_edges,
        }

    @app.get("/accounts/{account_id}")
    def account(request: Request, account_id: str, limit: int = 25) -> dict:
        records = db(request).execute_query(ACCOUNT, id=account_id, limit=min(max(limit, 1), 200)).records
        if not records:
            raise HTTPException(404, f"account {account_id} not found")
        rec = records[0]
        flags = request.app.state.flags
        edges = [e | {"rules": sorted({rule for _, rule in flags.get(e["tx_id"])})}
                 for e in rec["sent"] + rec["received"]]
        neighbours = sorted({e["source"] for e in edges} | {e["target"] for e in edges})
        return {
            "account": rec["account"],
            "risk_score": rec["account"].get("risk_score"),
            "reasons": [a["reason"] for a in rec["alerts"]],
            "alerts": rec["alerts"],
            "rings": sorted({a["ring"] for a in rec["alerts"] if a["ring"]}),
            "neighbourhood": {"nodes": [{"id": n} for n in neighbours], "edges": edges},
        }

    @app.get("/metrics")
    def metrics(request: Request) -> dict:
        counts = db(request).execute_query(COUNTS).records[0]
        return {
            "graph": {
                "accounts": counts["accounts"],
                "transactions": counts["transactions"],
                "rings": counts["rings"],
                "alerts": {a["rule"]: a["n"] for a in counts["alerts"] if a["rule"]},
            },
            "rules": {
                "overall": read_csv(RESULTS_DIR / "rule_eval_overall.csv"),
                "by_pattern": read_csv(RESULTS_DIR / "rule_eval_by_pattern.csv"),
            },
            "sweeps": {
                "cycles": read_csv(RESULTS_DIR / "sweep_cycles.csv"),
                "fans": read_csv(RESULTS_DIR / "sweep_fans.csv"),
                "cycle_tolerance": read_csv(RESULTS_DIR / "sweep_cycle_tolerance.csv"),
            },
            "ml": {
                "metrics": read_csv(RESULTS_DIR / "ml_metrics.csv"),
                "importance": read_csv(RESULTS_DIR / "ml_feature_importance.csv"),
            },
            "images": sorted(p.name for p in RESULTS_DIR.glob("*.png")) if RESULTS_DIR.exists() else [],
        }

    @app.post("/simulate/ring")
    def simulate(request: Request, body: SimulateRequest) -> dict:
        result = inject_ring(db(request), body.pattern, body.size)
        state = request.app.state
        state.flags.refresh()
        fresh = [tag(tx, state.flags) for tx in _transactions(db(request), result.tx_ids)]
        with state.injected_lock:
            state.injected.extend(fresh)
        return result.to_dict()

    @app.delete("/simulate")
    def clear_simulated(request: Request) -> dict:
        remove_synthetic(db(request))
        request.app.state.flags.refresh()
        return {"status": "removed"}

    @app.get("/stream/transactions")
    def stream(request: Request, start: datetime = datetime(2022, 9, 1), rate: float = 5.0) -> StreamingResponse:
        """Server-sent events: replayed transactions, plus simulated ones as soon as they're injected."""
        state = request.app.state
        delay = 1 / min(max(rate, 0.5), 200)

        def events():
            with state.injected_lock:
                seen_injected = len(state.injected)
            for tx in iter_transactions(state.driver, start):
                with state.injected_lock:
                    new, seen_injected = state.injected[seen_injected:], len(state.injected)
                for item in new + [tag(tx, state.flags)]:
                    yield f"data: {json.dumps(item)}\n\n"
                time.sleep(delay)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app


def _transactions(driver: Driver, tx_ids: list[int]) -> list[dict]:
    rows = driver.execute_query(EDGES, tx_ids=tx_ids).records
    return [
        {"tx_id": r["tx_id"], "timestamp": r["timestamp"], "src": r["source"], "dst": r["target"],
         "amount": r["amount"], "currency": r["currency"], "amount_usd": r["amount_usd"],
         "format": "ACH", "synthetic": True}
        for r in rows
    ]


app = create_app()
