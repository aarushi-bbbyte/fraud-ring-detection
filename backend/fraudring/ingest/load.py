"""Load the IBM AML transactions CSV into Neo4j.

Graph model:
    (:Account {id, bank, account})
    (:Account)-[:SENT {tx_id, timestamp, amount, currency, amount_received,
                       receiving_currency, amount_usd, format, is_laundering,
                       is_self_loop, pattern, attempt_id}]->(:Account)

``pattern``/``attempt_id`` hold ground truth from the patterns file. They exist
only for evaluation; detection rules and ML features must never read them.

Usage (from backend/):
    python -m fraudring.ingest.load --limit 100000
    python -m fraudring.ingest.load --until 2022-09-05 --reset
    python -m fraudring.ingest.load --reset            # full dataset
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import islice
from typing import TypeVar

from neo4j import Driver, ManagedTransaction

from fraudring.config import get_settings
from fraudring.db import get_driver
from fraudring.ingest.dataset import RawRow, account_id, endpoints, iter_raw_rows, read_patterns, to_record
from fraudring.ingest.fx import load_usd_rates
from fraudring.schema import ensure_schema

T = TypeVar("T")

# Accounts are created in their own statement before the edges, so the edge
# statement is a pure MATCH + CREATE. The loader only runs on an empty graph and
# tracks which accounts it has already written, so plain CREATE is safe and
# avoids the per-row lock-and-check cost of MERGE (measured at about 1.3 s per 10k rows).
CREATE_ACCOUNTS = """
UNWIND $accounts AS a
CREATE (:Account {id: a.id, bank: a.bank, account: a.account})
"""

CREATE_EDGES = """
UNWIND $rows AS r
MATCH (s:Account {id: r.src})
MATCH (d:Account {id: r.dst})
CREATE (s)-[:SENT {
  tx_id: r.tx_id,
  timestamp: localdatetime(r.ts),
  amount: r.amount,
  currency: r.currency,
  amount_received: r.amount_received,
  receiving_currency: r.receiving_currency,
  amount_usd: r.amount_usd,
  format: r.format,
  is_laundering: r.is_laundering,
  is_self_loop: r.is_self_loop,
  pattern: r.pattern,
  attempt_id: r.attempt_id
}]->(d)
"""


def batched(items: Iterable[T], size: int) -> Iterator[list[T]]:
    it = iter(items)
    while batch := list(islice(it, size)):
        yield batch


def new_accounts(batch: list[tuple[int, RawRow]], seen: set[str]) -> list[dict]:
    """Accounts in this batch that have not been written yet. Marks them as seen."""
    fresh = []
    for _, fields in batch:
        for bank, account in endpoints(fields):
            aid = account_id(bank, account)
            if aid not in seen:
                seen.add(aid)
                fresh.append({"id": aid, "bank": bank, "account": account})
    return fresh


def write_batch(tx: ManagedTransaction, accounts: list[dict], rows: list[dict]) -> None:
    if accounts:
        tx.run(CREATE_ACCOUNTS, accounts=accounts).consume()
    tx.run(CREATE_EDGES, rows=rows).consume()


def graph_is_empty(driver: Driver) -> bool:
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) > 0 AS any")
    return not records[0]["any"]


def reset_graph(driver: Driver) -> None:
    """Delete all data in batches so a 5M-edge graph doesn't need one giant transaction.

    Relationships go first. Deleting nodes directly would put hub accounts with
    hundreds of thousands of edges into a single inner transaction.
    """
    with driver.session() as session:
        session.run(
            "MATCH ()-[r]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 50000 ROWS"
        ).consume()
        session.run(
            "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 50000 ROWS"
        ).consume()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="load at most N rows (after --until filtering)")
    parser.add_argument(
        "--until",
        type=datetime.fromisoformat,
        help="only load transactions before this date/time, e.g. 2022-09-05",
    )
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--reset", action="store_true", help="delete existing graph data first")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    if not settings.transactions_csv.exists():
        print(f"missing {settings.transactions_csv}; download the dataset into data/raw/", file=sys.stderr)
        return 1

    driver = get_driver(settings)
    try:
        if args.reset:
            print("Resetting graph...")
            reset_graph(driver)
        elif not graph_is_empty(driver):
            print("Graph already has data. Re-run with --reset to replace it.", file=sys.stderr)
            return 1

        ensure_schema(driver)

        print("Loading USD rates...")
        rates = load_usd_rates(settings.transactions_csv, settings.processed_dir / f"{settings.dataset}_usd_rates.json")
        tags = read_patterns(settings.patterns_txt)
        print(f"{len(rates)} currencies, {len(tags)} pattern transactions in ground truth")

        raw_rows = iter_raw_rows(settings.transactions_csv, until=args.until, limit=args.limit)
        seen: set[str] = set()
        start = time.perf_counter()
        loaded = 0
        with driver.session() as session:
            for batch in batched(raw_rows, args.batch_size):
                accounts = new_accounts(batch, seen)
                rows = [to_record(tx_id, fields, rates, tags.get(fields)) for tx_id, fields in batch]
                session.execute_write(write_batch, accounts, rows)
                loaded += len(batch)
                if loaded % (args.batch_size * 20) == 0:
                    elapsed = time.perf_counter() - start
                    print(f"  {loaded:>9,} rows  {loaded / elapsed:,.0f} rows/s")
        elapsed = time.perf_counter() - start
        print(f"Loaded {loaded:,} transactions in {elapsed:,.1f}s")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
