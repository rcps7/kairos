"""Durable multi-step plans / todo tracking.

A plan is a goal plus ordered steps; step status and results persist in SQLite
so work can be resumed across restarts.
"""

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".kairos" / "planner.db"


class PlannerStore:
    def __init__(self, db_path=None):
        self.path = Path(db_path) if db_path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, goal TEXT, "
                "status TEXT, created_at TEXT)")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS steps (id TEXT PRIMARY KEY, plan_id TEXT, "
                "idx INTEGER, title TEXT, status TEXT, result TEXT)")
            self.conn.commit()

    def create(self, goal: str, steps=None):
        pid = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute("INSERT INTO plans (id, goal, status, created_at) "
                              "VALUES (?,?,?,?)", (pid, goal, "open", now))
            self.conn.commit()
        for title in (steps or []):
            self.add_step(pid, title)
        return pid

    def add_step(self, plan_id: str, title: str):
        sid = uuid.uuid4().hex
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COALESCE(MAX(idx), -1) + 1 FROM steps WHERE plan_id=?",
                        (plan_id,))
            idx = cur.fetchone()[0]
            self.conn.execute("INSERT INTO steps (id, plan_id, idx, title, status, result) "
                              "VALUES (?,?,?,?,?,?)", (sid, plan_id, idx, title, "todo", ""))
            self.conn.commit()
        return sid

    def list_plans(self, limit: int = 50):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, goal, status, created_at FROM plans "
                        "ORDER BY created_at DESC LIMIT ?", (limit,))
            return cur.fetchall()

    def get_plan(self, plan_id: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, goal, status, created_at FROM plans WHERE id=?",
                        (plan_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("SELECT id, idx, title, status, result FROM steps "
                        "WHERE plan_id=? ORDER BY idx", (plan_id,))
            steps = cur.fetchall()
        return {"id": row[0], "goal": row[1], "status": row[2], "created_at": row[3],
                "steps": [{"id": s[0], "idx": s[1], "title": s[2], "status": s[3],
                           "result": s[4]} for s in steps]}

    def update_step(self, step_id: str, status: str, result: str = ""):
        with self._lock:
            self.conn.execute("UPDATE steps SET status=?, result=? WHERE id=?",
                              (status, str(result)[:4000], step_id))
            self.conn.commit()

    def set_status(self, plan_id: str, status: str):
        with self._lock:
            self.conn.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))
            self.conn.commit()

    def delete(self, plan_id: str):
        with self._lock:
            self.conn.execute("DELETE FROM steps WHERE plan_id=?", (plan_id,))
            self.conn.execute("DELETE FROM plans WHERE id=?", (plan_id,))
            self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass