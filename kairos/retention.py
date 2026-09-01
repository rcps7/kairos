import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class RetentionManager:
    """Weekly sweep: collect items older than retention_days and request deletion approval."""

    def __init__(self, engine):
        self.engine = engine
        self.pending = []  # list of {"kind": "document"|"media", "id":..., "label":...}

    def retention_days(self) -> int:
        return int(self.engine.config.get("retention_days", 30))

    def collect_expired(self) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days())).isoformat()
        items = []
        for doc in self.engine.knowledge.get_old_documents(cutoff):
            items.append({"kind": "document", "id": doc[0], "label": doc[1] or doc[0]})
        for media in self.engine.media.get_old_media(cutoff):
            items.append({"kind": "media", "id": media[0], "label": media[1] or media[0]})
        self.pending = items
        return items

    def approve(self, selected_ids: list) -> int:
        """Delete the given items. Returns count deleted."""
        deleted = 0
        selected = set(selected_ids)
        for item in self.pending:
            if item["id"] in selected:
                if item["kind"] == "document":
                    self.engine.knowledge.delete_document(item["id"])
                elif item["kind"] == "media":
                    self.engine.media.delete_media(item["id"])
                deleted += 1
        self.pending = [i for i in self.pending if i["id"] not in selected]
        logger.info("Retention deleted %d items.", deleted)
        return deleted
