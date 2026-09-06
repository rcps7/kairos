"""Persistent storage for prediction reports."""

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kairos" / "predictions.db"


class PredictiveStore:
    """SQLite store for prediction records (thread-safe)."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY,
                    question TEXT,
                    source TEXT,
                    status TEXT,
                    report TEXT,
                    created_at TEXT
                );
            """)
            self.conn.commit()

    def add(self, question: str, source: str, status: str = "done", report: str = "") -> str:
        pid = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO predictions (id, question, source, status, report, created_at) VALUES (?,?,?,?,?,?)",
                (pid, question, source, status, report, now)
            )
            self.conn.commit()
        return pid

    def update(self, pid: str, status: str = None, report: str = None):
        with self._lock:
            cur = self.conn.cursor()
            if status is not None:
                cur.execute("UPDATE predictions SET status = ? WHERE id = ?", (status, pid))
            if report is not None:
                cur.execute("UPDATE predictions SET report = ? WHERE id = ?", (report, pid))
            self.conn.commit()

    def list_recent(self, limit: int = 10):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, question, source, status, report, created_at FROM predictions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return cur.fetchall()

    def get(self, pid: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, question, source, status, report, created_at FROM predictions WHERE id = ?", (pid,))
            return cur.fetchone()

    def close(self):
        self.conn.close()
