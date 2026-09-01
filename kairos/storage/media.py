import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kairos" / "media.db"


class MediaStore:
    def __init__(self, storage_root: str):
        self.storage_root = Path(storage_root)
        self.media_dir = self.storage_root / "Kairos" / "Media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY,
                    path TEXT,
                    title TEXT,
                    type TEXT,
                    created_at TEXT
                );
            """)
            self.conn.commit()

    def add_media(self, media_id: str, file_path: str, title: str, media_type: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO media (id, path, title, type, created_at) VALUES (?,?,?,?,?)",
                (media_id, str(file_path), title, media_type, now)
            )
            self.conn.commit()

    def get_all_media(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, title, path, type, created_at FROM media")
            return cur.fetchall()

    def get_old_media(self, before_iso: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, title, path, created_at FROM media WHERE created_at < ?",
                (before_iso,)
            )
            return cur.fetchall()

    def delete_media(self, media_id: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT path FROM media WHERE id = ?", (media_id,))
            row = cur.fetchone()
            if row:
                file_path = Path(row[0])
                if file_path.exists():
                    file_path.unlink()
                cur.execute("DELETE FROM media WHERE id = ?", (media_id,))
                self.conn.commit()

    def close(self):
        self.conn.close()