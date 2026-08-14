"""Local-only SQLite store for saved searches ("watches").

Everything here stays on the user's own machine, under a per-user data
directory. Nothing is uploaded or shared. The store exists so that "what's new
since I last looked?" can be answered without re-reading anything but ids —
i.e. it records which finnkoder a watch has already seen, not a mirror of FINN's
content.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


def default_db_path() -> Path:
    """Per-user data location, overridable with FINN_AGENT_DB for tests."""
    override = os.environ.get("FINN_AGENT_DB")
    if override:
        return Path(override).expanduser()
    base = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )
    return base / "finn-agent" / "watches.db"


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                vertical TEXT NOT NULL,
                query TEXT,
                filters TEXT,
                sort TEXT,
                created_at INTEGER NOT NULL,
                last_checked_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS seen (
                watch_id INTEGER NOT NULL,
                finnkode TEXT NOT NULL,
                first_seen_at INTEGER NOT NULL,
                PRIMARY KEY (watch_id, finnkode),
                FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
            );
            """
        )
        self._db.commit()

    # -- watches ---------------------------------------------------------------

    def create_watch(
        self,
        name: str,
        vertical: str,
        query: str | None,
        filters: dict[str, Any] | None,
        sort: str | None,
    ) -> int:
        cur = self._db.execute(
            """INSERT INTO watches (name, vertical, query, filters, sort, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                name,
                vertical,
                query,
                json.dumps(filters or {}),
                sort,
                int(time.time()),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def get_watch(self, name: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM watches WHERE name = ?", (name,)
        ).fetchone()

    def list_watches(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM watches ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            seen_count = self._db.execute(
                "SELECT COUNT(*) FROM seen WHERE watch_id = ?", (r["id"],)
            ).fetchone()[0]
            out.append(
                {
                    "name": r["name"],
                    "vertical": r["vertical"],
                    "query": r["query"],
                    "filters": json.loads(r["filters"] or "{}"),
                    "sort": r["sort"],
                    "seen_count": seen_count,
                    "last_checked_at": r["last_checked_at"],
                }
            )
        return out

    def delete_watch(self, name: str) -> bool:
        cur = self._db.execute("DELETE FROM watches WHERE name = ?", (name,))
        self._db.commit()
        return cur.rowcount > 0

    # -- seen tracking ---------------------------------------------------------

    def seen_finnkoder(self, watch_id: int) -> set[str]:
        rows = self._db.execute(
            "SELECT finnkode FROM seen WHERE watch_id = ?", (watch_id,)
        ).fetchall()
        return {r["finnkode"] for r in rows}

    def mark_seen(self, watch_id: int, finnkoder: list[str]) -> None:
        now = int(time.time())
        self._db.executemany(
            "INSERT OR IGNORE INTO seen (watch_id, finnkode, first_seen_at) VALUES (?,?,?)",
            [(watch_id, fk, now) for fk in finnkoder],
        )
        self._db.execute(
            "UPDATE watches SET last_checked_at = ? WHERE id = ?", (now, watch_id)
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
