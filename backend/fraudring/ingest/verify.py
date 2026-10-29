"""Sanity checks after a load: counts, ground-truth coverage, GDS availability, and a sample query.

Usage (from backend/):
    python -m fraudring.ingest.verify
"""

from __future__ import annotations

import sys

from neo4j import Driver

from fraudring.db import get_driver

COUNTS = """
MATCH ()-[s:SENT]->()
RETURN count(s) AS edges,
       sum(CASE WHEN s.is_laundering THEN 1 ELSE 0 END) AS laundering,
       sum(CASE WHEN s.is_self_loop THEN 1 ELSE 0 END) AS self_loops,
       sum(CASE WHEN s.is_laundering AND s.pattern IS NULL THEN 1 ELSE 0 END) AS laundering_untyped,
       min(s.timestamp) AS first_ts,
       max(s.timestamp) AS last_ts
"""

PATTERNS = """
MATCH ()-[s:SENT]->()
WHERE s.pattern IS NOT NULL
RETURN s.pattern AS pattern, count(DISTINCT s.attempt_id) AS attempts, count(s) AS edges
ORDER BY pattern
"""

# Sample query: replay one ground-truth cycle in time order. Only attempts whose
# money returns to the starting account in the loaded data qualify. A subset
# load can cut an attempt off before its last hop.
SAMPLE_CYCLE = """
MATCH (a:Account)-[s:SENT {pattern: 'CYCLE'}]->(b:Account)
WITH s.attempt_id AS attempt, a, s, b ORDER BY s.timestamp
WITH attempt, collect({src: a.id, dst: b.id, ts: s.timestamp, amount: s.amount,
                       currency: s.currency, usd: s.amount_usd}) AS hops
WHERE size(hops) >= 3 AND hops[0].src = hops[-1].dst
RETURN attempt, hops
ORDER BY attempt
LIMIT 1
"""


def run(driver: Driver) -> bool:
    ok = True
    accounts = driver.execute_query("MATCH (a:Account) RETURN count(a) AS n").records[0]["n"]
    c = driver.execute_query(COUNTS).records[0]
    print(f"Accounts:            {accounts:,}")
    print(f"SENT edges:          {c['edges']:,}")
    print(f"  laundering:        {c['laundering']:,}")
    print(f"  untyped laundering:{c['laundering_untyped']:>8,}  (labeled 1 but not in the patterns file)")
    print(f"  self-loops:        {c['self_loops']:,}")
    print(f"Time range:          {c['first_ts']} -> {c['last_ts']}")
    if c["edges"] == 0:
        print("No transactions loaded.")
        return False

    print("\nGround-truth patterns present:")
    for r in driver.execute_query(PATTERNS).records:
        print(f"  {r['pattern']:<15} {r['attempts']:>4} attempts  {r['edges']:>5} edges")

    try:
        version = driver.execute_query("RETURN gds.version() AS v").records[0]["v"]
        print(f"\nGDS version:         {version}")
    except Exception as exc:  # noqa: BLE001 - surface any plugin problem verbatim
        print(f"\nGDS NOT available: {exc}")
        ok = False

    records = driver.execute_query(SAMPLE_CYCLE).records
    if records:
        hops = records[0]["hops"]
        print(f"\nSample: ground-truth cycle attempt {records[0]['attempt']} ({len(hops)} hops, returns to origin)")
        for h in hops:
            print(f"  {h['ts']}  {h['src']:>18} -> {h['dst']:<18} {h['amount']:>14,.2f} {h['currency']:<17} (${h['usd']:,.2f})")
    else:
        print("\nNo complete ground-truth cycle in this subset (expected for small loads).")
    return ok


def main() -> int:
    driver = get_driver()
    try:
        return 0 if run(driver) else 1
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
