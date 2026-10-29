"""Streaming parser for the IBM "Transactions for Anti-Money Laundering" files.

The CSV header repeats the column name ``Account`` (once for the sender, once
for the receiver), so rows are parsed by position, not by header name.

Everything here streams line by line. The HI-Small CSV is about 5M rows, and
holding it in a DataFrame takes several GB, which would compete with Neo4j for
RAM on a laptop.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Positional layout of both the transactions CSV and the transaction lines in the patterns file.
TIMESTAMP, FROM_BANK, FROM_ACCOUNT, TO_BANK, TO_ACCOUNT = 0, 1, 2, 3, 4
AMOUNT_RECEIVED, RECEIVING_CURRENCY, AMOUNT_PAID, PAYMENT_CURRENCY = 5, 6, 7, 8
PAYMENT_FORMAT, IS_LAUNDERING = 9, 10
N_FIELDS = 11
RAW_TS_FORMAT = "%Y/%m/%d %H:%M"

EXPECTED_HEADER = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account",
    "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency",
    "Payment Format", "Is Laundering",
]

RawRow = tuple[str, ...]


@dataclass(frozen=True)
class PatternTag:
    """Ground-truth laundering attempt that a transaction belongs to."""

    attempt_id: int
    pattern: str  # e.g. "CYCLE", "FAN-IN", "SCATTER-GATHER"
    detail: str | None  # e.g. "Max 10 hops"; absent for some pattern types


def account_id(bank: str, account: str) -> str:
    """Accounts are keyed by bank + account number.

    Account numbers are almost unique on their own, but 8 of them appear under
    two different banks in HI-Small. Keying on both keeps those as separate
    accounts. Bank codes keep their leading zeros.
    """
    return f"{bank}:{account}"


def endpoints(fields: RawRow) -> tuple[tuple[str, str], tuple[str, str]]:
    """``(bank, account)`` of the sender and the receiver."""
    return (fields[FROM_BANK], fields[FROM_ACCOUNT]), (fields[TO_BANK], fields[TO_ACCOUNT])


def parse_timestamp(raw: str) -> str:
    """Convert ``2022/09/01 00:20`` to an ISO local datetime string for Cypher's ``localdatetime()``.

    The dataset has minute resolution and no timezone, so a timezone-free local
    datetime is the honest representation.
    """
    return datetime.strptime(raw, RAW_TS_FORMAT).isoformat()


def read_patterns(path: Path) -> dict[RawRow, PatternTag]:
    """Map each transaction listed in the patterns file to its laundering attempt.

    Pattern transactions are byte-for-byte copies of CSV rows (verified: all 3,209
    match exactly one CSV row), so the raw field tuple works as a join key.
    Attempt IDs are assigned in file order, starting at 1.
    """
    tags: dict[RawRow, PatternTag] = {}
    current: PatternTag | None = None
    attempt_id = 0
    with path.open(newline="", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("BEGIN LAUNDERING ATTEMPT"):
                attempt_id += 1
                kind = line.split(" - ", 1)[1]
                pattern, _, detail = kind.partition(":")
                current = PatternTag(attempt_id, pattern.strip(), detail.strip() or None)
            elif line.startswith("END LAUNDERING ATTEMPT"):
                current = None
            elif current is not None:
                fields = tuple(next(csv.reader([line])))
                if len(fields) != N_FIELDS:
                    raise ValueError(f"malformed pattern transaction: {line!r}")
                tags[fields] = current
    return tags


def iter_raw_rows(
    path: Path, *, until: datetime | None = None, limit: int | None = None
) -> Iterator[tuple[int, RawRow]]:
    """Yield ``(tx_id, fields)`` for each CSV row, optionally filtered.

    ``tx_id`` is the 0-based row position in the full file, so the same
    transaction keeps the same ID whatever subset is loaded.

    ``until`` keeps rows strictly before that instant. The file is only roughly
    time-ordered (some rows jump back up to ~8 days), so this checks every row
    instead of stopping at the first late one. ``limit`` caps how many rows pass
    the filter.
    """
    # The raw "YYYY/MM/DD HH:MM" format sorts lexicographically, so string
    # comparison avoids parsing 5M timestamps just to filter them.
    until_key = until.strftime(RAW_TS_FORMAT) if until else None
    yielded = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != EXPECTED_HEADER:
            raise ValueError(f"unexpected CSV header: {header}")
        for tx_id, fields in enumerate(reader):
            if limit is not None and yielded >= limit:
                return
            if until_key is not None and fields[TIMESTAMP] >= until_key:
                continue
            yielded += 1
            yield tx_id, tuple(fields)


def to_record(
    tx_id: int, fields: RawRow, usd_rates: dict[str, float], tag: PatternTag | None
) -> dict:
    """Shape one raw row into the parameter map the Neo4j loader writes.

    ``amount``/``currency`` are the paid side (what left the sender), matching the
    graph model in the spec. The received side is kept as well, because 72k rows
    convert between currencies in transit. ``amount_usd`` makes amounts in
    different currencies comparable for the detection rules.
    """
    src = account_id(fields[FROM_BANK], fields[FROM_ACCOUNT])
    dst = account_id(fields[TO_BANK], fields[TO_ACCOUNT])
    amount = float(fields[AMOUNT_PAID])
    return {
        "tx_id": tx_id,
        "src": src,
        "dst": dst,
        "ts": parse_timestamp(fields[TIMESTAMP]),
        "amount": amount,
        "currency": fields[PAYMENT_CURRENCY],
        "amount_received": float(fields[AMOUNT_RECEIVED]),
        "receiving_currency": fields[RECEIVING_CURRENCY],
        "amount_usd": round(amount * usd_rates[fields[PAYMENT_CURRENCY]], 2),
        "format": fields[PAYMENT_FORMAT],
        "is_laundering": fields[IS_LAUNDERING] == "1",
        "is_self_loop": src == dst,
        "pattern": tag.pattern if tag else None,
        "attempt_id": tag.attempt_id if tag else None,
    }
