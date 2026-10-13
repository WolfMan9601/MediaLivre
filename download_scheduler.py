"""Persistência local de downloads agendados para o MediaLivre.

Os horários são guardados em UTC. Esta camada não executa downloads: a interface
Qt consulta a fila, reclama atomicamente um trabalho vencido e encaminha-o ao
DownloadWorker já existente.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

APP_DIRECTORY_NAME = "MediaLivre"


def app_data_directory() -> Path:
    """Return a stable per-user data location, never relative to the .exe/.bat."""
    override = os.environ.get("MEDIALIVRE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / APP_DIRECTORY_NAME


def default_database_path() -> Path:
    return app_data_directory() / "scheduled-downloads.sqlite3"


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("O horário agendado tem de incluir fuso horário.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ScheduledDownload:
    id: str
    url: str
    run_at_utc: str
    options: dict[str, Any]
    state: str
    created_at_utc: str
    updated_at_utc: str
    last_error: str | None = None

    @property
    def run_at_local(self) -> datetime:
        return datetime.fromisoformat(self.run_at_utc).astimezone()


class ScheduleStore:
    """SQLite-backed job queue with an atomic due-job claim operation."""

    STATES = {"pending", "running", "completed", "failed", "cancelled"}

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path) if database_path else default_database_path()
        self.database_path = self.database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.database_path.parent.chmod(0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        if os.name != "nt":
            try:
                self.database_path.chmod(0o600)
            except FileNotFoundError:
                pass
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    run_at_utc TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('pending', 'running', 'completed', 'failed', 'cancelled')
                    ),
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    last_error TEXT
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduled_downloads_due
                ON scheduled_downloads(state, run_at_utc, created_at_utc)
            """)

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> ScheduledDownload | None:
        if row is None:
            return None
        return ScheduledDownload(
            id=row["id"],
            url=row["url"],
            run_at_utc=row["run_at_utc"],
            options=json.loads(row["options_json"]),
            state=row["state"],
            created_at_utc=row["created_at_utc"],
            updated_at_utc=row["updated_at_utc"],
            last_error=row["last_error"],
        )

    def add(self, url: str, run_at: datetime, options: dict[str, Any]) -> ScheduledDownload:
        """Add one pending job. ``run_at`` must be timezone-aware."""
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Introduza uma URL HTTP(S) completa.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Não guarde credenciais dentro da URL.")
        run_at_utc = _utc_iso(run_at)
        job_id = str(uuid.uuid4())
        now = _now_utc_iso()
        options_json = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("""
                INSERT INTO scheduled_downloads
                    (id, url, run_at_utc, options_json, state, created_at_utc, updated_at_utc)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """, (job_id, url, run_at_utc, options_json, now, now))
            row = connection.execute(
                "SELECT * FROM scheduled_downloads WHERE id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row)  # type: ignore[return-value]

    def list_recent(self, limit: int = 100) -> list[ScheduledDownload]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_downloads "
                "ORDER BY CASE state WHEN 'pending' THEN 0 WHEN 'running' THEN 1 ELSE 2 END, "
                "run_at_utc, created_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]  # type: ignore[misc]

    def claim_next_due(self, now: datetime | None = None) -> ScheduledDownload | None:
        """Atomically change and return the oldest due pending job as running."""
        cutoff = _utc_iso(now or datetime.now(timezone.utc))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM scheduled_downloads "
                "WHERE state = 'pending' AND run_at_utc <= ? "
                "ORDER BY run_at_utc, created_at_utc LIMIT 1",
                (cutoff,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            changed = connection.execute(
                "UPDATE scheduled_downloads SET state = 'running', updated_at_utc = ? "
                "WHERE id = ? AND state = 'pending'",
                (_now_utc_iso(), row["id"]),
            ).rowcount
            connection.commit()
            if changed != 1:
                return None
            return self.get(row["id"])
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, job_id: str) -> ScheduledDownload | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_downloads WHERE id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row)

    def finish(self, job_id: str, state: str, error: str | None = None) -> bool:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("Estado final inválido.")
        error = (error or "").strip()[:4000] or None
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE scheduled_downloads SET state = ?, last_error = ?, updated_at_utc = ? "
                "WHERE id = ? AND state = 'running'",
                (state, error, _now_utc_iso(), job_id),
            ).rowcount
        return changed == 1

    def cancel(self, job_id: str) -> bool:
        """Cancel only a job that has not started; active downloads use worker.cancel()."""
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE scheduled_downloads SET state = 'cancelled', updated_at_utc = ? "
                "WHERE id = ? AND state = 'pending'",
                (_now_utc_iso(), job_id),
            ).rowcount
        return changed == 1

    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left running by a previous, now-closed app process as failed."""
        note = "A aplicação terminou durante este download; reveja o ficheiro antes de o agendar novamente."
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE scheduled_downloads SET state = 'failed', last_error = ?, updated_at_utc = ? "
                "WHERE state = 'running'",
                (note, _now_utc_iso()),
            ).rowcount
        return changed

    def requeue(self, job_id: str, run_at: datetime | None = None) -> bool:
        """Manually retry a failed/cancelled job, optionally at a new aware time."""
        run_at_utc = _utc_iso(run_at or datetime.now(timezone.utc))
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE scheduled_downloads SET state = 'pending', run_at_utc = ?, "
                "updated_at_utc = ?, last_error = NULL "
                "WHERE id = ? AND state IN ('failed', 'cancelled')",
                (run_at_utc, _now_utc_iso(), job_id),
            ).rowcount
        return changed == 1
