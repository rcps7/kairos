"""Long-term semantic memory backed by the embedded LadybugDB graph.

Stores entities, relationships and episodic memories as a property graph and
retrieves a relationship-aware context for a query. Embeddings (384-d, from the
same all-MiniLM-L6-v2 model Kairos already uses) power a native HNSW vector
index; graph traversal then expands the semantic seed by 1-2 hops.

All database access runs through a single ``lb.AsyncConnection`` owned by a
dedicated event-loop thread, so callers may use either the ``async`` methods or
the synchronous wrappers.

Note: the Ladybug full-text (FTS) extension aborts the process on the current
Windows/Python 3.14 build, so keyword search is done in Python rather than via
an FTS index.
"""

import asyncio
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .ladybug_bootstrap import ensure_runtime

logger = logging.getLogger(__name__)

EMBED_DIM = 384

SCHEMA_DDL = [
    "CREATE NODE TABLE IF NOT EXISTS Entity("
    "id STRING PRIMARY KEY, name STRING, kind STRING, summary STRING, "
    "aliases STRING[], embedding FLOAT[384], mention_count INT64 DEFAULT 0, "
    "confidence DOUBLE DEFAULT 0.5, first_seen TIMESTAMP, last_seen TIMESTAMP, source STRING);",
    "CREATE NODE TABLE IF NOT EXISTS Memory("
    "id STRING PRIMARY KEY, text STRING, kind STRING, character STRING, "
    "source STRING, created_at TIMESTAMP, embedding FLOAT[384]);",
    "CREATE REL TABLE IF NOT EXISTS Relates(FROM Entity TO Entity, predicate STRING, "
    "weight DOUBLE DEFAULT 1.0, evidence STRING, created_at TIMESTAMP);",
    "CREATE REL TABLE IF NOT EXISTS Mentions(FROM Memory TO Entity, count INT64 DEFAULT 1, "
    "created_at TIMESTAMP);",
]

VECTOR_INDEXES = [
    ("Entity", "entity_vec", "embedding"),
    ("Memory", "memory_vec", "embedding"),
]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "x"


def entity_id(kind: str, name: str) -> str:
    return f"{_slug(kind)}:{_slug(name)}"


def _now():
    return datetime.now(timezone.utc)


