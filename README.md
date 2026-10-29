# Fraud-ring detection in payment networks

Detects money-laundering rings (cycles, fan-in, fan-out and more) in a payment
transaction graph stored in Neo4j, using the IBM "Transactions for Anti-Money
Laundering" dataset (HI-Small) as labeled ground truth.

> Work in progress. The full write-up (architecture, results, limitations) comes later.

## Setup

Requirements: Docker Desktop, Python 3.11+.

1. Download `HI-Small_Trans.csv` and `HI-Small_Patterns.txt` from Kaggle into `data/raw/`.
2. Create `.env` from the template and set a password:
   ```sh
   cp .env.example .env
   ```
3. Start Neo4j. The Graph Data Science plugin is downloaded on first start.
   ```sh
   docker compose up -d
   ```
   The Neo4j Browser is at http://localhost:7474.
4. Create a virtualenv and install the backend:
   ```sh
   python -m venv .venv
   .venv/Scripts/pip install -e "backend[dev]"    # Windows; use .venv/bin/pip elsewhere
   ```

## Loading data

Run from `backend/`:

```sh
python -m fraudring.ingest.load --until 2022-09-03 --reset   # first two days
python -m fraudring.ingest.load --limit 100000 --reset       # first N rows of the file
python -m fraudring.ingest.load --reset                      # full dataset (~5M transactions)
python -m fraudring.ingest.verify                            # counts + sample query
```

`--until` is usually the better subset option. The CSV is only roughly time-ordered,
and its first rows are dominated by self-transfers, so taking the first N rows
produces partial laundering patterns.

### Graph model

```
(:Account {id: "bank:account", bank, account})
(:Account)-[:SENT {tx_id, timestamp, amount, currency, amount_received,
                   receiving_currency, amount_usd, format, is_laundering,
                   is_self_loop, pattern, attempt_id}]->(:Account)
```

- `amount_usd` uses exchange rates derived from the dataset's own cross-currency rows.
- `pattern` and `attempt_id` come from the patterns file and are used only for evaluation.

## Tests

```sh
cd backend && python -m pytest
```
