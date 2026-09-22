import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QGroupBox, QFormLayout,
)

from kairos.config import load_config, save_config
from kairos.characters import CharacterManager
from kairos.characters_presets import GENERAL_PROMPT
from kairos.council import Council
from kairos.graph_memory import GraphMemory
from kairos.pending_store import PendingStore
from kairos import memory_extract
from kairos.tools import build_tool_protocol, format_tool_results, parse_tool_calls
from kairos.email_client import EmailClient
from kairos.gui.main_window import KairosGUI
from kairos.learning import ErrorMemory, reflect
from kairos.llm.client import LLMClient
from kairos.media_downloader import MediaDownloader
from kairos.peripherals.serial_manager import SerialManager
from kairos.predictive.mirofish_client import MiroFishClient
from kairos.predictive.quick_predictor import QuickPredictor
from kairos.predictive.store import PredictiveStore
from kairos.retention import RetentionManager
from kairos.skills import SkillManager
from kairos.storage.knowledge import KnowledgeStore
from kairos.storage.media import MediaStore
from kairos.telegram_bot import TelegramBot
from kairos.watchdog import HEARTBEAT_FILE, KILLSWITCH_FILE, PID_FILE
from kairos.web import WebSearcher, WebScraper, summarize_with_llm

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 7 * 24 * 60 * 60  # weekly
HEARTBEAT_INTERVAL_SECONDS = 5
MAX_TOOL_ROUNDS = 3


