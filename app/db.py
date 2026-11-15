from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import DATABASE_PATH, DATA_DIR


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DATABASE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    note TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    last_fired_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER,
                    symbol TEXT NOT NULL,
                    tag TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(guild_id, user_id, symbol, tag)
                );

                CREATE TABLE IF NOT EXISTS ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry REAL,
                    stop REAL,
                    target REAL,
                    note TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    exit_price REAL,
                    pnl_pct REAL,
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                );

                CREATE TABLE IF NOT EXISTS last_tickers (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    set_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bug_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    user_id INTEGER NOT NULL,
                    command TEXT,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'open',
                    assignee_id INTEGER,
                    resolution TEXT,
                    context_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS filing_seen (
                    accession TEXT PRIMARY KEY,
                    symbol TEXT,
                    seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "tickets").mkdir(parents=True, exist_ok=True)

    # ---- settings ----
    def get_setting(self, guild_id: int, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE guild_id = ? AND key = ?",
                (guild_id, key),
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, guild_id: int, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(guild_id, key, value) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value
                """,
                (guild_id, key, value),
            )

    # ---- last ticker ----
    def set_last_ticker(self, guild_id: int, channel_id: int, symbol: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO last_tickers(guild_id, channel_id, symbol, set_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    set_at = excluded.set_at
                """,
                (guild_id, channel_id, symbol.upper(), utcnow()),
            )

    def get_last_ticker(self, guild_id: int, channel_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT symbol FROM last_tickers WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id),
            ).fetchone()
        return row["symbol"] if row else None

    # ---- alerts ----
    def add_alert(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        symbol: str,
        kind: str,
        params: dict[str, Any],
        note: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts(guild_id, channel_id, user_id, symbol, kind, params_json, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    user_id,
                    symbol.upper(),
                    kind,
                    json.dumps(params),
                    note,
                    utcnow(),
                ),
            )
            return int(cur.lastrowid)

    def list_alerts(
        self,
        *,
        guild_id: int | None = None,
        user_id: int | None = None,
        active_only: bool = True,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        args: list[Any] = []
        if guild_id is not None:
            clauses.append("guild_id = ?")
            args.append(guild_id)
        if user_id is not None:
            clauses.append("user_id = ?")
            args.append(user_id)
        if active_only:
            clauses.append("active = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            return list(conn.execute(f"SELECT * FROM alerts {where} ORDER BY id DESC", args))

    def get_alert(self, alert_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()

    def deactivate_alert(self, alert_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE alerts SET active = 0 WHERE id = ?", (alert_id,))

    def mark_alert_fired(self, alert_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE alerts SET last_fired_at = ? WHERE id = ?",
                (utcnow(), alert_id),
            )

    # ---- watchlist ----
    def watch_add(
        self,
        *,
        guild_id: int,
        symbol: str,
        user_id: int | None = None,
        tag: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO watchlist(guild_id, user_id, symbol, tag, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, symbol.upper(), tag, utcnow()),
            )

    def watch_remove(
        self,
        *,
        guild_id: int,
        symbol: str | None = None,
        user_id: int | None = None,
        tag: str | None = None,
        clear_all: bool = False,
    ) -> int:
        clauses = ["guild_id = ?"]
        args: list[Any] = [guild_id]
        if user_id is not None:
            clauses.append("user_id IS ?")
            args.append(user_id)
        if symbol and not clear_all:
            clauses.append("symbol = ?")
            args.append(symbol.upper())
        if tag and not clear_all:
            clauses.append("tag = ?")
            args.append(tag)
        with self.connect() as conn:
            cur = conn.execute(f"DELETE FROM watchlist WHERE {' AND '.join(clauses)}", args)
            return cur.rowcount

    def watch_list(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        tag: str | None = None,
        server: bool = False,
    ) -> list[sqlite3.Row]:
        clauses = ["guild_id = ?"]
        args: list[Any] = [guild_id]
        if server:
            clauses.append("user_id IS NULL")
        elif user_id is not None:
            clauses.append("user_id = ?")
            args.append(user_id)
        if tag:
            clauses.append("tag = ?")
            args.append(tag)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM watchlist WHERE {' AND '.join(clauses)} ORDER BY symbol",
                    args,
                )
            )

    # ---- ideas ----
    def idea_create(self, **fields: Any) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ideas(guild_id, channel_id, message_id, user_id, symbol, side, entry, stop, target, note, created_at)
                VALUES (:guild_id, :channel_id, :message_id, :user_id, :symbol, :side, :entry, :stop, :target, :note, :created_at)
                """,
                {**fields, "created_at": utcnow(), "symbol": str(fields["symbol"]).upper()},
            )
            return int(cur.lastrowid)

    def idea_get(self, idea_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()

    def idea_list(self, guild_id: int, status: str | None = "open") -> list[sqlite3.Row]:
        with self.connect() as conn:
            if status:
                return list(
                    conn.execute(
                        "SELECT * FROM ideas WHERE guild_id = ? AND status = ? ORDER BY id DESC",
                        (guild_id, status),
                    )
                )
            return list(
                conn.execute(
                    "SELECT * FROM ideas WHERE guild_id = ? ORDER BY id DESC LIMIT 50",
                    (guild_id,),
                )
            )

    def idea_close(self, idea_id: int, exit_price: float | None, pnl_pct: float | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ideas
                SET status = 'closed', exit_price = ?, pnl_pct = ?, closed_at = ?
                WHERE id = ?
                """,
                (exit_price, pnl_pct, utcnow(), idea_id),
            )

    def idea_set_message(self, idea_id: int, message_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE ideas SET message_id = ? WHERE id = ?", (message_id, idea_id))

    # ---- paper ----
    def paper_open(self, guild_id: int, user_id: int, symbol: str, side: str, qty: float, entry: float) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO paper_positions(guild_id, user_id, symbol, side, qty, entry, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, symbol.upper(), side, qty, entry, utcnow()),
            )
            return int(cur.lastrowid)

    def paper_list(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM paper_positions WHERE guild_id = ? AND user_id = ? ORDER BY id",
                    (guild_id, user_id),
                )
            )

    def paper_close(self, position_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_positions WHERE id = ? AND user_id = ?",
                (position_id, user_id),
            ).fetchone()
            if row:
                conn.execute("DELETE FROM paper_positions WHERE id = ?", (position_id,))
            return row

    # ---- bugs ----
    def bug_create(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        description: str,
        command: str | None = None,
        severity: str = "normal",
        context: dict[str, Any] | None = None,
        message_id: int | None = None,
    ) -> int:
        now = utcnow()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO bug_tickets(
                    guild_id, channel_id, message_id, user_id, command, description,
                    severity, status, context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    message_id,
                    user_id,
                    command,
                    description,
                    severity,
                    json.dumps(context or {}),
                    now,
                    now,
                ),
            )
            ticket_id = int(cur.lastrowid)
        self._write_ticket_file(ticket_id)
        return ticket_id

    def bug_get(self, ticket_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM bug_tickets WHERE id = ?", (ticket_id,)).fetchone()

    def bug_list(
        self,
        *,
        guild_id: int | None = None,
        status: str | None = "open",
        limit: int = 25,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        args: list[Any] = []
        if guild_id is not None:
            clauses.append("guild_id = ?")
            args.append(guild_id)
        if status and status != "all":
            clauses.append("status = ?")
            args.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM bug_tickets {where} ORDER BY id DESC LIMIT ?",
                    args,
                )
            )

    def bug_update(
        self,
        ticket_id: int,
        *,
        status: str | None = None,
        assignee_id: int | None = None,
        resolution: str | None = None,
        message_id: int | None = None,
    ) -> sqlite3.Row | None:
        row = self.bug_get(ticket_id)
        if not row:
            return None
        fields: list[str] = ["updated_at = ?"]
        args: list[Any] = [utcnow()]
        if status is not None:
            fields.append("status = ?")
            args.append(status)
            if status in {"fixed", "closed", "wontfix"}:
                fields.append("closed_at = ?")
                args.append(utcnow())
        if assignee_id is not None:
            fields.append("assignee_id = ?")
            args.append(assignee_id)
        if resolution is not None:
            fields.append("resolution = ?")
            args.append(resolution)
        if message_id is not None:
            fields.append("message_id = ?")
            args.append(message_id)
        args.append(ticket_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE bug_tickets SET {', '.join(fields)} WHERE id = ?", args)
        self._write_ticket_file(ticket_id)
        return self.bug_get(ticket_id)

    def _write_ticket_file(self, ticket_id: int) -> None:
        row = self.bug_get(ticket_id)
        if not row:
            return
        payload = {k: row[k] for k in row.keys()}
        path = DATA_DIR / "tickets" / f"{ticket_id:05d}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ---- filings / schedule ----
    def filing_seen(self, accession: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM filing_seen WHERE accession = ?",
                (accession,),
            ).fetchone()
        return row is not None

    def mark_filing(self, accession: str, symbol: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO filing_seen(accession, symbol, seen_at) VALUES (?, ?, ?)",
                (accession, symbol, utcnow()),
            )

    def schedule_get(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM schedule_state WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else None

    def schedule_set(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO schedule_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


db = Database()
