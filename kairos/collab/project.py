"""Collaborative project state backed by a pycrdt CRDT document.

Peers exchange full CRDT updates (documents are small); concurrent edits merge
without conflict. Local edits trigger ``on_change`` (to broadcast), remote
updates trigger ``on_refresh`` (to update the UI).
"""

import logging

logger = logging.getLogger(__name__)


class SharedProject:
    def __init__(self, project_id: str = "default", max_bytes: int = 4 * 1024 * 1024):
        from pycrdt import Array, Doc, Map, Text

        self.project_id = project_id
        self.max_bytes = max_bytes
        self.doc = Doc()
        self.notes = self.doc.get("notes", type=Text)
        self.tasks = self.doc.get("tasks", type=Array)
        self.chat = self.doc.get("chat", type=Array)
        self.files = self.doc.get("files", type=Map)
        self.llm = self.doc.get("llm", type=Map)

        self.on_change = None    # fn(update_bytes) -> broadcast
        self.on_refresh = None   # fn() -> refresh UI
        self._applying = False
        self._observe()

    def _observe(self):
        for t in (self.notes, self.tasks, self.chat, self.files, self.llm):
            try:
                t.observe(self._changed)
            except Exception:
                logger.debug("observe() unavailable for %s", type(t))

    def _changed(self, event=None):
        if self._applying or self.on_change is None:
            return
        # Do NOT read the document here: pycrdt runs observers inside the
        # transaction, and get_update() would panic. Just signal the caller,
        # which fetches the update later on its own thread.
        try:
            self.on_change()
        except Exception:
            logger.exception("on_change failed")

    def update(self) -> bytes:
        return self.doc.get_update()

    def apply(self, data: bytes):
        if len(data) > self.max_bytes:
            logger.warning("Ignoring oversized CRDT update (%d bytes).", len(data))
            return
        self._applying = True
        try:
            self.doc.apply_update(bytes(data))
        except Exception:
            logger.exception("Failed to apply CRDT update")
        finally:
            self._applying = False
        if self.on_refresh:
            try:
                self.on_refresh()
            except Exception:
                pass

    # ---- convenience edits ----
    def get_notes(self) -> str:
        try:
            return str(self.notes)
        except Exception:
            return ""

    def set_notes(self, text: str):
        text = text or ""
        try:
            self.notes.clear()
            if text:
                self.notes.insert(0, text)
        except Exception:
            logger.exception("set_notes failed")

    def add_task(self, title: str, owner: str = ""):
        try:
            self.tasks.append({"title": title, "owner": owner, "done": False})
        except Exception:
            logger.exception("add_task failed")

    def get_tasks(self) -> list:
        try:
            return [t for t in self.tasks.to_py()]
        except Exception:
            return []

    def append_chat(self, sender: str, text: str):
        try:
            self.chat.append({"from": sender, "text": text})
        except Exception:
            logger.exception("append_chat failed")

    def set_llm(self, key: str, value):
        try:
            self.llm[key] = value
        except Exception:
            logger.exception("set_llm failed")