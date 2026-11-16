"""Persistencia SQLite: execucoes, itens, logs, agendamentos e alertas."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    trigger     TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    summary     TEXT
);
CREATE TABLE IF NOT EXISTS run_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    operation   TEXT NOT NULL,
    target      TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    seconds     INTEGER,
    artifact    TEXT,
    started_at  TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    run_id  INTEGER,
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    at_time      TEXT NOT NULL,
    weekdays     TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_run_at  TEXT,
    next_run_at  TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    severity TEXT NOT NULL,
    title    TEXT NOT NULL,
    message  TEXT,
    run_id   INTEGER,
    ack      INTEGER NOT NULL DEFAULT 0
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else config.db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------ runs
    def start_run(self, kind: str, trigger: str) -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO runs(kind, trigger, started_at, status) VALUES(?,?,?,?)",
                (kind, trigger, now(), "running"),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: str) -> None:
        with self.connect() as con:
            con.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE id=?",
                        (now(), status, summary, run_id))

    def abort_running(self, reason: str) -> list[int]:
        """Fecha execucoes que ficaram 'running' (queda/reinicio no meio)."""
        with self.connect() as con:
            rows = con.execute("SELECT id FROM runs WHERE status='running'").fetchall()
            ids = [int(r["id"]) for r in rows]
            if ids:
                con.executemany(
                    "UPDATE runs SET status='aborted', finished_at=?, summary=? WHERE id=?",
                    [(now(), reason, run_id) for run_id in ids],
                )
            return ids

    def add_item(self, run_id: int, operation: str, target: str, status: str,
                 detail: str = "", seconds: int | None = None,
                 artifact: str = "", started_at: str = "", finished_at: str = "") -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO run_items(run_id, operation, target, status, detail, "
                "seconds, artifact, started_at, finished_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, operation, target, status, detail, seconds, artifact,
                 started_at or now(), finished_at or now()),
            )
            return int(cur.lastrowid)

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def run_items(self, run_id: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM run_items WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

    def last_success(self, operation: str, target: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM run_items WHERE operation=? AND target=? AND status='succeeded' "
                "ORDER BY id DESC LIMIT 1", (operation, target)).fetchone()

    # ------------------------------------------------------------------ logs
    def log(self, level: str, message: str, run_id: int | None = None) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO logs(ts, run_id, level, message) VALUES(?,?,?,?)",
                        (now(), run_id, level.upper(), message))

    def recent_logs(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ---------------------------------------------------------------- alerts
    def alert(self, severity: str, title: str, message: str = "",
              run_id: int | None = None) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO alerts(ts, severity, title, message, run_id) VALUES(?,?,?,?,?)",
                (now(), severity, title, message, run_id))

    def recent_alerts(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ------------------------------------------------------------ manutencao
    def prune_logs(self, days: int) -> int:
        if days <= 0:
            return 0
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.connect() as con:
            cur = con.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
            return cur.rowcount

    def prune_runs(self, days: int) -> int:
        """Nunca remove artefatos de backup; apenas registros antigos do historico."""
        if days <= 0:
            return 0
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.connect() as con:
            cur = con.execute(
                "DELETE FROM runs WHERE finished_at IS NOT NULL AND finished_at < ?", (cutoff,))
            return cur.rowcount

    # ------------------------------------------------------------- schedules
    def schedules(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT * FROM schedules ORDER BY id").fetchall()

    def upsert_schedule(self, name: str, kind: str, at_time: str, weekdays: str,
                        enabled: bool = True) -> int:
        with self.connect() as con:
            row = con.execute("SELECT id FROM schedules WHERE name=?", (name,)).fetchone()
            if row:
                con.execute(
                    "UPDATE schedules SET kind=?, at_time=?, weekdays=?, enabled=? WHERE id=?",
                    (kind, at_time, weekdays, 1 if enabled else 0, row["id"]))
                return int(row["id"])
            cur = con.execute(
                "INSERT INTO schedules(name, kind, at_time, weekdays, enabled) VALUES(?,?,?,?,?)",
                (name, kind, at_time, weekdays, 1 if enabled else 0))
            return int(cur.lastrowid)

    def set_schedule_run(self, schedule_id: int, last_run_at: str, next_run_at: str) -> None:
        with self.connect() as con:
            con.execute("UPDATE schedules SET last_run_at=?, next_run_at=? WHERE id=?",
                        (last_run_at, next_run_at, schedule_id))
