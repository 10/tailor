"""SQLite-backed rolling traffic history."""

import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote_to_bytes, urlencode, urlsplit

MAX_ROWS = 1000
BODY_PREVIEW_LIMIT = 4000


def body_preview(text: str) -> str:
    if len(text) > BODY_PREVIEW_LIMIT:
        return text[:BODY_PREVIEW_LIMIT] + f"\n... [{len(text)} characters total]"
    return text


def _open_history(db_path: str | Path, access: str) -> tuple[sqlite3.Connection, Path | None]:
    value = str(db_path)
    if value not in ("", ":memory:") and not value.startswith("file:"):
        value = Path(value).absolute().as_uri()
    location = urlsplit(value)
    if location.netloc.lower() not in ("", "localhost"):
        raise sqlite3.OperationalError("History must use a local SQLite file")
    # SQLite URI options use percent escapes and preserve literal plus signs.
    options = parse_qsl(location.query.replace("+", "%2B"), keep_blank_values=True)
    modes = {v for k, v in options if k == "mode"}
    if len(modes) > 1 or not modes <= {"ro", "rw", "rwc", "memory"}:
        raise sqlite3.OperationalError("Invalid SQLite history mode")
    mode = next(iter(modes), "rwc")
    name = os.fsdecode(unquote_to_bytes(location.path))
    if name in ("", ":memory:") or mode == "memory" or ("vfs", "memdb") in options:
        db = sqlite3.connect(value, uri=True, check_same_thread=False)
        if access != "rwc" and not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='traffic'"
        ).fetchone():
            db.close()
            raise FileNotFoundError(value)
        return db, None

    path = Path(name).resolve()
    if mode == access == "rwc":
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    elif access != "rwc" and not path.exists():
        raise FileNotFoundError(path)
    options = [(k, v) for k, v in options if k != "mode"]
    options.append(("mode", "ro" if "ro" in (access, mode) else "rw"))
    uri = f"{path.as_uri()}?{urlencode(options, quote_via=quote)}"
    return sqlite3.connect(uri, uri=True, check_same_thread=False), path


def history_summary(db_path: str | Path) -> tuple[int, int, float | None, float | None]:
    db, path = _open_history(db_path, "ro")
    with closing(db):
        size = path.stat().st_size if path else 0
        count, oldest, newest = db.execute("SELECT count(*), min(ts), max(ts) FROM traffic").fetchone()
        return size, count, oldest, newest


def clear_history(db_path: str | Path) -> int:
    try:
        db, _ = _open_history(db_path, "rw")
    except FileNotFoundError:
        return 0
    with closing(db), db:
        db.execute("BEGIN IMMEDIATE")
        # A different application can also have a table named traffic.
        db.execute(
            "SELECT id, ts, method, host, path, status, matched, req_headers, req_body, "
            "resp_headers, resp_body, error FROM traffic LIMIT 0"
        )
        return db.execute("DELETE FROM traffic").rowcount


class TrafficStore:
    def __init__(self, db_path: str | Path):
        self._db, _ = _open_history(db_path, "rwc")
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

    def summaries(self, limit: int, only_matched: bool, rule: str) -> list[dict[str, Any]]:
        entries = []
        with self._lock:
            rows = self._db.execute(
                """SELECT id, ts, method, host, path, status, matched, error != '' AS has_error
                   FROM traffic ORDER BY id DESC"""
            )
            for row in rows:
                if len(entries) >= limit:
                    break
                matched = json.loads(row["matched"] or "[]")
                if (only_matched and not matched) or (rule and rule not in matched):
                    continue
                entries.append({**row, "matched": matched})
        return entries

    def get(self, entry_id: int | str) -> dict[str, Any] | None:
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
