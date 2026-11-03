"""Durable embedding cache: a text is never sent to the provider twice."""

from __future__ import annotations

import sqlite3
from array import array
from pathlib import Path


class EmbeddingCache:
    """Vectors keyed by text hash (model + dimensions + text).

    Writes are committed before the matching Qdrant upsert, so quota spent on
    a batch survives a crash, a container stop or a lost collection.
    """

    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS embeddings (hash TEXT PRIMARY KEY, vector BLOB NOT NULL)"
        )
        self.db.commit()

    def get_many(self, hashes: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        for start in range(0, len(hashes), 500):
            batch = hashes[start:start + 500]
            placeholders = ",".join("?" * len(batch))
            for digest, blob in self.db.execute(
                f"SELECT hash, vector FROM embeddings WHERE hash IN ({placeholders})", batch
            ):
                found[digest] = array("f", blob).tolist()
        return found

    def put_many(self, vectors: dict[str, list[float]]):
        self.db.executemany(
            "INSERT OR REPLACE INTO embeddings VALUES (?, ?)",
            [(digest, array("f", vector).tobytes()) for digest, vector in vectors.items()],
        )
        self.db.commit()

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])

    def close(self):
        self.db.close()
