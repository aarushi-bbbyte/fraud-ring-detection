"""Parsing tests for the dataset layer, using tiny fixture files in the real formats."""

from datetime import datetime
from pathlib import Path

import pytest

from fraudring.ingest.dataset import iter_raw_rows, read_patterns, to_record
from fraudring.ingest.fx import derive_usd_rates

FIXTURES = Path(__file__).parent / "fixtures"
CSV = FIXTURES / "mini_trans.csv"
PATTERNS = FIXTURES / "mini_patterns.txt"


@pytest.fixture(scope="module")
def rows():
    return list(iter_raw_rows(CSV))


@pytest.fixture(scope="module")
def tags():
    return read_patterns(PATTERNS)


def test_rows_parsed_positionally_despite_duplicate_header(rows):
    assert len(rows) == 10
    tx_id, fields = rows[1]
    assert tx_id == 1
    assert fields[2] == "A1" and fields[4] == "A2"


def test_until_filters_every_row_not_just_a_prefix():
    # Row 7 (2022/09/01 05:00) comes after later rows, so a naive
    # stop-at-first-late-row would drop it.
    kept = [tx_id for tx_id, _ in iter_raw_rows(CSV, until=datetime(2022, 9, 2))]
    assert kept == [0, 1, 2, 3, 7]


def test_limit_applies_after_until():
    kept = [tx_id for tx_id, _ in iter_raw_rows(CSV, until=datetime(2022, 9, 2), limit=2)]
    assert kept == [0, 1]


def test_patterns_assign_attempts_in_file_order(tags):
    assert len(tags) == 5
    cycle = {t for t in tags.values() if t.pattern == "CYCLE"}
    bipartite = {t for t in tags.values() if t.pattern == "BIPARTITE"}
    assert [(t.attempt_id, t.detail) for t in cycle] == [(1, "Max 3 hops")]
    assert [(t.attempt_id, t.detail) for t in bipartite] == [(2, None)]


def test_usd_rates_use_median_of_cross_currency_rows():
    rates = derive_usd_rates(CSV)
    assert rates["US Dollar"] == 1.0
    # Implied EUR rates: 1.172, 1.171, 1.173, so the median is 1.172.
    assert rates["Euro"] == pytest.approx(1.172)


def test_record_shape(rows, tags):
    rates = {"US Dollar": 1.0, "Euro": 1.172}

    self_loop = to_record(*rows[0], rates, tags.get(rows[0][1]))
    assert self_loop["is_self_loop"] is True
    assert self_loop["src"] == "010:8000EBD30"
    assert self_loop["pattern"] is None

    fx = to_record(*rows[1], rates, None)
    assert fx["ts"] == "2022-09-01T00:21:00"
    assert (fx["amount"], fx["currency"]) == (100.0, "Euro")
    assert (fx["amount_received"], fx["receiving_currency"]) == (117.2, "US Dollar")
    assert fx["amount_usd"] == 117.2
    assert fx["is_self_loop"] is False

    cycle_edge = to_record(*rows[4], rates, tags.get(rows[4][1]))
    assert cycle_edge["is_laundering"] is True
    assert (cycle_edge["pattern"], cycle_edge["attempt_id"]) == ("CYCLE", 1)
    # Leading zeros in bank codes are preserved.
    assert cycle_edge["src"] == "0071:C1"


def test_laundering_row_outside_patterns_stays_untyped(rows, tags):
    record = to_record(*rows[9], {"US Dollar": 1.0}, tags.get(rows[9][1]))
    assert record["is_laundering"] is True
    assert record["pattern"] is None
