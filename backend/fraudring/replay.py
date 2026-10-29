"""Replay loaded transactions in time order, as a "live" feed.

The graph already holds the whole dataset, and batch detection has already run
over it. Replay walks the transactions in timestamp order and tags each one
with the alerts that cover it, so the dashboard can show a feed with
suspicious transfers highlighted. It doesn't write anything.

Usage (from backend/):
    python -m fraudring.replay --start 2022-09-05 --rate 20
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime

from neo4j import Driver

from fraudring.db import get_driver

# Uses the timestamp index for both the range and the ordering. Ties within a
# minute are skipped via $seen rather than a compound cursor, which would
# defeat the index.
PAGE = """
MATCH (a:Account)-[s:SENT]->(b:Account)
WHERE s.timestamp >= $after AND NOT s.tx_id IN $seen AND NOT s.is_self_loop
RETURN s.tx_id AS tx_id, s.timestamp AS ts, a.id AS src, b.id AS dst,
       s.amount AS amount, s.currency AS currency, s.amount_usd AS amount_usd,
       s.format AS format, coalesce(s.synthetic, false) AS synthetic
ORDER BY s.timestamp
LIMIT $limit
"""


class FlagIndex:
    """tx_id -> [(alert id, rule)] for every transaction covered by an alert.

    About 265k entries on HI-Small. Kept in memory so tagging a feed page costs
    nothing, and rebuilt after detection or a simulated ring adds alerts.
    """

    def __init__(self, driver: Driver):
        self.driver = driver
        self._lock = threading.Lock()
        self._index: dict[int, list[tuple[str, str]]] = {}
        self.refresh()

    def refresh(self) -> None:
        index: dict[int, list[tuple[str, str]]] = {}
        records = self.driver.execute_query(
            "MATCH (al:Alert) RETURN al.id AS id, al.rule AS rule, al.tx_ids AS txs"
        ).records
        for r in records:
            for tx in r["txs"]:
                index.setdefault(tx, []).append((r["id"], r["rule"]))
        with self._lock:
            self._index = index

    def get(self, tx_id: int) -> list[tuple[str, str]]:
        with self._lock:
            return self._index.get(tx_id, [])


def iter_transactions(driver: Driver, start: datetime, page_size: int = 200) -> Iterator[dict]:
    """Yield transactions from ``start`` onward in timestamp order, forever until exhausted."""
    after, seen = start, []
    while True:
        rows = driver.execute_query(PAGE, after=after, seen=seen, limit=page_size).records
        if not rows:
            return
        for r in rows:
            ts = r["ts"].to_native()
            if ts != after:
                after, seen = ts, []
            seen.append(r["tx_id"])
            yield {
                "tx_id": r["tx_id"],
                "timestamp": ts.isoformat(),
                "src": r["src"],
                "dst": r["dst"],
                "amount": r["amount"],
                "currency": r["currency"],
                "amount_usd": r["amount_usd"],
                "format": r["format"],
                "synthetic": r["synthetic"],
            }


def tag(tx: dict, flags: FlagIndex) -> dict:
    hits = flags.get(tx["tx_id"])
    return tx | {"alerts": [a for a, _ in hits], "rules": sorted({rule for _, rule in hits})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=datetime.fromisoformat, default=datetime(2022, 9, 1))
    parser.add_argument("--rate", type=float, default=10.0, help="transactions per second")
    parser.add_argument("--only-flagged", action="store_true")
    args = parser.parse_args(argv)

    driver = get_driver()
    try:
        flags = FlagIndex(driver)
        for tx in iter_transactions(driver, args.start):
            tx = tag(tx, flags)
            if args.only_flagged and not tx["rules"]:
                continue
            mark = f"\033[31m!! {','.join(tx['rules'])}\033[0m" if tx["rules"] else ""
            print(f"{tx['timestamp']}  {tx['src']:>20} -> {tx['dst']:<20} ${tx['amount_usd']:>12,.2f}  {mark}")
            time.sleep(1 / args.rate)
    except KeyboardInterrupt:
        pass
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
