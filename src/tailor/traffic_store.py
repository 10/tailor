"""SQLite-backed rolling traffic history."""

import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

MAX_ROWS = 1000
BODY_PREVIEW_LIMIT = 4000


def body_preview(text: str) -> str:
    if len(text) > BODY_PREVIEW_LIMIT:
        return text[:BODY_PREVIEW_LIMIT] + f"\n... [{len(text)} characters total]"
    return text


def _open_existing(path: Path, mode: str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    return sqlite3.connect(
        f"{path.absolute().as_uri()}?mode={mode}", uri=True, check_same_thread=check_same_thread
    )


def history_summary(path: Path) -> tuple[int, float | None, float | None]:
    with closing(_open_existing(path, "ro")) as db:
        return db.execute("SELECT count(*), min(ts), max(ts) FROM traffic").fetchone()


def clear_history(db_path: str | Path) -> int:
    path = Path(db_path)
    if str(db_path) in ("", ":memory:") or not path.exists():
        return 0
    with closing(_open_existing(path, "rw")) as db, db:
        db.execute("BEGIN IMMEDIATE")
        # A different application can also have a table named traffic.
        db.execute(
            "SELECT id, ts, method, host, path, status, matched, req_headers, req_body, "
            "resp_headers, resp_body, error FROM traffic LIMIT 0"
        )
        return db.execute("DELETE FROM traffic").rowcount


class TrafficStore:
    def __init__(self, db_path: str | Path):
        if str(db_path) in ("", ":memory:"):
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        else:
            path = Path(db_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            # SQLite inherits the permissions of an existing database.
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
            self._db = _open_existing(path, "rw", check_same_thread=False)
        self._lock = threading.Lock()
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS traffic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, method TEXT, host TEXT, path TEXT, status INTEGER,
                matched TEXT, req_headers TEXT, req_body TEXT,
                resp_headers TEXT, resp_body TEXT, error TEXT
            )"""
        )
        self._db.commit()

    def add(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO traffic
                   (ts, method, host, path, status, matched, req_headers,
                    req_body, resp_headers, resp_body, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["ts"],
                    record["method"],
                    record["host"],
                    record["path"],
                    record["status"],
                    json.dumps(record["matched"]),
                    json.dumps(record["req_headers"]),
                    record["req_body"],
                    json.dumps(record["resp_headers"]),
                    record["resp_body"],
                    record["error"],
                ),
            )
            # rolling: drop anything beyond the newest MAX_ROWS
            self._db.execute(
                """DELETE FROM traffic WHERE id NOT IN
                   (SELECT id FROM traffic ORDER BY id DESC LIMIT ?)""",
                (MAX_ROWS,),
            )
            self._db.commit()

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM traffic ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM traffic WHERE id = ?", (entry_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def clear(self) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM traffic").rowcount
            self._db.commit()
        return n


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("matched", "req_headers", "resp_headers"):
        d[k] = json.loads(d[k]) if d[k] else ([] if k == "matched" else {})
    return d
