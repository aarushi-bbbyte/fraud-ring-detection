"""USD conversion rates derived from the dataset itself.

Rows whose payment and receiving currencies differ show the exchange rate the
simulator used (amount received / amount paid). Every non-USD currency in
HI-Small has thousands of such rows paired directly with USD, and the implied
rates are tight (fiat varies less than 0.1% between the 5th and 95th percentile).
Using the median of those rows gives a rate per currency without any external
FX data. Bitcoin varies more (about 10k to 15k USD), so its USD amounts are rougher.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from fraudring.ingest.dataset import (
    AMOUNT_PAID,
    AMOUNT_RECEIVED,
    PAYMENT_CURRENCY,
    RECEIVING_CURRENCY,
)

USD = "US Dollar"


def derive_usd_rates(csv_path: Path) -> dict[str, float]:
    """Return USD per one unit of each currency, as the median implied rate.

    This scans the whole file regardless of any subset being loaded, so a given
    transaction always gets the same ``amount_usd``.
    """
    samples: dict[str, list[float]] = defaultdict(list)
    currencies: set[str] = {USD}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            paid_cur, recv_cur = row[PAYMENT_CURRENCY], row[RECEIVING_CURRENCY]
            currencies.add(paid_cur)
            currencies.add(recv_cur)
            if paid_cur == recv_cur:
                continue
            paid, recv = float(row[AMOUNT_PAID]), float(row[AMOUNT_RECEIVED])
            if paid <= 0 or recv <= 0:
                continue
            if recv_cur == USD:
                samples[paid_cur].append(recv / paid)
            elif paid_cur == USD:
                samples[recv_cur].append(paid / recv)

    rates = {USD: 1.0}
    for cur, values in samples.items():
        rates[cur] = statistics.median(values)
    missing = currencies - rates.keys()
    if missing:
        raise ValueError(f"no USD conversion rows for: {sorted(missing)}")
    return dict(sorted(rates.items()))


def load_usd_rates(csv_path: Path, cache_path: Path) -> dict[str, float]:
    """Read cached rates, deriving and caching them on first use (about 30 s for HI-Small)."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    rates = derive_usd_rates(csv_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(rates, indent=2), encoding="utf-8")
    return rates
