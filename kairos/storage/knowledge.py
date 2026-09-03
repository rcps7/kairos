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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT,
                    created_at TEXT
                );
            """)
            self.conn.commit()

    # ---- Memories (user-retained data for later recall) ----
    def add_memory(self, content: str) -> str:
        import uuid
        mem_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO memories (id, content, created_at) VALUES (?,?,?)",
                (mem_id, content, now)
            )
            self.conn.commit()
        if self.collection is not None:
            with self._vec_lock:
                try:
                    self.collection.add(
                        ids=[mem_id],
                        documents=[content],
                        metadatas=[{"kind": "memory", "content": content[:200]}]
                    )
                except Exception:
                    pass
        return mem_id

    def list_memories(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, content, created_at FROM memories ORDER BY created_at DESC")
            return cur.fetchall()

    def delete_memory(self, mem_id: str):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
            self.conn.commit()
        if self.collection is not None:
            with self._vec_lock:
                try:
                    self.collection.delete(ids=[mem_id])
                except Exception:
                    pass

    def search_memories(self, query: str, limit: int = 10):
        if self.collection is None:
            with self._lock:
                cur = self.conn.cursor()
                cur.execute(
                    "SELECT id, content, created_at FROM memories WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{query}%", limit)
                )
                return cur.fetchall()
        with self._vec_lock:
            try:
                res = self.collection.query(
                    query_texts=[query],
                    n_results=limit,
                    where={"kind": "memory"},
                )
                ids = res.get("ids", [[]])[0]
                if not ids:
                    return []
                out = []
                with self._lock:
                    for mid in ids:
                        cur = self.conn.cursor()
                        cur.execute("SELECT id, content, created_at FROM memories WHERE id = ?", (mid,))
                        row = cur.fetchone()
                        if row:
                            out.append(row)
                return out
            except Exception:
                return []

    def recall(self, query: str, limit: int = 8):
        """Return related memories + knowledge documents for a query."""
        related = []
        for mid, content, created in self.search_memories(query, limit):
            related.append({"kind": "memory", "id": mid, "text": content})
        docs = self.semantic_search(query, limit)
        if docs:
            ids = docs.get("ids", [[]])[0]
            metas = docs.get("metadatas", [[]])[0]
            with self._lock:
                for i, did in enumerate(ids):
                    cur = self.conn.cursor()
                    cur.execute("SELECT summary FROM documents WHERE id = ?", (did,))
                    row = cur.fetchone()
                    meta = metas[i] if i < len(metas) else {}
                    text = row[0] if row and row[0] else meta.get("summary", "")
                    if text:
                        related.append({"kind": "document", "id": did, "text": text})
        return related


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