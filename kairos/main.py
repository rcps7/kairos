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
from kairos.email_client import EmailClient
from kairos.gui.main_window import KairosGUI
from kairos.learning import ErrorMemory, reflect
from kairos.llm.client import LLMClient
from kairos.media_downloader import MediaDownloader
from kairos.peripherals.serial_manager import SerialManager
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


class KairosEngine:
    def __init__(self):
        self.config = load_config()
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
        self._loop = None
        self._thread = None
        self._retention_thread = None
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        self._heartbeat_stop = threading.Event()
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
    def ask_llm(self, prompt: str, provider_id: str = None, system_prompt: str = None) -> str:
        try:
            if system_prompt:
                return self.llm.generate(prompt, system_prompt=system_prompt, provider_id=provider_id)
            return self.llm.generate(prompt, provider_id=provider_id)
        except Exception as e:
            self.record_error("llm.generate", e)
            raise

    def chat_with_recall(self, prompt: str) -> str:
        """Answer a user message, injecting related retained data as context."""
        try:
            related = self.knowledge.recall(prompt, limit=6)
            if related:
                context_lines = []
                for item in related:
                    context_lines.append(f"- {item['text'][:400]}")
                context = "\n".join(context_lines)
                full_prompt = (
                    "You are KAIROS. Use the following related information from the "
                    "user's retained knowledge/memory if it helps answer the question.\n\n"
                    f"RELATED INFORMATION:\n{context}\n\n"
                    f"USER QUESTION: {prompt}"
                )
                return self.ask_llm(full_prompt)
            return self.ask_llm(prompt)
        except Exception as e:
            self.record_error("chat.recall", e)
            return self.ask_llm(prompt)

    # ---- Web ----
    def search_web(self, query: str, max_results: int = 10) -> list:
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
        try:
            data = self.web_scrape.fetch(url)
            summary = summarize_with_llm(self.llm, data["text"])
            import uuid
            doc_id = uuid.uuid4().hex
            self.knowledge.add_document(doc_id, url, data["html"], data["text"], summary)
            return {"id": doc_id, "url": url, "title": data["title"], "summary": summary}
        except Exception as e:
            self.record_error("learn_from_page", e)
            raise

    # ---- Media ----
    def download_media(self, url: str, fmt: str = "mp4") -> dict:
        try:
            return self.downloader.download(url, fmt)
        except Exception as e:
            self.record_error("media.download", e)
            raise

    # ---- Skills ----
    def list_skills(self) -> list:
        return self.skills.list_skills()

    def run_skill(self, name: str, **kwargs):
        return self.skills.run_skill(name, self, **kwargs)

    def generate_skill(self, name: str, description: str) -> str:
        """Generate a working skill using the LLM. Falls back to a stub on failure."""
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
        code = self.ask_llm(user, system_prompt=system)
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
        path = self.skills.create_skill(name, description, code)
        return str(path)

    def delete_skill(self, name: str) -> str:
        return self.skills.delete_skill(name)

    # ---- Email ----
    def read_email(self, limit: int = 10) -> list:
        return self.email.read_mail(limit)

    def send_email(self, to: str, subject: str, body: str) -> bool:
        return self.email.send_mail(to, subject, body)

    # ---- Peripherals ----
    def list_ports(self) -> list:
        return self.peripherals.list_ports()

    def open_port(self, device: str, baudrate: int = None) -> None:
        try:
            self.peripherals.open(device, baudrate)
        except Exception as e:
            self.record_error("peripheral.open", e)
            raise

    def close_port(self, device: str) -> None:
        self.peripherals.close(device)

    def write_port(self, device: str, text: str) -> int:
        try:
            return self.peripherals.write_text(device, text)
        except Exception as e:
            self.record_error("peripheral.write", e)
            raise

    def read_port(self, device: str, size: int = 1024) -> str:
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
        return self.knowledge.add_memory(content)

    def list_memories(self) -> list:
        return self.knowledge.list_memories()

    def delete_memory(self, mem_id: str):
        self.knowledge.delete_memory(mem_id)

    def recall(self, query: str, limit: int = 8) -> list:
        return self.knowledge.recall(query, limit)

    # ---- Learning / self-improvement ----
    def record_error(self, context: str, error: str):
        self.learning.record(context, error)

    def reflect(self) -> str:
        return reflect(self)

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
    if not cfg.get("telegram_token") or not has_llm_provider(cfg):
        prompt_for_setup(cfg)
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
