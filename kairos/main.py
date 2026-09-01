import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QInputDialog

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


def prompt_for_setup(cfg: dict) -> bool:
    token, ok1 = QInputDialog.getText(None, "Kairos Setup", "Enter Telegram Bot Token:")
    if not ok1 or not token.strip():
        return False
    cfg["telegram_token"] = token.strip()
    save_config(cfg)

    provider_id, ok2 = QInputDialog.getText(None, "Kairos Setup", "LLM Provider ID (e.g. moonshot):", text="moonshot")
    if not ok2 or not provider_id.strip():
        return False
    api_url, ok3 = QInputDialog.getText(
        None, "Kairos Setup", "LLM API URL:",
        text="https://api.moonshot.ai/v1/chat/completions"
    )
    if not ok3 or not api_url.strip():
        return False
    api_key, ok4 = QInputDialog.getText(None, "Kairos Setup", "LLM API Key:")
    if not ok4 or not api_key.strip():
        return False
    model, ok5 = QInputDialog.getText(None, "Kairos Setup", "LLM Model:", text="kimi-k3")
    if not ok5 or not model.strip():
        return False

    cfg["llm_providers"][provider_id.strip()] = {
        "api_url": api_url.strip(),
        "api_key": api_key.strip(),
        "model": model.strip()
    }
    cfg["active_llm"] = provider_id.strip()
    save_config(cfg)
    return True


def has_llm_provider(cfg: dict) -> bool:
    providers = cfg.get("llm_providers", {})
    return any(p.get("api_key") for p in providers.values())


def main():
    app = QApplication(sys.argv)

    cfg = load_config()
    if not cfg.get("telegram_token") or not has_llm_provider(cfg):
        if not prompt_for_setup(cfg):
            print("Setup cancelled. Telegram token and LLM API key are required.")
            sys.exit(1)
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
