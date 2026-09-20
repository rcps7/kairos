"""Agent Characters for Kairos.

Each character is a self-contained persona profile stored as JSON in its own
folder::

    <storage_root>/Kairos/AGENT_CHARACTER/<character_id>/character.json

Built-in presets (see :mod:`kairos.characters_presets`) are seeded on first run
and are read-only; users can add, edit and delete their own custom characters.
"""

import json
import logging
import re
import threading
from pathlib import Path

from .characters_presets import (
    ALL_CAPABILITIES,
    CAPABILITY_LABELS,
    GENERAL_PROMPT,
    PRESETS,
)

logger = logging.getLogger(__name__)

DEFAULT_DIR_NAME = "AGENT_CHARACTER"
PROFILE_FILENAME = "character.json"
GENERAL_ID = "general"
_ID_RE = re.compile(r"^[a-z0-9_]+$")

CUSTOM_PROMPT_TEMPLATE = (
    "You are KAIROS operating as a specialized assistant: {name}.\n\n"
    "ROLE\n{description}\n\n"
    "OPERATING PRINCIPLES\n"
    "1. Stay strictly within the scope of this role. If a request falls outside "
    "it, politely decline and state your purpose.\n"
    "2. Be precise and evidence-based. When a claim is time-sensitive or "
    "uncertain, verify it with a tool instead of guessing, and never fabricate "
    "facts or tool results.\n"
    "3. Match the user's level of expertise and keep answers well-structured.\n"
    "4. Use the user's retained knowledge/memory when relevant, and use the "
    "multi-LLM council for complex tasks."
)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "character"


def _validate_id(cid: str) -> str:
    cid = (cid or "").strip().lower()
    if not _ID_RE.match(cid):
        raise ValueError(
            "Character id must contain only lowercase letters, digits and "
            "underscores."
        )
    return cid


