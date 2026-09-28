"""Token/usage accounting and simple cost observability.

Stores per-call usage in a local SQLite DB and provides rollups. Actual token
counts are taken from provider responses when present; otherwise a rough
character-based estimate is used.
"""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".kairos" / "usage.db"


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4) if text else 0


class UsageStore:
    def __init__(self, db_path=None):
        self.path = Path(db_path) if db_path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS usage ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, provider TEXT, "
                "model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, source TEXT)"
            )
            self.conn.commit()

    def add(self, provider: str, model: str, prompt_tokens: int,
            completion_tokens: int, source: str = "chat"):
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO usage (ts, provider, model, prompt_tokens, "
                    "completion_tokens, source) VALUES (?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), provider or "", model or "",
                     int(prompt_tokens or 0), int(completion_tokens or 0), source or ""))
                self.conn.commit()
        except Exception:
            logger.exception("Failed to record usage")

    def summary(self, days: int = 30) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT provider, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens) "
                "FROM usage WHERE ts >= ? GROUP BY provider ORDER BY 3 DESC", (cutoff,))
            rows = cur.fetchall()
        total_calls = sum(r[1] or 0 for r in rows)
        total_pt = sum(r[2] or 0 for r in rows)
        total_ct = sum(r[3] or 0 for r in rows)
        return {
            "days": days,
            "total_calls": total_calls,
            "prompt_tokens": total_pt,
            "completion_tokens": total_ct,
            "total_tokens": total_pt + total_ct,
            "by_provider": [
                {"provider": r[0], "calls": r[1], "prompt_tokens": r[2] or 0,
                 "completion_tokens": r[3] or 0}
                for r in rows
            ],
        }

    def recent(self, limit: int = 10) -> list:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT ts, provider, model, prompt_tokens, completion_tokens, "
                        "source FROM usage ORDER BY id DESC LIMIT ?", (limit,))
            return cur.fetchall()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass