"""Durable, idempotent offline queue for measurements."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class OfflineQueue:
    """Local spool only; the official history remains in central PostgreSQL."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS queue (measurement_uuid TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def put(self, measurement_uuid: str, payload: dict[str, Any], created_at: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO queue(measurement_uuid, payload, created_at) VALUES (?, ?, ?)",
                (measurement_uuid, json.dumps(payload, ensure_ascii=False), created_at),
            )

    def items(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT measurement_uuid, payload FROM queue ORDER BY created_at").fetchall()
        return [{"measurement_uuid": uuid, **json.loads(payload)} for uuid, payload in rows]

    def remove(self, measurement_uuid: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM queue WHERE measurement_uuid = ?", (measurement_uuid,))

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as db:
            return int(db.execute("SELECT COUNT(*) FROM queue").fetchone()[0])