class CharacterManager:
    """Loads, seeds and persists agent character profiles."""

    def __init__(self, storage_root: str, active_id: str = None,
                 dir_name: str = DEFAULT_DIR_NAME):
        self._lock = threading.RLock()
        self.dir_name = dir_name or DEFAULT_DIR_NAME
        self.active_id = active_id or GENERAL_ID
        self.characters_dir = Path(".")
        self.profiles = {}
        self.set_root(storage_root)

    # ------------------------------------------------------------------
    # Paths / persistence
    # ------------------------------------------------------------------
    def _resolve_dir(self, storage_root: str) -> Path:
        base = Path(storage_root) if storage_root else (Path.home() / "KairosData")
        return base / "Kairos" / self.dir_name

    def set_root(self, storage_root: str):
        """(Re)point at a storage root, seeding defaults and reloading."""
        with self._lock:
            self.characters_dir = self._resolve_dir(storage_root)
            self.characters_dir.mkdir(parents=True, exist_ok=True)
            self._seed_missing()
            self._load()

    def _profile_path(self, cid: str) -> Path:
        return self.characters_dir / cid / PROFILE_FILENAME

    def _write_profile(self, profile: dict, builtin: bool = None) -> dict:
        cid = _validate_id(profile.get("id"))
        data = {
            "id": cid,
            "name": profile.get("name") or cid,
            "icon": profile.get("icon") or "",
            "description": profile.get("description") or "",
            "system_prompt": profile.get("system_prompt") or GENERAL_PROMPT,
            "disclaimer": profile.get("disclaimer"),
            "capabilities": profile.get("capabilities"),
            "skills": profile.get("skills"),
            "builtin": bool(
                builtin if builtin is not None else profile.get("builtin", False)
            ),
            "version": 1,
        }
        folder = self.characters_dir / cid
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / PROFILE_FILENAME
        tmp = folder / (PROFILE_FILENAME + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
        return data

    def _seed_missing(self):
        for preset in PRESETS:
            cid = _validate_id(preset["id"])
            if not self._profile_path(cid).exists():
                try:
                    self._write_profile(preset, builtin=True)
                except Exception:
                    logger.exception("Failed to seed character '%s'.", cid)

    def _load(self):
        profiles = {}
        for folder in sorted(self.characters_dir.iterdir()):
            if not folder.is_dir():
                continue
            fp = folder / PROFILE_FILENAME
            if not fp.exists():
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Unreadable character profile: %s", fp)
                continue
            if not (data.get("id") and data.get("name") and data.get("system_prompt")):
                logger.warning("Incomplete character profile: %s", fp)
                continue
            data.setdefault("builtin", False)
            profiles[data["id"]] = data

        # Auto-heal missing/corrupt built-ins (force re-seed), then re-read them.
        missing = [p for p in PRESETS if p["id"] not in profiles]
        for preset in missing:
            cid = preset["id"]
            try:
                data = self._write_profile(preset, builtin=True)
                profiles[cid] = data
            except Exception:
                logger.exception("Failed to heal character '%s'.", cid)

        if GENERAL_ID not in profiles:
            fallback = next((p for p in PRESETS if p["id"] == GENERAL_ID), None)
            if fallback:
                profiles[GENERAL_ID] = self._write_profile(fallback, builtin=True)

        self.profiles = profiles
        if self.active_id not in profiles:
            self.active_id = GENERAL_ID

    def reload(self):
        with self._lock:
            self._seed_missing()
            self._load()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list(self) -> list:
        with self._lock:
            values = list(self.profiles.values())
        values.sort(key=lambda p: (not p.get("builtin", False), p.get("name", "").lower()))
        return values

    def get(self, cid: str):
        with self._lock:
            return self.profiles.get((cid or "").strip().lower())

    def active(self) -> dict:
        return self.get(self.active_id) or self.get(GENERAL_ID) or {}

    def capabilities(self, cid: str = None) -> list:
        prof = self.get(cid) if cid else self.active()
        caps = (prof or {}).get("capabilities")
        return list(ALL_CAPABILITIES) if caps is None else list(caps)

    def can(self, capability: str, cid: str = None) -> bool:
        prof = self.get(cid) if cid else self.active()
        caps = (prof or {}).get("capabilities")
        if caps is None:
            return True
        return capability in caps

    def allows_skill(self, name: str, cid: str = None) -> bool:
        prof = self.get(cid) if cid else self.active()
        allowed = (prof or {}).get("skills")
        if allowed is None:
            return True
        return name in allowed

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def set_active(self, cid: str) -> dict:
        prof = self.get(cid)
        if not prof:
            raise ValueError(f"Character '{cid}' not found.")
        with self._lock:
            self.active_id = prof["id"]
        return prof

    def _unique_id(self, base: str) -> str:
        cid = _slugify(base)
        with self._lock:
            existing = set(self.profiles)
        if cid not in existing:
            return cid
        i = 2
        while f"{cid}_{i}" in existing:
            i += 1
        return f"{cid}_{i}"

    def create(self, name: str, description: str = "", system_prompt: str = None,
               icon: str = "", disclaimer: str = None, capabilities=None,
               skills=None) -> dict:
        if not (name or "").strip():
            raise ValueError("Character name is required.")
        cid = self._unique_id(name)
        profile = {
            "id": cid,
            "name": name.strip(),
            "icon": icon or "",
            "description": (description or "").strip(),
            "system_prompt": (system_prompt or CUSTOM_PROMPT_TEMPLATE.format(
                name=name.strip(), description=(description or "").strip() or name.strip()
            )),
            "disclaimer": disclaimer,
            "capabilities": capabilities,
            "skills": skills,
        }
        with self._lock:
            data = self._write_profile(profile, builtin=False)
            self.profiles[cid] = data
        return data

    def duplicate(self, cid: str) -> dict:
        source = self.get(cid)
        if not source:
            raise ValueError(f"Character '{cid}' not found.")
        new_id = self._unique_id(f"{source['name']} copy")
        profile = dict(source)
        profile.update({
            "id": new_id,
            "name": f"{source['name']} (copy)",
            "builtin": False,
        })
        with self._lock:
            data = self._write_profile(profile, builtin=False)
            self.profiles[new_id] = data
        return data

    def save(self, profile: dict) -> dict:
        cid = _validate_id(profile.get("id"))
        current = self.profiles.get(cid)
        if current and current.get("builtin"):
            raise PermissionError(
                "Built-in characters are read-only. Duplicate it to make an "
                "editable copy."
            )
        with self._lock:
            data = self._write_profile(profile, builtin=False)
            self.profiles[cid] = data
        return data

    def delete(self, cid: str) -> str:
        cid = _validate_id(cid)
        prof = self.profiles.get(cid)
        if not prof:
            raise ValueError(f"Character '{cid}' not found.")
        if prof.get("builtin"):
            raise PermissionError("Built-in characters cannot be deleted.")
        import shutil
        folder = self.characters_dir / cid
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        with self._lock:
            self.profiles.pop(cid, None)
            if self.active_id == cid:
                self.active_id = GENERAL_ID
        return cid

    def reset_builtin(self, cid: str) -> dict:
        cid = _validate_id(cid)
        preset = next((p for p in PRESETS if p["id"] == cid), None)
        if not preset:
            raise ValueError(f"Character '{cid}' is not a built-in.")
        with self._lock:
            data = self._write_profile(preset, builtin=True)
            self.profiles[cid] = data
        return data

    def restore_defaults(self) -> list:
        """Re-write every built-in preset from the packaged defaults."""
        restored = []
        with self._lock:
            for preset in PRESETS:
                try:
                    data = self._write_profile(preset, builtin=True)
                    self.profiles[preset["id"]] = data
                    restored.append(preset["id"])
                except Exception:
                    logger.exception("Failed to restore '%s'.", preset["id"])
        return restored