class KairosEngine:
    def __init__(self):
        self.config = load_config()
        self.characters = CharacterManager(
            self.config.get("storage_root", ""),
            active_id=self.config.get("active_character", "general"),
            dir_name=self.config.get("character", {}).get("dir_name", "AGENT_CHARACTER"),
        )
        self.active_character = self.characters.active_id
        self.llm = LLMClient()
        self.peripherals = SerialManager(
            default_baud=self.config["peripherals"]["default_baud"]
        )
        self.knowledge = KnowledgeStore()
        self.media = MediaStore(self.config["storage_root"])
        self.telegram = TelegramBot(self)
        self.skills = SkillManager(self._skills_dir())
        self.web_search = WebSearcher()
        self.web_scrape = WebScraper()
        self.downloader = MediaDownloader(self.media)
        self.email = EmailClient()
        self.retention = RetentionManager(self)
        self.learning = ErrorMemory()
        self.predictive_store = PredictiveStore()
        self.mirofish = MiroFishClient(self.config.get("mirofish", {}).get("base_url", "http://localhost:5001"))
        self.quick_predictor = QuickPredictor(self)
        self.pending = PendingStore()
        self.graph = None
        self.on_pending_graph = None
        self._init_graph_memory()
        self._loop = None
        self._thread = None
        self._retention_thread = None
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._in_chat = False
        self._write_pid()
        self._start_heartbeat()

    def _skills_dir(self) -> str:
        base = self.config.get("storage_root", "")
        import os
        return os.path.join(base, "Kairos", "Skills")

    # ---- Watchdog / heartbeat ----
    def _write_pid(self):
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    def _start_heartbeat(self):
        def run():
            while not self._heartbeat_stop.is_set():
                try:
                    HEARTBEAT_FILE.write_text(
                        str(time.time()), encoding="utf-8"
                    )
                except Exception:
                    pass
                self._heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS)

        self._heartbeat_thread = threading.Thread(target=run, daemon=True)
        self._heartbeat_thread.start()

    def emergency_kill(self) -> bool:
        """Engage the kill switch: trigger the watchdog and hard-exit."""
        try:
            KILLSWITCH_FILE.write_text("KILL", encoding="utf-8")
        except Exception:
            pass
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        # Hard exit so the process dies even if the watchdog is not running.
        os._exit(1)
        return True

    def reload_llm(self):
        self.llm = LLMClient()

    # ---- LLM ----
    def ask_llm(self, prompt: str, provider_id: str = None, system_prompt: str = None,
                use_character: bool = True, with_tools: bool = False) -> str:
        try:
            if use_character:
                system_prompt = self.current_system_prompt(
                    system_prompt, with_tools=with_tools
                )
            if system_prompt:
                return self.llm.generate(prompt, system_prompt=system_prompt, provider_id=provider_id)
            return self.llm.generate(prompt, provider_id=provider_id)
        except Exception as e:
            self.record_error("llm.generate", e)
            raise

    def generate_with_images(self, prompt: str, image_paths, provider_id: str = None,
                             system_prompt: str = None, use_character: bool = True) -> str:
        """Vision call that respects the active agent character."""
        if use_character:
            system_prompt = self.current_system_prompt(system_prompt)
        if not system_prompt:
            system_prompt = "You are a helpful assistant."
        return self.llm.generate_with_images(
            prompt, image_paths, system_prompt=system_prompt, provider_id=provider_id
        )

    # ---- Agent Characters ----
    def current_system_prompt(self, extra: str = None, with_tools: bool = False) -> str:
        """Return the active character's system prompt.

        With ``with_tools`` the provider-agnostic tool protocol (restricted to
        the character's allowed capabilities) is appended so the model can
        request web tools.
        """
        base = self.characters.active().get("system_prompt") or GENERAL_PROMPT
        parts = [base]
        if with_tools:
            parts.append(build_tool_protocol(self.characters.capabilities()))
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    def character_capabilities(self) -> list:
        return self.characters.capabilities()

    def can(self, capability: str) -> bool:
        return self.characters.can(capability)

    def require(self, capability: str) -> None:
        """Raise PermissionError if the active character lacks a capability."""
        if not self.can(capability):
            name = self.characters.active().get("name", "This character")
            label = capability.replace("_", " ")
            raise PermissionError(
                f"'{name}' is not permitted to use the {label} capability. "
                "Switch character or edit the profile to allow it."
            )

    def list_characters(self) -> list:
        return self.characters.list()

    def active_character_profile(self) -> dict:
        return self.characters.active()

    def set_character(self, char_id: str) -> dict:
        prof = self.characters.set_active(char_id)
        cfg = load_config()
        cfg["active_character"] = prof["id"]
        save_config(cfg)
        self.config = load_config()
        self.active_character = prof["id"]
        return prof

    def reload_characters(self) -> list:
        """Re-point character storage (e.g. after the storage root changes)."""
        self.characters.dir_name = self.config.get("character", {}).get(
            "dir_name", "AGENT_CHARACTER"
        )
        self.characters.set_root(self.config.get("storage_root", ""))
        self.active_character = self.characters.active_id
        return self.characters.list()

    def create_character(self, name: str, description: str = "", system_prompt: str = None,
                         icon: str = "", disclaimer: str = None, capabilities=None,
                         skills=None) -> dict:
        return self.characters.create(
            name, description, system_prompt, icon, disclaimer, capabilities, skills
        )

    def save_character(self, profile: dict) -> dict:
        return self.characters.save(profile)

    def delete_character(self, char_id: str) -> str:
        return self.characters.delete(char_id)

    def duplicate_character(self, char_id: str) -> dict:
        return self.characters.duplicate(char_id)

    def reset_character(self, char_id: str) -> dict:
        return self.characters.reset_builtin(char_id)

    def restore_default_characters(self) -> list:
        return self.characters.restore_defaults()

    # ---- Long-term graph memory (LadybugDB) ----
    def _graph_cfg(self) -> dict:
        return self.config.get("graph_memory", {}) or {}

    def _graph_embed_fn(self):
        fn = getattr(self.knowledge, "_embed_fn", None)
        return fn

    def _init_graph_memory(self):
        cfg = self._graph_cfg()
        if not cfg.get("enabled", True):
            return
        try:
            db_path = cfg.get("db_path") or str(Path.home() / ".kairos" / "graph.lbdb")
            self.graph = GraphMemory(
                db_path,
                embed_fn=self._graph_embed_fn(),
                dedup_distance=float(cfg.get("dedup_distance", 0.15)),
            )
            if not self.graph.available:
                logger.warning("Graph memory unavailable: %s", self.graph.error)
        except Exception:
            logger.exception("Failed to initialise graph memory.")
            self.graph = None

    def graph_context(self, query: str) -> str:
        cfg = self._graph_cfg()
        if not self.graph or not cfg.get("enabled", True):
            return ""
        try:
            return self.graph.retrieve(
                query,
                k_nodes=int(cfg.get("max_nodes", 12)),
                k_memories=int(cfg.get("max_memories", 6)),
            ).get("context", "")
        except Exception as e:
            self.record_error("graph.retrieve", e)
            return ""

    def ingest_graph(self, text: str, source: str = "chat", kind: str = "chat"):
        """Extract knowledge and either queue it for approval or store it."""
        cfg = self._graph_cfg()
        if not self.graph or not cfg.get("enabled", True):
            return None
        if not memory_extract.should_extract(text):
            return None
        try:
            proposal = memory_extract.extract(self, text, source=source, kind=kind)
        except Exception as e:
            self.record_error("graph.extract", e)
            return None
        if not proposal.get("entities"):
            return None
        if cfg.get("require_approval", True) and not cfg.get("auto_approve", False):
            pid = self.pending.add(proposal, source=source, kind=kind)
            self._notify_pending(pid, proposal)
            return {"pending": pid, "entities": len(proposal["entities"])}
        try:
            self.graph.upsert(proposal.get("entities"), proposal.get("relations"), proposal.get("memory"))
        except Exception as e:
            self.record_error("graph.store", e)
            return None
        return {"stored": len(proposal["entities"])}

    def spawn_graph_extract(self, text: str, source: str = "chat", kind: str = "chat"):
        cfg = self._graph_cfg()
        if not self.graph or not cfg.get("enabled", True) or not cfg.get("extract_on_chat", True):
            return
        threading.Thread(
            target=self.ingest_graph, args=(text, source, kind), daemon=True
        ).start()

    def _notify_pending(self, pid: str, proposal: dict):
        try:
            if self.telegram and self.telegram.running and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.telegram.prompt_graph_approval(pid, proposal), self._loop
                )
        except Exception:
            pass
        cb = getattr(self, "on_pending_graph", None)
        if cb:
            try:
                cb(pid, proposal)
            except Exception:
                pass

    # ---- Pending approval queue ----
    def graph_pending_count(self) -> int:
        try:
            return self.pending.count_pending()
        except Exception:
            return 0

    def list_pending_graph(self, limit: int = 100) -> list:
        return self.pending.list("pending", limit)

    def get_pending_graph(self, pid: str) -> dict:
        return self.pending.get(pid)

    def update_pending_graph(self, pid: str, payload: dict) -> bool:
        return self.pending.update_payload(pid, payload)

    def reject_pending_graph(self, pid: str) -> bool:
        return self.pending.mark(pid, "rejected")

    def approve_pending_graph(self, pid: str) -> bool:
        item = self.pending.get(pid)
        if not item:
            return False
        payload = item.get("payload", {})
        try:
            if self.graph:
                self.graph.upsert(payload.get("entities"), payload.get("relations"),
                                  payload.get("memory"))
        except Exception as e:
            self.record_error("graph.store", e)
            return False
        self.pending.mark(pid, "approved")
        return True

    def approve_all_pending_graph(self) -> int:
        n = 0
        for item in self.list_pending_graph():
            if self.approve_pending_graph(item["id"]):
                n += 1
        return n

    def reject_all_pending_graph(self) -> int:
        n = 0
        for item in self.list_pending_graph():
            if self.reject_pending_graph(item["id"]):
                n += 1
        return n

    # ---- Graph CRUD ----
    def graph_search(self, query: str, limit: int = 20) -> dict:
        if not self.graph:
            return {"entities": [], "relations": [], "memories": []}
        return self.graph.search(query, limit)

    def graph_stats(self) -> dict:
        if not self.graph:
            return {"available": False}
        return self.graph.stats()

    def graph_list_entities(self, limit: int = 200) -> list:
        return self.graph.list_entities(limit) if self.graph else []

    def graph_update_entity(self, eid, **kwargs) -> bool:
        return self.graph.update_entity(eid, **kwargs) if self.graph else False

    def graph_delete_entity(self, eid) -> bool:
        return self.graph.delete_entity(eid) if self.graph else False

    def graph_delete_relation(self, sid, predicate, oid) -> bool:
        return self.graph.delete_relation(sid, predicate, oid) if self.graph else False

    def graph_delete_memory(self, mid) -> bool:
        return self.graph.delete_memory(mid) if self.graph else False

    def graph_clear(self) -> bool:
        return self.graph.clear() if self.graph else False

    def chat(self, prompt: str, attachment_paths=None, progress=None) -> str:
        """Answer a user message with context, recall, vision and tool access.

        The model may request web tools (search / learn / scrape) using the
        documented tool protocol; those are executed here and their results fed
        back for a final answer. Only web tools are exposed to the model.
        """
        if getattr(self, "_in_chat", False):
            # Re-entrancy guard: tool execution must not start another chat loop.
            return self.ask_llm(prompt)
        self._in_chat = True
        try:
            context, images = ("", [])
            if attachment_paths:
                try:
                    context, images = self.attach_context(attachment_paths)
                except Exception as e:
                    self.record_error("chat.attachments", e)
                    context, images = ("", [])

            user_content = self._build_user_content(prompt, context)

            # Vision: if images are present and a vision provider exists, answer
            # in one call (no tool loop).
            if images:
                vis = [p for p in self.list_providers() if self.llm.is_vision(p)]
                if vis:
                    return self.generate_with_images(
                        user_content, images, provider_id=vis[0]
                    )

            conversation = user_content
            reply = ""
            for round_index in range(MAX_TOOL_ROUNDS):
                reply = self.ask_llm(conversation, with_tools=True)
                clean, calls = parse_tool_calls(reply)
                if not calls:
                    return clean or reply

                results = []
                for call in calls:
                    if progress:
                        try:
                            progress(f"Running tool: {call.name} "
                                     f"{call.query or call.url}".strip())
                        except Exception:
                            pass
                    results.append((call, self._run_tool(call)))

                conversation = (
                    f"{conversation}\n\nASSISTANT TOOL REQUEST:\n{reply}\n\n"
                    f"{format_tool_results(results)}\n\n"
                    "Now answer the user's original question using the tool "
                    "results above. Do not emit more tool tags unless essential."
                )

            # Rounds exhausted: return whatever prose we have.
            clean, _ = parse_tool_calls(reply)
            if clean:
                return clean
            return ("I gathered some information but could not finish the answer. "
                    "Please refine your request or try again.")
        except Exception as e:
            self.record_error("chat", e)
            try:
                return self.ask_llm(prompt)
            except Exception:
                raise
        finally:
            self._in_chat = False
            cfg = self._graph_cfg()
            if cfg.get("use_in_chat", True) or cfg.get("use_in_tools", True):
                self.spawn_graph_extract(prompt, source="chat", kind="chat")

    def _build_user_content(self, prompt: str, context: str) -> str:
        sections = []
        if context:
            sections.append(f"ATTACHED MATERIAL:\n{context}")
        try:
            related = self.knowledge.recall(prompt, limit=6)
        except Exception:
            related = []
        if related:
            recall = "\n".join(f"- {item['text'][:400]}" for item in related)
            sections.append(
                "RELATED INFORMATION FROM RETAINED MEMORY (use only if relevant "
                "to the question; ignore unrelated items):\n" + recall
            )
        cfg = self._graph_cfg()
        if cfg.get("enabled", True) and cfg.get("use_in_chat", True):
            graph_ctx = self.graph_context(prompt)
            if graph_ctx:
                sections.append(graph_ctx)
        sections.append(f"USER QUESTION:\n{prompt}")
        return "\n\n".join(sections)

    def _run_tool(self, call) -> str:
        """Execute a single model-requested tool, respecting capabilities."""
        try:
            if call.name == "web_search":
                if not call.query:
                    return "(no search query provided)"
                results = self.search_web(call.query, max_results=8)
                if not results:
                    return f"(no results for: {call.query})"
                lines = []
                for i, r in enumerate(results[:8], 1):
                    lines.append(
                        f"{i}. {r.get('title', 'Untitled')} — {r.get('url', '')}\n"
                        f"   {(r.get('description') or '').strip()}"
                    )
                return "\n".join(lines)

            if not self.can("learn_web"):
                self.require("learn_web")  # raises PermissionError

            if call.name == "learn_web":
                if not call.url:
                    return "(no url provided)"
                data = self.learn_from_page(call.url)
                return f"Page: {data.get('title', call.url)}\n{data.get('summary', '')}"

            if call.name == "scrape":
                if not call.url:
                    return "(no url provided)"
                data = self.scrape_page(call.url)
                return f"Page: {data.get('title', call.url)}\n{(data.get('text') or '')[:6000]}"

            return f"(unknown tool: {call.name})"
        except PermissionError as e:
            return f"(tool not permitted: {e})"
        except Exception as e:
            self.record_error("chat.tool", e)
            return f"(tool error: {e})"

    def chat_with_recall(self, prompt: str) -> str:
        """Backwards-compatible alias for :meth:`chat`."""
        return self.chat(prompt)

    # ---- Attachments & Council ----
    def attach_context(self, paths):
        """Extract text + image paths from attached files/folders."""
        from kairos.attachments import build_attachment_context
        summarize_fn = None
        try:
            summarize_fn = lambda t: self.ask_llm(t)
        except Exception:
            summarize_fn = None
        return build_attachment_context(paths, summarize_fn=summarize_fn)

    def council(self, prompt: str, members=None, attachment_paths=None,
                mode: str = "standard", progress=None) -> dict:
        """Run the multi-LLM council on a task."""
        self.require("council")
        try:
            context, images = ("", [])
            if attachment_paths:
                context, images = self.attach_context(attachment_paths)
            cfg = self._graph_cfg()
            if self.graph and cfg.get("use_in_council", True):
                g = self.graph_context(prompt)
                if g:
                    context = f"{context}\n\n{g}" if context else g
            if not members:
                members = self.config.get("council", {}).get("members") or []
            council = Council(self)
            result = council.run(prompt, members, context=context, image_paths=images,
                                 mode=mode, progress=progress)
            # Save the final result for later recall.
            try:
                self.knowledge.add_memory(f"[Council] {prompt}\n{result.get('final', '')[:3000]}")
            except Exception:
                pass
            return result
        except Exception as e:
            self.record_error("council", e)
            raise

    def list_providers(self) -> list:
        return self.llm.list_providers()

    # ---- Web ----
    def search_web(self, query: str, max_results: int = 10) -> list:
        self.require("web_search")
        try:
            return self.web_search.search(query, max_results=max_results)
        except Exception as e:
            self.record_error("web.search", e)
            raise

    def scrape_page(self, url: str) -> dict:
        try:
            return self.web_scrape.fetch(url)
        except Exception as e:
            self.record_error("web.scrape", e)
            raise

    def learn_from_page(self, url: str) -> dict:
        self.require("learn_web")
        try:
            data = self.web_scrape.fetch(url)
            summary = summarize_with_llm(
                self.llm, data["text"], system_prompt=self.current_system_prompt()
            )
            import uuid
            doc_id = uuid.uuid4().hex
            self.knowledge.add_document(doc_id, url, data["html"], data["text"], summary)
            self.spawn_graph_extract(summary, source="web", kind="document")
            return {"id": doc_id, "url": url, "title": data["title"], "summary": summary}
        except Exception as e:
            self.record_error("learn_from_page", e)
            raise

    # ---- Media ----
    def download_media(self, url: str, fmt: str = "mp4") -> dict:
        self.require("download_media")
        try:
            return self.downloader.download(url, fmt)
        except Exception as e:
            self.record_error("media.download", e)
            raise

    # ---- Skills ----
    def list_skills(self) -> list:
        return self.skills.list_skills()

    def run_skill(self, name: str, **kwargs):
        self.require("skills_run")
        if not self.characters.allows_skill(name):
            prof = self.characters.active()
            raise PermissionError(
                f"Skill '{name}' is not available to the "
                f"'{prof.get('name', 'current')}' character."
            )
        return self.skills.run_skill(name, self, **kwargs)

    def generate_skill(self, name: str, description: str) -> str:
        """Generate a working skill using the LLM. Falls back to a stub on failure."""
        self.require("skills_manage")
        try:
            return self._llm_generate_skill(name, description)
        except Exception as e:
            self.record_error("skill.generate", e)
            return self.skills.generate_skill_code(name, description)

    def _llm_generate_skill(self, name: str, description: str) -> str:
        system = (
            "You are an expert Python developer writing skills for the Kairos AI agent. "
            "Return ONLY Python code, no markdown fences, no explanations."
        )
        user = (
            f"Write a complete Kairos skill.\n"
            f"Skill name (lowercase, underscores): {name}\n"
            f"Skill description: {description}\n\n"
            "Requirements:\n"
            "- Define a class that subclasses `Skill` imported from `kairos.skills.base`.\n"
            "- Set class attributes: `name = \"<name>\"` and `description = \"<description>\"`.\n"
            "- Implement `def run(self, engine, **kwargs)` that actually performs the "
            "described task and returns a string result.\n"
            "- The `engine` object provides: ask_llm(prompt), search_web(query), "
            "learn_from_page(url), download_media(url, fmt), read_email(limit), "
            "send_email(to, subject, body), list_ports(), open_port(device, baud), "
            "write_port(device, text), read_port(device).\n"
            "- Use only the Python standard library or PySide6 (for popup windows).\n"
            "- Do not import Kairos modules other than `kairos.skills.base`.\n"
            "Output the code now."
        )
        cfg = self._graph_cfg()
        if self.graph and cfg.get("use_in_skills", True):
            g = self.graph_context(description)
            if g:
                user += f"\n\nRELEVANT EXISTING KNOWLEDGE (context only):\n{g}"
        code = self.ask_llm(user, system_prompt=system, use_character=False)
        code = self._strip_code_fences(code)
        if "def run" not in code or "class " not in code:
            raise RuntimeError("LLM returned invalid skill code.")
        return code

    def _strip_code_fences(self, code: str) -> str:
        code = code.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        return code.strip()

    def create_skill(self, name: str, description: str, code: str) -> str:
        self.require("skills_manage")
        path = self.skills.create_skill(name, description, code)
        return str(path)

    def delete_skill(self, name: str) -> str:
        self.require("skills_manage")
        return self.skills.delete_skill(name)

    # ---- Email ----
    def read_email(self, limit: int = 10) -> list:
        self.require("email_read")
        return self.email.read_mail(limit)

    def send_email(self, to: str, subject: str, body: str) -> bool:
        self.require("email_send")
        return self.email.send_mail(to, subject, body)

    # ---- Peripherals ----
    def list_ports(self) -> list:
        self.require("peripherals")
        return self.peripherals.list_ports()

    def open_port(self, device: str, baudrate: int = None) -> None:
        self.require("peripherals")
        try:
            self.peripherals.open(device, baudrate)
        except Exception as e:
            self.record_error("peripheral.open", e)
            raise

    def close_port(self, device: str) -> None:
        self.require("peripherals")
        self.peripherals.close(device)

    def write_port(self, device: str, text: str) -> int:
        self.require("peripherals")
        try:
            return self.peripherals.write_text(device, text)
        except Exception as e:
            self.record_error("peripheral.write", e)
            raise

    def read_port(self, device: str, size: int = 1024) -> str:
        self.require("peripherals")
        try:
            return self.peripherals.read_text(device, size)
        except Exception as e:
            self.record_error("peripheral.read", e)
            raise

    # ---- Retention ----
    def collect_expired(self) -> list:
        return self.retention.collect_expired()

    def approve_retention_deletion(self, selected_ids: list) -> int:
        return self.retention.approve(selected_ids)

    # ---- Memories (user-retained data) ----
    def add_memory(self, content: str) -> str:
        self.require("memory")
        mem_id = self.knowledge.add_memory(content)
        self.spawn_graph_extract(content, source="remember", kind="note")
        return mem_id

    def list_memories(self) -> list:
        self.require("memory")
        return self.knowledge.list_memories()

    def delete_memory(self, mem_id: str):
        self.require("memory")
        self.knowledge.delete_memory(mem_id)

    def recall(self, query: str, limit: int = 8) -> list:
        return self.knowledge.recall(query, limit)

    # ---- Predictive engine ----
    def predict(self, question: str, files=None, links=None, text=None, mode="auto") -> dict:
        """Run a prediction. mode: auto | mirofish | quick."""
        from kairos.predictive.ingest import build_seed

        self.require("predict")
        try:
            seed = build_seed(question, files=files, links=links, text=text, engine=self)
            cfg = self._graph_cfg()
            if self.graph and cfg.get("use_in_predict", True):
                g = self.graph_context(question)
                if g:
                    seed = f"{seed}\n\n{g}"
            pid = self.predictive_store.add(question, source=mode, status="running")

            mirofish_enabled = self.config.get("mirofish", {}).get("enabled", False)
            use_mirofish = mode == "mirofish" or (mode == "auto" and mirofish_enabled)

            report = None
            source = "quick"
            if use_mirofish:
                try:
                    if not self.mirofish.is_available():
                        if mode == "mirofish":
                            raise RuntimeError(
                                "MiroFish service is not reachable at "
                                f"{self.config.get('mirofish', {}).get('base_url', 'http://localhost:5001')}. "
                                "MiroFish is a SEPARATE program you must install and run yourself "
                                "(see README). To predict without it, use 'Auto' or 'Quick' mode."
                            )
                    else:
                        report = self.mirofish.predict(seed, question)
                        source = "mirofish"
                except Exception as e:
                    if mode == "mirofish":
                        raise
                    self.record_error("predict.mirofish", e)
                    report = None

            if report is None:
                report = self.quick_predictor.predict(seed, question)
                source = "quick"

            self.predictive_store.update(pid, status="done", report=report)
            # Also save to retention so it's recallable later.
            self.knowledge.add_memory(f"[Prediction] {question}\n{report[:3000]}")
            self.spawn_graph_extract(report, source="prediction", kind="prediction")
            return {"id": pid, "question": question, "source": source, "report": report}
        except Exception as e:
            self.record_error("predict", e)
            raise

    def list_predictions(self, limit: int = 10) -> list:
        return self.predictive_store.list_recent(limit)

    # ---- Learning / self-improvement ----
    def record_error(self, context: str, error: str):
        self.learning.record(context, error)

    def reflect(self) -> str:
        analysis = reflect(self)
        self.spawn_graph_extract(analysis, source="reflection", kind="lesson")
        return analysis

    def recent_lessons(self, limit: int = 10) -> list:
        return self.learning.recent_lessons(limit)

    # ---- Telegram ----
    def start_telegram(self):
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(self.telegram.start())
                loop.run_forever()
            finally:
                try:
                    loop.run_until_complete(self.telegram.stop())
                except Exception:
                    pass
                loop.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop_telegram(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ---- Background retention sweep ----
    def start_retention_loop(self):
        def run():
            while not self._stop_event.is_set():
                try:
                    items = self.collect_expired()
                    if items:
                        logger.info("Retention sweep found %d expired item(s).", len(items))
                        if self.telegram.running:
                            asyncio.run_coroutine_threadsafe(
                                self.telegram.prompt_retention(items), self._loop
                            )
                except Exception:
                    logger.exception("Retention sweep failed.")
                self._stop_event.wait(RETENTION_INTERVAL_SECONDS)

        self._retention_thread = threading.Thread(target=run, daemon=True)
        self._retention_thread.start()

    def stop_retention_loop(self):
        self._stop_event.set()

    def shutdown(self):
        self._heartbeat_stop.set()
        self.stop_telegram()
        self.stop_retention_loop()
        self.peripherals.close_all()
        self.web_search.close()
        self.web_scrape.close()
        self.learning.close()
        self.predictive_store.close()
        self.mirofish.close()
        try:
            if self.graph:
                self.graph.close()
        except Exception:
            pass
        try:
            self.pending.close()
        except Exception:
            pass
        self.llm.close()
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass


LLM_PRESETS = [
    {
        "id": "moonshot",
        "name": "Moonshot AI (Kimi)",
        "api_url": "https://api.moonshot.ai/v1/chat/completions",
        "model": "kimi-k3",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "api_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openrouter/auto",
    },
    {
        "id": "groq",
        "name": "Groq",
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
    },
]


class SetupDialog(QDialog):
    """First-run setup wizard with skippable Telegram and a provider dropdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kairos Setup")
        self.resize(520, 400)
        self.telegram_token = None
        self.llm = None  # dict {provider_id, api_url, api_key, model} or None

        self.setStyleSheet("""
            QDialog { background-color: #0d1117; }
            QLabel { color: #e6edf3; font-family: 'Segoe UI', sans-serif; }
            QLineEdit, QComboBox {
                background-color: #1c2128; color: #00ff66;
                border: 1px solid #30363d; border-radius: 4px; padding: 6px;
                font-family: 'Consolas', monospace;
            }
            QPushButton {
                background-color: #2d333b; color: #e6edf3;
                border: 1px solid #30363d; border-radius: 5px; padding: 7px 16px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover { background-color: #3a4149; color: #00ff66; }
            QGroupBox {
                border: 1px solid #30363d; border-radius: 6px; margin-top: 10px;
                color: #00ff66; font-weight: bold; font-family: 'Segoe UI', sans-serif;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        """)

        layout = QVBoxLayout(self)

        # --- Telegram (skippable) ---
        tg_box = QGroupBox("Telegram (optional)")
        tg_layout = QVBoxLayout(tg_box)
        tg_row = QHBoxLayout()
        self.tg_edit = QLineEdit()
        self.tg_edit.setPlaceholderText("Bot token from @BotFather")
        self.tg_edit.setEchoMode(QLineEdit.Password)
        self.skip_tg_btn = QPushButton("Skip")
        self.skip_tg_btn.clicked.connect(self._skip_telegram)
        tg_row.addWidget(self.tg_edit, 1)
        tg_row.addWidget(self.skip_tg_btn)
        tg_layout.addLayout(tg_row)
        layout.addWidget(tg_box)

        # --- LLM provider (dropdown) ---
        llm_box = QGroupBox("LLM Provider")
        llm_layout = QFormLayout(llm_box)
        self.provider_combo = QComboBox()
        for preset in LLM_PRESETS:
            self.provider_combo.addItem(preset["name"], preset)
        self.provider_combo.addItem("Custom / Other", None)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        self.id_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Required")

        llm_layout.addRow("Provider:", self.provider_combo)
        llm_layout.addRow("Provider ID:", self.id_edit)
        llm_layout.addRow("API URL:", self.url_edit)
        llm_layout.addRow("Model:", self.model_edit)
        llm_layout.addRow("API Key:", self.key_edit)
        layout.addWidget(llm_box)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        self.skip_llm_btn = QPushButton("Skip LLM")
        self.skip_llm_btn.clicked.connect(self._skip_llm)
        self.finish_btn = QPushButton("Continue")
        self.finish_btn.setStyleSheet("background-color: #00b84d; color: #0d1117; font-weight: bold;")
        self.finish_btn.clicked.connect(self._finish)
        btn_row.addWidget(self.skip_llm_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.finish_btn)
        layout.addLayout(btn_row)

        self._on_provider_changed()

    def _on_provider_changed(self):
        preset = self.provider_combo.currentData()
        if preset:
            self.id_edit.setText(preset["id"])
            self.url_edit.setText(preset["api_url"])
            self.model_edit.setText(preset["model"])
        else:
            self.id_edit.setText("")
            self.url_edit.setText("")
            self.model_edit.setText("")

    def _skip_telegram(self):
        self.tg_edit.clear()
        self.tg_edit.setPlaceholderText("Skipped — you can add it later in Settings")
        self.telegram_token = None
        self.skip_tg_btn.setEnabled(False)

    def _skip_llm(self):
        self.llm = None
        self.accept()

    def _finish(self):
        token = self.tg_edit.text().strip()
        self.telegram_token = token or None

        api_key = self.key_edit.text().strip()
        if not api_key:
            self.llm = None
        else:
            provider_id = self.id_edit.text().strip() or "custom"
            api_url = self.url_edit.text().strip()
            model = self.model_edit.text().strip()
            self.llm = {
                "provider_id": provider_id,
                "api_url": api_url,
                "api_key": api_key,
                "model": model,
            }
        self.accept()


def prompt_for_setup(cfg: dict) -> bool:
    dlg = SetupDialog()
    if dlg.exec() != QDialog.Accepted:
        # User closed the window; proceed with whatever is already in cfg.
        return True

    if dlg.telegram_token:
        cfg["telegram_token"] = dlg.telegram_token
    if dlg.llm:
        pid = dlg.llm["provider_id"]
        cfg["llm_providers"][pid] = {
            "api_url": dlg.llm["api_url"],
            "api_key": dlg.llm["api_key"],
            "model": dlg.llm["model"],
        }
        cfg["active_llm"] = pid
    save_config(cfg)
    return True


def has_llm_provider(cfg: dict) -> bool:
    providers = cfg.get("llm_providers", {})
    return any(p.get("api_key") for p in providers.values())


def main():
    app = QApplication(sys.argv)

    cfg = load_config()
    if not cfg.get("setup_done"):
        prompt_for_setup(cfg)
        cfg = load_config()
        cfg["setup_done"] = True
        save_config(cfg)
        cfg = load_config()

    engine = KairosEngine()
    engine.start_telegram()
    engine.start_retention_loop()

    gui = KairosGUI(engine)
    gui.show()

    try:
        sys.exit(app.exec())
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
