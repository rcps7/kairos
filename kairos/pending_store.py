"""Durable approval queue for proposed graph knowledge.

Proposals are extracted by the LLM but are NOT written to the graph until the
user explicitly approves them. They are persisted in user data
(``~/.kairos/graph_pending.db``) so they survive restarts and application
updates (the self-updater only replaces program files).
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kairos" / "graph_pending.db"


class PendingStore:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_graph (
                    id TEXT PRIMARY KEY,
                    created_at TEXT,
                    source TEXT,
                    kind TEXT,
                    payload TEXT,
                    status TEXT,
                    reviewed_at TEXT
                );
            """)
            self.conn.commit()

    def add(self, payload: dict, source: str = "chat", kind: str = "knowledge"):
        pid = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO pending_graph (id, created_at, source, kind, payload, status, reviewed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (pid, now, source, kind, json.dumps(payload, ensure_ascii=False), "pending", None),
            )
            self.conn.commit()
        return pid

    def _row(self, row):
        if not row:
            return None
        pid, created, source, kind, payload, status, reviewed = row
        try:
            data = json.loads(payload)
        except Exception:
            data = {}
        return {"id": pid, "created_at": created, "source": source, "kind": kind,
                "payload": data, "status": status, "reviewed_at": reviewed}

    def list(self, status: str = "pending", limit: int = 100):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, created_at, source, kind, payload, status, reviewed_at "
                "FROM pending_graph WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
            return [self._row(r) for r in cur.fetchall()]

    def get(self, pid: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, created_at, source, kind, payload, status, reviewed_at "
                "FROM pending_graph WHERE id = ?", (pid,),
            )
            return self._row(cur.fetchone())

    def update_payload(self, pid: str, payload: dict):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE pending_graph SET payload = ? WHERE id = ? AND status = 'pending'",
                (json.dumps(payload, ensure_ascii=False), pid),
            )
            self.conn.commit()
        return True

    def mark(self, pid: str, status: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE pending_graph SET status = ?, reviewed_at = ? WHERE id = ?",
                (status, now, pid),
            )
            self.conn.commit()
        return True

    def delete(self, pid: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM pending_graph WHERE id = ?", (pid,))
            self.conn.commit()
        return True

    def count_pending(self) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM pending_graph WHERE status = 'pending'")
            return int(cur.fetchone()[0])

    def close(self):
        self.conn.close()