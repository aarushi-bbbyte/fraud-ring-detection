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

## Detection rules

Run from `backend/` after loading data:

```sh
python -m fraudring.detection.run                         # all rules with default thresholds
python -m fraudring.detection.run --fan-in-min-senders 10 # any threshold can be overridden
```

This runs three Cypher rules, stores each hit as an `(:Alert)` with a readable
reason, and groups alerts that share accounts into `(:Ring)`s using GDS weakly
connected components over the flagged subgraph.

| Rule | Flags | Defaults |
|---|---|---|
| Cycle | money leaves an account and returns, with time-ordered hops, each hop passing on a similar USD amount | ≤ 12 hops, within 96 h, ±20% per hop |
| Fan-in | one account receives from many distinct senders in a sliding window | ≥ 8 senders within 96 h |
| Fan-out | one account sends to many distinct receivers in a sliding window | ≥ 8 receivers within 96 h |

Fan rules skip high-volume hubs (more than 1,000 edges; 15 accounts in HI-Small).

### Choosing the thresholds

`python -m fraudring.detection.sweep` measures, for each threshold setting, the
share of ground-truth attempts captured, the query runtime and the alert volume.
It writes `results/sweep_*.csv` and `results/sweep_*.png`. The defaults above
sit at the knee of those curves. The reasoning is recorded in
`backend/fraudring/detection/config.py`.

## Dashboard

`docker compose up -d --build` starts Neo4j, the API and the dashboard at http://localhost:8080.

Demo: pick a pattern next to **Simulate fraud ring** and click it. A synthetic ring is
written into the graph and detected within seconds. A banner links to the new ring,
the alert appears at the top of *Alerts → Most recent first*, and its transfers
show up highlighted in the *Live feed*. `DELETE /simulate` (or `curl -X DELETE
localhost:8000/simulate`) removes all synthetic data again.

For frontend development: `cd frontend && npm install && npm run dev` (proxies `/api` to port 8000).

## API

The API runs on http://localhost:8000 (docs at `/docs`).
For local development, run `uvicorn fraudring.api.app:app --reload` from `backend/`.

| Endpoint | Purpose |
|---|---|
| `GET /alerts?sort=risk\|recent&rule=` | alerts with reasons, ranked by risk |
| `GET /rings/{id}` | ring accounts, alerts and money-flow edges, for graph visualisation |
| `GET /accounts/{id}` | account details, reasons it was flagged, recent neighbourhood |
| `GET /metrics` | graph counts and the evaluation results from `results/` |
| `POST /simulate/ring` `{"pattern": "cycle"\|"fan_in"\|"fan_out"}` | injects a synthetic ring and detects it within seconds |
| `DELETE /simulate` | removes all synthetic data |
| `GET /stream/transactions?start=&rate=` | live feed (server-sent events) replaying transactions in time order, flagged ones tagged |

`python -m fraudring.replay --start 2022-09-05 --rate 20` prints the same feed in the terminal.

## Tests

Unit tests need nothing running. The rule tests use a separate, throwaway Neo4j
so they never touch the loaded dataset:

```sh
docker compose --profile test up -d neo4j-test
cd backend && python -m pytest
docker compose --profile test stop neo4j-test
```

Without `neo4j-test` running, the database tests are skipped.
