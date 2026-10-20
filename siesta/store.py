"""SQLite storage for Siesta.

Everything Siesta knows lives in one local file. There is no server, no
account, and nothing to sync — the whole point is that your fridge, your
receipts and your chat screenshots never leave the machine.

The database doubles as the **cost ledger**: every model call is recorded
with its latency and token counts so the write-up can quote real numbers
instead of guesses.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .util import cosine, ensure_dir, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    raw_name     TEXT,
    category     TEXT,
    quantity     REAL,
    unit         TEXT,
    condition    TEXT,
    expiry_days  INTEGER,
    expiry_date  TEXT,
    source       TEXT,
    confidence   REAL,
    embedding    TEXT,
    first_seen   TEXT,
    last_seen    TEXT
);

CREATE TABLE IF NOT EXISTS seen_files (
    path         TEXT PRIMARY KEY,
    fingerprint  TEXT,
    sha256       TEXT,
    size         INTEGER,
    mtime        REAL,
    processed_at TEXT,
    chore        TEXT,
    digest_id    INTEGER,
    skipped      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT,
    phase         TEXT,
    chore         TEXT,
    model         TEXT,
    backend       TEXT,
    latency_ms    INTEGER,
    prompt_tokens INTEGER,
    eval_tokens   INTEGER,
    note          TEXT,
    payload       TEXT
);

CREATE TABLE IF NOT EXISTS digests (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT,
    path      TEXT,
    headline  TEXT,
    markdown  TEXT,
    files     INTEGER,
    items     INTEGER,
    tokens    INTEGER,
    embedding TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    merchant TEXT,
    total    REAL,
    currency TEXT,
    lines    TEXT,
    source   TEXT
);

CREATE TABLE IF NOT EXISTS chores_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    """Thin, explicit wrapper around SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        ensure_dir(self.db_path.parent)
        # The web UI runs its handlers in a threadpool, so the connection
        # cannot be bound to the thread that opened it. SQLite is compiled in
        # serialised mode, and the lock below keeps writes single-threaded
        # anyway.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            with self._lock:
                self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Cost ledger
    # ------------------------------------------------------------------ #
    def record_event(
        self,
        *,
        phase: str,
        model: str = "",
        backend: str = "",
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        eval_tokens: int = 0,
        chore: str = "",
        note: str = "",
        payload: Any = None,
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO events (ts, phase, chore, model, backend, latency_ms,"
                " prompt_tokens, eval_tokens, note, payload)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    now_iso(),
                    phase,
                    chore,
                    model,
                    backend,
                    int(latency_ms),
                    int(prompt_tokens),
                    int(eval_tokens),
                    note,
                    json.dumps(payload, default=str) if payload is not None else None,
                ),
            )
            self.conn.commit()

    def token_totals(self, since: str | None = None) -> dict[str, int]:
        if since:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(eval_tokens),0) e,"
                " COALESCE(SUM(latency_ms),0) l, COUNT(*) n FROM events WHERE ts >= ?",
                (since,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(eval_tokens),0) e,"
                " COALESCE(SUM(latency_ms),0) l, COUNT(*) n FROM events"
            ).fetchone()
        return {
            "prompt_tokens": int(row["p"]),
            "eval_tokens": int(row["e"]),
            "total_tokens": int(row["p"]) + int(row["e"]),
            "latency_ms": int(row["l"]),
            "calls": int(row["n"]),
        }

    def events_by_phase(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT phase, model, backend, COUNT(*) calls,"
            " COALESCE(SUM(prompt_tokens),0) prompt_tokens,"
            " COALESCE(SUM(eval_tokens),0) eval_tokens,"
            " COALESCE(SUM(latency_ms),0) latency_ms"
            " FROM events GROUP BY phase, model, backend ORDER BY phase"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Files we have already seen
    # ------------------------------------------------------------------ #
    def seen(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM seen_files WHERE path = ?", (path,)).fetchone()

    def mark_seen(
        self,
        path: str,
        *,
        fingerprint: str,
        sha256: str,
        size: int,
        mtime: float,
        chore: str = "",
        digest_id: int | None = None,
        skipped: bool = False,
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO seen_files (path, fingerprint, sha256, size, mtime, processed_at,"
                " chore, digest_id, skipped) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint,"
                " sha256=excluded.sha256, size=excluded.size, mtime=excluded.mtime,"
                " processed_at=excluded.processed_at, chore=excluded.chore,"
                " digest_id=excluded.digest_id, skipped=excluded.skipped",
                (
                    path,
                    fingerprint,
                    sha256,
                    int(size),
                    float(mtime),
                    now_iso(),
                    chore,
                    digest_id,
                    1 if skipped else 0,
                ),
            )
            self.conn.commit()

    def seen_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) n FROM seen_files").fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------ #
    # Pantry
    # ------------------------------------------------------------------ #
    def upsert_item(
        self,
        *,
        name: str,
        raw_name: str = "",
        category: str = "",
        quantity: float = 0.0,
        unit: str = "",
        condition: str = "",
        expiry_days: int | None = None,
        source: str = "",
        confidence: float = 1.0,
        embedding: list[float] | None = None,
    ) -> int:
        stamp = now_iso()
        existing = self.conn.execute(
            "SELECT id FROM items WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        expiry_date = None
        if expiry_days is not None:
            import datetime as _dt

            expiry_date = (
                _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=int(expiry_days))
            ).date().isoformat()
        if existing:
            with self._lock:
                self.conn.execute(
                    "UPDATE items SET quantity=?, unit=?, condition=?, expiry_days=?, expiry_date=?,"
                    " source=?, confidence=?, embedding=?, last_seen=? WHERE id=?",
                    (
                        quantity,
                        unit,
                        condition,
                        expiry_days,
                        expiry_date,
                        source,
                        confidence,
                        json.dumps(embedding) if embedding else None,
                        stamp,
                        existing["id"],
                    ),
                )
                self.conn.commit()
            return int(existing["id"])
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO items (name, raw_name, category, quantity, unit, condition, expiry_days,"
                " expiry_date, source, confidence, embedding, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    name,
                    raw_name or name,
                    category,
                    quantity,
                    unit,
                    condition,
                    expiry_days,
                    expiry_date,
                    source,
                    confidence,
                    json.dumps(embedding) if embedding else None,
                    stamp,
                    stamp,
                ),
            )
            self.conn.commit()
        return int(cur.lastrowid)

    def list_items(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM items ORDER BY COALESCE(expiry_days, 9999) ASC, name ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def items_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, name, category, embedding FROM items WHERE embedding IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def match_item(self, name: str, embedding: list[float] | None, threshold: float = 0.86) -> dict[str, Any] | None:
        """Find an existing item with the same name, or a close enough match."""
        row = self.conn.execute(
            "SELECT * FROM items WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        if row:
            return dict(row)
        if not embedding:
            return None
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in self.items_with_embeddings():
            try:
                vector = json.loads(candidate.get("embedding") or "[]")
            except json.JSONDecodeError:
                continue
            score = cosine(embedding, vector)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= threshold:
            return {"id": best[1]["id"], "name": best[1]["name"], "score": round(best[0], 3)}
        return None

    # ------------------------------------------------------------------ #
    # Digests
    # ------------------------------------------------------------------ #
    def add_digest(
        self,
        *,
        path: str,
        headline: str,
        markdown: str,
        files: int,
        items: int,
        tokens: int,
        embedding: list[float] | None = None,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO digests (ts, path, headline, markdown, files, items, tokens, embedding)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    now_iso(),
                    path,
                    headline,
                    markdown,
                    int(files),
                    int(items),
                    int(tokens),
                    json.dumps(embedding) if embedding else None,
                ),
            )
            self.conn.commit()
        return int(cur.lastrowid)

    def last_digest(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM digests ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def list_digests(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, path, headline, files, items, tokens FROM digests"
            " ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Expenses
    # ------------------------------------------------------------------ #
    def add_expense(
        self, *, merchant: str, total: float, currency: str, lines: Iterable[dict[str, Any]], source: str
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO expenses (ts, merchant, total, currency, lines, source) VALUES (?,?,?,?,?,?)",
                (now_iso(), merchant, float(total), currency, json.dumps(list(lines), default=str), source),
            )
            self.conn.commit()
        return int(cur.lastrowid)

    def list_expenses(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["lines"] = json.loads(item.get("lines") or "[]")
            except json.JSONDecodeError:
                item["lines"] = []
            out.append(item)
        return out

    def expense_total(self) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(total),0) t FROM expenses").fetchone()
        return float(row["t"])

    # ------------------------------------------------------------------ #
    # Free-form key/value (e.g. last shopping list, nap state)
    # ------------------------------------------------------------------ #
    def set_state(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO chores_state (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, default=str)),
            )
            self.conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM chores_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default