class GraphMemory:
    """Async-first LadybugDB graph with sync wrappers."""

    def __init__(self, db_path, embed_fn=None, max_concurrent: int = 4,
                 dedup_distance: float = 0.15):
        info = ensure_runtime()
        self.info = info
        self.error = info.get("error")
        self.available = bool(info.get("available"))
        self.vector_available = False
        self.dedup_distance = dedup_distance
        self._embed_fn = embed_fn
        self._db_path = str(db_path)
        self._max_concurrent = max_concurrent
        self._lb = None
        self._db = None
        self._conn = None
        self._loop = None
        self._thread = None
        self._io_lock = threading.Lock()

        if self.available:
            try:
                import ladybug
                self._lb = ladybug
                self._start_loop()
                self._run(self._ainit())
            except Exception as e:
                logger.exception("Failed to initialise graph memory.")
                self.available = False
                self.error = str(e)

    # ------------------------------------------------------------------
    # Event-loop plumbing
    # ------------------------------------------------------------------
    def _start_loop(self):
        self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, daemon=True, name="kairos-ladybug")
        self._thread.start()

    def _run(self, coro, timeout: float = 90.0):
        if self._loop is None:
            return asyncio.run(coro)
        with self._io_lock:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return fut.result(timeout)

    async def _ainit(self):
        self._db = self._lb.Database(self._db_path)
        self._conn = self._lb.AsyncConnection(
            self._db, max_concurrent_queries=self._max_concurrent
        )
        # Vector extension (best-effort; INSTALL is a no-op once present).
        try:
            try:
                await self._conn.execute("LOAD vector;")
            except Exception:
                await self._conn.execute("INSTALL vector;")
                await self._conn.execute("LOAD vector;")
            self.vector_available = True
        except Exception as e:
            logger.warning("Ladybug vector extension unavailable: %s", e)
            self.vector_available = False

        for stmt in SCHEMA_DDL:
            await self._conn.execute(stmt)

        if self.vector_available:
            existing = set()
            try:
                for row in (await self._conn.execute("CALL SHOW_INDEXES() RETURN *;")).get_all():
                    existing.add(row[1])
            except Exception:
                pass
            for table, idx, prop in VECTOR_INDEXES:
                if idx not in existing:
                    try:
                        await self._conn.execute(
                            f"CALL CREATE_VECTOR_INDEX('{table}','{idx}','{prop}', metric := 'cosine');"
                        )
                    except Exception as e:
                        logger.warning("Could not create %s: %s", idx, e)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def _embed_one(self, text: str):
        return self._embed([text or ""])[0]

    def _embed(self, texts):
        if self._embed_fn is None:
            return [[0.0] * EMBED_DIM for _ in texts]
        try:
            out = self._embed_fn(list(texts))
        except TypeError:
            out = self._embed_fn(input=list(texts))
        vecs = []
        for v in out:
            v = list(v)
            if len(v) != EMBED_DIM:
                v = (v + [0.0] * EMBED_DIM)[:EMBED_DIM]
            vecs.append(v)
        return vecs

    # ------------------------------------------------------------------
    # Ingestion (write)
    # ------------------------------------------------------------------
    def upsert(self, entities, relations=None, memory=None):
        return self._run(self.aupsert(entities, relations, memory))

    async def aupsert(self, entities, relations=None, memory=None):
        if not self.available:
            return {"ok": False, "error": self.error}
        entities = entities or []
        relations = relations or []
        now = _now()

        # Embed entity descriptors + memory once.
        ent_embeddings = self._embed(
            [f"{e.get('name','')}. {e.get('summary','')}" for e in entities]
        )
        resolved = []
        for ent, emb in zip(entities, ent_embeddings):
            name = (ent.get("name") or "").strip()
            kind = (ent.get("kind") or "Concept").strip()
            if not name:
                continue
            eid = entity_id(kind, name)
            # Dedup against existing nodes via the vector index.
            if self.vector_available:
                try:
                    rows = (await self._conn.execute(
                        "CALL QUERY_VECTOR_INDEX('Entity','entity_vec',$q,$k) "
                        "RETURN node.id, node.kind, node.name, distance;",
                        {"q": emb, "k": 3},
                    )).get_all()
                    for rid, rkind, rname, dist in rows:
                        if rkind == kind and dist is not None and dist <= self.dedup_distance:
                            eid = rid
                            aliases = set(ent.get("aliases") or [])
                            aliases.add(name)
                            ent["aliases"] = sorted(aliases)
                            break
                except Exception:
                    pass
            await self._conn.execute(
                "MERGE (e:Entity {id:$id}) "
                "ON CREATE SET e.name=$name, e.kind=$kind, e.summary=$summary, e.aliases=$aliases, "
                "e.embedding=$emb, e.mention_count=1, e.confidence=$conf, "
                "e.first_seen=$now, e.last_seen=$now, e.source=$source "
                "ON MATCH SET e.last_seen=$now, e.mention_count=e.mention_count+1, "
                "e.embedding=$emb, e.aliases=$aliases, e.summary=$summary;",
                {
                    "id": eid, "name": name, "kind": kind,
                    "summary": ent.get("summary") or "",
                    "aliases": [str(a) for a in (ent.get("aliases") or [])],
                    "emb": emb, "conf": float(ent.get("confidence", 0.5)),
                    "now": now, "source": (memory or {}).get("source", "chat"),
                },
            )
            resolved.append({"name": name, "kind": kind, "id": eid})

        by_name = {}
        for r in resolved:
            by_name[r["name"].lower()] = r
            by_name[_slug(r["name"])] = r

        for rel in relations:
            s = by_name.get((rel.get("subject") or "").lower()) or by_name.get(_slug(rel.get("subject") or ""))
            o = by_name.get((rel.get("object") or "").lower()) or by_name.get(_slug(rel.get("object") or ""))
            pred = (rel.get("predicate") or "related_to").strip()
            if not (s and o) or s["id"] == o["id"]:
                continue
            try:
                await self._conn.execute(
                    "MATCH (s:Entity {id:$sid}),(o:Entity {id:$oid}) "
                    "MERGE (s)-[r:Relates {predicate:$pred}]->(o) "
                    "ON CREATE SET r.weight=1.0, r.evidence=$ev, r.created_at=$now "
                    "ON MATCH SET r.weight=r.weight+1.0, r.evidence=$ev;",
                    {"sid": s["id"], "oid": o["id"], "pred": pred,
                     "ev": rel.get("evidence") or "", "now": now},
                )
            except Exception:
                logger.exception("Failed to link relation %s-%s->%s", s["id"], pred, o["id"])

        if memory and memory.get("text"):
            mid = memory.get("id") or uuid.uuid4().hex
            await self._conn.execute(
                "MERGE (m:Memory {id:$id}) ON CREATE SET m.text=$text, m.kind=$kind, "
                "m.character=$char, m.source=$source, m.created_at=$now, m.embedding=$emb;",
                {
                    "id": mid, "text": memory["text"], "kind": memory.get("kind", "chat"),
                    "char": memory.get("character", ""), "source": memory.get("source", "chat"),
                    "now": memory.get("created_at") or now,
                    "emb": self._embed_one(memory["text"]),
                },
            )
            for r in resolved:
                try:
                    await self._conn.execute(
                        "MATCH (m:Memory {id:$mid}),(e:Entity {id:$eid}) "
                        "MERGE (m)-[mn:Mentions]->(e) ON CREATE SET mn.count=1, mn.created_at=$now "
                        "ON MATCH SET mn.count=mn.count+1;",
                        {"mid": mid, "eid": r["id"], "now": now},
                    )
                except Exception:
                    pass

        return {"ok": True, "entities": resolved, "memory_id": (memory or {}).get("id")}

    # ------------------------------------------------------------------
    # Retrieval (read)
    # ------------------------------------------------------------------
    def retrieve(self, query: str, k_nodes: int = 12, k_memories: int = 6, hops: int = 2):
        return self._run(self.aretrieve(query, k_nodes, k_memories, hops))

    async def aretrieve(self, query: str, k_nodes: int = 12, k_memories: int = 6, hops: int = 2):
        if not self.available or not query:
            return {"context": "", "entities": [], "memories": []}
        qv = self._embed_one(query)
        entities = []
        memories = []

        if self.vector_available:
            try:
                srows = (await self._conn.execute(
                    "CALL QUERY_VECTOR_INDEX('Entity','entity_vec',$q,$k) "
                    "RETURN node.id, node.name, node.kind, node.summary, distance;",
                    {"q": qv, "k": k_nodes},
                )).get_all()
                for sid, sname, skind, ssum, dist in srows:
                    entities.append({"id": sid, "name": sname, "kind": skind,
                                     "summary": ssum, "distance": dist, "relations": []})
                # 1-hop neighbourhood with predicates (reliable; avoids projecting
                # a RECURSIVE_REL from a variable-length pattern).
                for ent in entities[:k_nodes]:
                    try:
                        nrows = (await self._conn.execute(
                            "MATCH (s:Entity {id:$sid})-[r:Relates]-(n:Entity) "
                            "RETURN n.name, n.kind, r.predicate;",
                            {"sid": ent["id"]},
                        )).get_all()
                    except Exception:
                        nrows = []
                    seen_rel = set()
                    for nname, nkind, pred in nrows:
                        key = (nname, pred)
                        if key in seen_rel:
                            continue
                        seen_rel.add(key)
                        ent["relations"].append(
                            {"predicate": pred, "target": f"{nname} ({nkind})"}
                        )
            except Exception:
                logger.exception("Entity retrieval failed.")

            try:
                mrows = (await self._conn.execute(
                    "CALL QUERY_VECTOR_INDEX('Memory','memory_vec',$q,$k) "
                    "RETURN node.text, node.kind, distance;",
                    {"q": qv, "k": k_memories},
                )).get_all()
                for text, kind, dist in mrows:
                    memories.append({"text": text, "kind": kind, "distance": dist})
            except Exception:
                logger.exception("Memory retrieval failed.")
        else:
            # No vector index: keyword fallback.
            entities = await self._keyword_entities(query, k_nodes)
            memories = await self._keyword_memories(query, k_memories)

        context = self._format_context(entities, memories)
        return {"context": context, "entities": entities, "memories": memories}

    async def _keyword_entities(self, query, limit):
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2][:6]
        if not terms:
            return []
        try:
            rows = (await self._conn.execute(
                "MATCH (e:Entity) RETURN e.id, e.name, e.kind, e.summary LIMIT 500;"
            )).get_all()
        except Exception:
            return []
        out = []
        for eid, name, kind, summary in rows:
            blob = f"{name} {summary}".lower()
            if any(t in blob for t in terms):
                out.append({"id": eid, "name": name, "kind": kind, "summary": summary,
                            "distance": None, "relations": []})
            if len(out) >= limit:
                break
        return out

    async def _keyword_memories(self, query, limit):
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2][:6]
        if not terms:
            return []
        try:
            rows = (await self._conn.execute(
                "MATCH (m:Memory) RETURN m.text, m.kind LIMIT 500;"
            )).get_all()
        except Exception:
            return []
        out = []
        for text, kind in rows:
            if any(t in (text or "").lower() for t in terms):
                out.append({"text": text, "kind": kind, "distance": None})
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _format_context(entities, memories) -> str:
        if not entities and not memories:
            return ""
        lines = ["RELATED KNOWLEDGE GRAPH (use only if relevant to the question):"]
        for e in entities[:15]:
            head = f"- {e['name']} [{e['kind']}]"
            if e.get("summary"):
                head += f": {e['summary']}"
            lines.append(head)
            for rel in e.get("relations", [])[:6]:
                lines.append(f"    {e['name']} {rel['predicate']} {rel['target']}")
        if memories:
            lines.append("Recent related notes:")
            for m in memories[:6]:
                lines.append(f"    * {m['text'][:300]}")
        return "\n".join(lines)

    def search(self, query: str, limit: int = 20):
        return self._run(self.asearch(query, limit))

    async def asearch(self, query: str, limit: int = 20):
        """Return structured search results for the GUI/Telegram."""
        if not self.available:
            return {"entities": [], "relations": [], "memories": []}
        res = await self.aretrieve(query, k_nodes=limit, k_memories=limit)
        return {"entities": res["entities"], "memories": res["memories"],
                "relations": [r for e in res["entities"] for r in e.get("relations", [])]}

    # ------------------------------------------------------------------
    # CRUD / management
    # ------------------------------------------------------------------
    def list_entities(self, limit: int = 200):
        return self._run(self.alist_entities(limit))

    async def alist_entities(self, limit: int = 200):
        if not self.available:
            return []
        rows = (await self._conn.execute(
            "MATCH (e:Entity) RETURN e.id, e.name, e.kind, e.summary, e.mention_count, "
            "e.last_seen ORDER BY e.mention_count DESC LIMIT $lim;", {"lim": limit}
        )).get_all()
        return [{"id": r[0], "name": r[1], "kind": r[2], "summary": r[3],
                 "mentions": r[4], "last_seen": str(r[5])} for r in rows]

    def update_entity(self, eid, name=None, kind=None, summary=None, aliases=None):
        return self._run(self.aupdate_entity(eid, name, kind, summary, aliases))

    async def aupdate_entity(self, eid, name=None, kind=None, summary=None, aliases=None):
        sets, params = [], {"id": eid}
        if name is not None:
            sets.append("e.name=$name"); params["name"] = name
        if kind is not None:
            sets.append("e.kind=$kind"); params["kind"] = kind
        if summary is not None:
            sets.append("e.summary=$summary"); params["summary"] = summary
        if aliases is not None:
            sets.append("e.aliases=$aliases"); params["aliases"] = [str(a) for a in aliases]
        if not sets:
            return False
        await self._conn.execute(f"MATCH (e:Entity {{id:$id}}) SET {', '.join(sets)};", params)
        return True

    def delete_entity(self, eid):
        return self._run(self.adelete_entity(eid))

    async def adelete_entity(self, eid):
        await self._conn.execute("MATCH (e:Entity {id:$id}) DETACH DELETE e;", {"id": eid})
        return True

    def delete_relation(self, sid, predicate, oid):
        return self._run(self.adelete_relation(sid, predicate, oid))

    async def adelete_relation(self, sid, predicate, oid):
        await self._conn.execute(
            "MATCH (s:Entity {id:$sid})-[r:Relates {predicate:$p}]->(o:Entity {id:$oid}) DELETE r;",
            {"sid": sid, "p": predicate, "oid": oid},
        )
        return True

    def delete_memory(self, mid):
        return self._run(self.adelete_memory(mid))

    async def adelete_memory(self, mid):
        await self._conn.execute("MATCH (m:Memory {id:$id}) DETACH DELETE m;", {"id": mid})
        return True

    def clear(self):
        return self._run(self.aclear())

    async def aclear(self):
        await self._conn.execute("MATCH (m:Memory) DETACH DELETE m;")
        await self._conn.execute("MATCH (e:Entity) DETACH DELETE e;")
        return True

    def stats(self):
        return self._run(self.astats())

    async def astats(self):
        if not self.available:
            return {"available": False, "error": self.error}
        async def count(q):
            try:
                return (await self._conn.execute(q)).get_all()[0][0]
            except Exception:
                return 0
        return {
            "available": True,
            "entities": await count("MATCH (e:Entity) RETURN count(*);"),
            "relations": await count("MATCH (:Entity)-[r:Relates]->(:Entity) RETURN count(*);"),
            "memories": await count("MATCH (m:Memory) RETURN count(*);"),
            "vector": self.vector_available,
            "db_path": self._db_path,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self):
        if self._loop is None:
            return
        try:
            self._run(self._aclose(), timeout=30)
        except Exception:
            logger.exception("Error closing graph memory.")
        finally:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
            self._loop = None

    async def _aclose(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        try:
            if self._db is not None:
                self._db.close()
        except Exception:
            pass