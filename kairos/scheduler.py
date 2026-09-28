"""Durable background task scheduler.

Stores scheduled tasks in SQLite and runs them on an interval via a background
thread. Supported kinds:
  * "ask"   -> run the prompt through the LLM, store the result
  * "skill" -> run a named skill (payload = skill name)
Results are kept in the task row and can be surfaced by the GUI/Telegram.
"""

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".kairos" / "scheduler.db"


class SchedulerStore:
    def __init__(self, db_path=None):
        self.path = Path(db_path) if db_path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id TEXT PRIMARY KEY, name TEXT, kind TEXT, payload TEXT, "
                "interval_seconds INTEGER, next_run REAL, enabled INTEGER, "
                "last_run TEXT, last_result TEXT)"
            )
            self.conn.commit()

    def add(self, name, kind, payload, interval_seconds):
        tid = uuid.uuid4().hex
        with self._lock:
            self.conn.execute(
                "INSERT INTO tasks (id, name, kind, payload, interval_seconds, "
                "next_run, enabled, last_run, last_result) VALUES (?,?,?,?,?,?,1,NULL,NULL)",
                (tid, name, kind, payload, int(max(10, interval_seconds)), time.time()))
            self.conn.commit()
        return tid

    def list(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, name, kind, payload, interval_seconds, next_run, "
                        "enabled, last_run, last_result FROM tasks ORDER BY name")
            return cur.fetchall()

    def due(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, name, kind, payload, interval_seconds FROM tasks "
                        "WHERE enabled=1 AND next_run <= ?", (now,))
            return cur.fetchall()

    def mark_run(self, tid, result=""):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT interval_seconds FROM tasks WHERE id=?", (tid,))
            row = cur.fetchone()
            interval = row[0] if row else 3600
            self.conn.execute(
                "UPDATE tasks SET last_run=?, last_result=?, next_run=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), str(result)[:2000],
                 time.time() + interval, tid))
            self.conn.commit()

    def delete(self, name):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM tasks WHERE name=?", (name,))
            self.conn.commit()
            return cur.rowcount

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


class SchedulerLoop:
    def __init__(self, engine, store, poll_seconds=5):
        self.engine = engine
        self.store = store
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="kairos-sched")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                for tid, name, kind, payload, _interval in self.store.due():
                    self._execute(tid, name, kind, payload)
            except Exception:
                logger.exception("Scheduler tick failed")
            self._stop.wait(self.poll_seconds)

    def _execute(self, tid, name, kind, payload):
        try:
            if kind == "ask":
                result = self.engine.ask_llm(payload, use_character=False)
            elif kind == "skill":
                result = self.engine.run_skill(payload)
            else:
                result = f"(unknown task kind '{kind}')"
        except Exception as e:
            result = f"(error: {e})"
        self.store.mark_run(tid, result)
        logger.info("Scheduled task '%s' ran.", name)
        try:
            if self.engine.telegram and self.engine.telegram.running and self.engine._loop:
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    self.engine.telegram.notify_task(name, result), self.engine._loop)
        except Exception:
            pass