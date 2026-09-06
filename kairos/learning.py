import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".kairos" / "learning.db"


class ErrorMemory:
    """Persistent store for agent errors and lessons learned."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT,
                    error TEXT,
                    created_at TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    content TEXT,
                    created_at TEXT
                );
            """)
            self.conn.commit()

    def record(self, context: str, error: str):
        try:
            with self._lock:
                cur = self.conn.cursor()
                cur.execute(
                    "INSERT INTO errors (context, error, created_at) VALUES (?,?,?)",
                    (context, str(error)[:2000], datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()
        except Exception:
            logger.exception("Failed to record error.")

    def recent_errors(self, limit: int = 10) -> list:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT context, error, created_at FROM errors ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return cur.fetchall()

    def add_lesson(self, content: str) -> str:
        lesson_id = uuid.uuid4().hex
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO lessons (id, content, created_at) VALUES (?,?,?)",
                (lesson_id, content, datetime.now(timezone.utc).isoformat())
            )
            self.conn.commit()
        return lesson_id

    def recent_lessons(self, limit: int = 10) -> list:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT content FROM lessons ORDER BY id DESC LIMIT ?", (limit,))
            return [r[0] for r in cur.fetchall()]

    def close(self):
        self.conn.close()


def reflect(engine, limit: int = 8) -> str:
    """Analyze recent errors and store a lesson. Returns the analysis."""
    errors = engine.learning.recent_errors(limit)
    if not errors:
        return "No errors recorded yet. Nothing to reflect on."

    lines = []
    for ctx, err, ts in errors:
        lines.append(f"[{ts}] {ctx}: {err}")

    # Include recent prediction reports so the agent can reflect on its
    # forecasting quality too.
    prediction_context = ""
    try:
        predictions = engine.predictive_store.list_recent(limit=5)
        if predictions:
            pred_lines = []
            for pid, question, source, status, report, created in predictions:
                pred_lines.append(
                    f"- Q: {question}\n  Engine: {source} | Status: {status}\n  {report[:500]}"
                )
            prediction_context = (
                "\n\nRECENT PREDICTIONS (for forecasting self-assessment):\n"
                + "\n".join(pred_lines)
            )
    except Exception:
        prediction_context = ""

    prompt = (
        "You are the self-improvement module of an AI agent. "
        "Below are recent errors, limitations, and prediction outputs encountered by the agent. "
        "Analyze them and produce:\n"
        "1) ROOT CAUSES - a short list\n"
        "2) CORRECTIVE ACTIONS - clear, actionable steps the agent should take\n"
        "3) LESSON LEARNED - one paragraph to remember for future use\n"
        "4) FORECASTING NOTES - how to improve future predictions (if predictions are present)\n\n"
        "ERRORS:\n" + "\n".join(lines) + prediction_context
    )
    analysis = engine.ask_llm(prompt)
    engine.learning.add_lesson(analysis)
    return analysis