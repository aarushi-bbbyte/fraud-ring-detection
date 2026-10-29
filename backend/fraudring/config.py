"""Runtime settings, read from the environment and the repo-level .env file.

A single .env at the repo root is shared with docker compose so the database
password and ports are defined in exactly one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    data_dir: Path
    dataset: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def transactions_csv(self) -> Path:
        return self.raw_dir / f"{self.dataset}_Trans.csv"

    @property
    def patterns_txt(self) -> Path:
        return self.raw_dir / f"{self.dataset}_Patterns.txt"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        data_dir=data_dir,
        dataset=os.getenv("DATASET", "HI-Small"),
    )
