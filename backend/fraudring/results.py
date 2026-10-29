"""Reading and writing the CSVs in results/ shared by the scripts and the API."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from fraudring.config import REPO_ROOT

# Overridable so the API container can read results from a mounted volume.
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", REPO_ROOT / "results"))


def _num(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def read_csv(path: Path) -> list[dict]:
    """Rows with numeric columns parsed as numbers; an empty list if the file is missing."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: _num(v) for k, v in row.items()} for row in csv.DictReader(f)]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path}")
