"""Lightweight tracing: per-LLM-call spans for observability."""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".kairos" / "trace.db"


class SpanStore:
    def __init__(self, db_path=None):
        self.path = Path(db_path) if db_path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS spans (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT, source TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER, "
                "completion_tokens INTEGER, ms INTEGER, ok INTEGER)")
            self.conn.commit()

    def add(self, source, provider, model, prompt_tokens, completion_tokens, ms=0, ok=1):
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO spans (ts, source, provider, model, prompt_tokens, "
                    "completion_tokens, ms, ok) VALUES (?,?,?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), source or "", provider or "",
                     model or "", int(prompt_tokens or 0), int(completion_tokens or 0),
                     int(ms or 0), 1 if ok else 0))
                self.conn.commit()
        except Exception:
            logger.exception("Failed to record span")

    def recent(self, limit: int = 20):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT ts, source, provider, model, prompt_tokens, "
                        "completion_tokens, ms, ok FROM spans ORDER BY id DESC LIMIT ?",
                        (limit,))
            return cur.fetchall()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass