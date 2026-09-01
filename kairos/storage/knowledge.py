import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kairos" / "knowledge.db"


class KnowledgeStore:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._lock = threading.Lock()
        self._vec_lock = threading.Lock()
        self._ensure_schema()
        self.collection = None
        self.client = None
        try:
            import chromadb
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self._embed_fn = DefaultEmbeddingFunction()
            self.client = chromadb.PersistentClient(
                path=str(Path.home() / ".kairos" / "chroma")
            )
            self.collection = self.client.get_or_create_collection(
                name="knowledge_vectors",
                embedding_function=self._embed_fn,
            )
        except Exception:
            self.collection = None
            self.client = None

    def _ensure_schema(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    url TEXT,
                    raw_html TEXT,
                    cleaned_text TEXT,
                    summary TEXT,
                    created_at TEXT
                );
            """)
            self.conn.commit()

    def add_document(self, doc_id: str, url: str, raw_html: str, cleaned: str, summary: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO documents (id, url, raw_html, cleaned_text, summary, created_at) VALUES (?,?,?,?,?,?)",
                (doc_id, url, raw_html, cleaned, summary, now)
            )
            self.conn.commit()
        if self.collection is not None:
            with self._vec_lock:
                try:
                    self.collection.add(
                        ids=[doc_id],
                        documents=[cleaned],
                        metadatas=[{"url": url, "summary": summary}]
                    )
                except Exception:
                    pass

    def search_text(self, query: str, limit: int = 10):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, url, summary FROM documents WHERE cleaned_text LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            return cur.fetchall()

    def get_old_documents(self, before_iso: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, url, created_at FROM documents WHERE created_at < ?",
                (before_iso,)
            )
            return cur.fetchall()

    def get_all_documents(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, url, summary, created_at FROM documents")
            return cur.fetchall()

    def delete_document(self, doc_id: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            self.conn.commit()
        if self.collection is not None:
            with self._vec_lock:
                try:
                    self.collection.delete(ids=[doc_id])
                except Exception:
                    pass

    def semantic_search(self, query: str, limit: int = 10):
        if self.collection is None:
            return []
        with self._vec_lock:
            try:
                return self.collection.query(query_texts=[query], n_results=limit)
            except Exception:
                return []

    def close(self):
        self.conn.close()