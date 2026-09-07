"""
Pluggable job persistence for the OGC API - Processes engine.

The engine never talks to a database directly: it goes through a
:class:`JobStore`. The default implementation, :class:`SQLiteJobStore`, is fully
self-contained (raw ``sqlite3`` + JSON files, WAL-enabled for multi-process
concurrency) and works **outside any Flask application context** - which is
required because async jobs run in a **separate OS process** (so they can be
killed on ``DELETE``). It is picklable so it can be handed to that process.

A host application that already owns a database can provide its own adapter by
subclassing :class:`JobStore` (see the SQLAlchemy example in the README).
"""
import os
import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime

# OGC statusInfo status values.
JOB_STATUSES = ("accepted", "running", "successful", "failed", "dismissed")
_TERMINAL_STATUSES = ("successful", "failed", "dismissed")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _ts(value):
    """Serialize a stored ISO timestamp to the OGC ``...Z`` form (or None)."""
    return (value + "Z") if value else None


class JobStore(ABC):
    """Abstract persistence interface for OGC jobs and their results."""

    @abstractmethod
    def create_job(self, job_id, process_id, *, type="process",
                   status="accepted", message="", progress=0):
        """Persist a freshly-accepted job."""

    @abstractmethod
    def get_job(self, job_id) -> dict | None:
        """Return the job as an OGC statusInfo dict (no links), or None."""

    @abstractmethod
    def list_jobs(self, *, type=None, process_id=None, status=None,
                  limit=10, offset=0) -> tuple[list[dict], int]:
        """Return ``(jobs, total_matched)`` ordered by creation (newest first)."""

    @abstractmethod
    def update_job(self, job_id, *, progress=None, status=None, message=None):
        """Update a job; auto-manages ``started``/``finished``/``updated``."""

    @abstractmethod
    def save_results(self, job_id, results: dict):
        """Persist a job's result document (results.yaml map)."""

    @abstractmethod
    def load_results(self, job_id) -> dict | None:
        """Load a job's result document, or None if absent."""

    def delete_job(self, job_id) -> bool:  # pragma: no cover - optional
        """Hard-delete a job (row + result file). Return True if it existed.

        Optional method (like :meth:`clear`); adapters that do not implement it
        simply raise ``NotImplementedError``.
        """
        raise NotImplementedError

    def clear(self):  # pragma: no cover - optional, used by tests
        """Remove all jobs and results (best effort)."""
        raise NotImplementedError


class SQLiteJobStore(JobStore):
    """Autonomous SQLite + JSON-file job store (no SQLAlchemy required)."""

    def __init__(self, db_path: str | None = None, results_dir: str | None = None):
        base = os.path.abspath(os.path.dirname(__file__))
        self.db_path = db_path or os.path.join(base, "job_store_data", "jobs.db")
        self.results_dir = results_dir or os.path.join(base, "job_store_data", "results")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def __getstate__(self):
        # Drop the un-picklable lock so the store can cross a process boundary
        # (handed to a multiprocessing worker); it is recreated on unpickle. The
        # child reconnects to the same on-disk SQLite file / results dir.
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock = threading.Lock()

    # --- infrastructure -------------------------------------------------
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL + busy_timeout make the store safe under concurrent writers (the
        # parent process and the forked async job processes all hit this file):
        # readers never block writers, and a busy writer waits instead of raising
        # "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    jobID     TEXT PRIMARY KEY,
                    processID TEXT NOT NULL,
                    type      TEXT NOT NULL DEFAULT 'process',
                    status    TEXT NOT NULL,
                    message   TEXT NOT NULL DEFAULT '',
                    progress  INTEGER NOT NULL DEFAULT 0,
                    created   TEXT NOT NULL,
                    started   TEXT,
                    finished  TEXT,
                    updated   TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "jobID": row["jobID"],
            "processID": row["processID"],
            "type": row["type"],
            "status": row["status"],
            "message": row["message"],
            "progress": row["progress"],
            "created": _ts(row["created"]),
            "started": _ts(row["started"]),
            "finished": _ts(row["finished"]),
            "updated": _ts(row["updated"]),
        }

    # --- JobStore API ---------------------------------------------------
    def create_job(self, job_id, process_id, *, type="process",
                   status="accepted", message="", progress=0):
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (jobID, processID, type, status, message, progress, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, process_id, type, status, message, progress, now, now),
            )
            conn.commit()

    def get_job(self, job_id) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE jobID = ?", (job_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_jobs(self, *, type=None, process_id=None, status=None,
                  limit=10, offset=0) -> tuple[list[dict], int]:
        clauses, params = [], []
        if type:
            clauses.append("type = ?"); params.append(type)
        if process_id:
            clauses.append("processID = ?"); params.append(process_id)
        if status:
            clauses.append("status = ?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs{where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM jobs{where} ORDER BY created DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [self._row_to_dict(r) for r in rows], total

    def update_job(self, job_id, *, progress=None, status=None, message=None):
        now = _now_iso()
        fields, values = ["updated = ?"], [now]
        if progress is not None:
            fields.append("progress = ?"); values.append(progress)
        if status is not None:
            fields.append("status = ?"); values.append(status)
            if status == "running":
                fields.append("started = ?"); values.append(now)
            if status in _TERMINAL_STATUSES:
                fields.append("finished = ?"); values.append(now)
        if message is not None:
            fields.append("message = ?"); values.append(message)
        values.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE jobID = ?", values)
            conn.commit()

    # --- results (file-backed) -----------------------------------------
    def _results_path(self, job_id) -> str:
        # Defence in depth (SECURITY_AUDIT.md #10): the job_id becomes a filename,
        # so refuse anything with path separators / traversal before building it.
        name = str(job_id)
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise ValueError(f"invalid job id: {job_id!r}")
        return os.path.join(self.results_dir, f"{name}.json")

    def save_results(self, job_id, results: dict):
        with open(self._results_path(job_id), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    def load_results(self, job_id) -> dict | None:
        path = self._results_path(job_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def delete_job(self, job_id) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE jobID = ?", (job_id,))
            conn.commit()
            existed = cur.rowcount > 0
        path = self._results_path(job_id)
        if os.path.exists(path):
            os.remove(path)
        return existed

    def clear(self):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM jobs")
            conn.commit()
        if os.path.isdir(self.results_dir):
            for name in os.listdir(self.results_dir):
                if name.endswith(".json"):
                    os.remove(os.path.join(self.results_dir, name))
