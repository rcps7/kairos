import html
import json
import math
import sys
import time
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QTextEdit, QTextBrowser, QLineEdit, QPushButton,
                               QListWidget, QSplitter, QMenuBar, QStatusBar,
                               QFileDialog, QCheckBox, QDialog, QFormLayout,
                               QListWidgetItem, QLabel, QDialogButtonBox,
                               QMessageBox, QToolBar, QGroupBox, QFrame,
                               QGridLayout, QComboBox, QTreeWidget, QTreeWidgetItem,
                               QScrollArea, QMenu, QTabWidget)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QTimer, QBuffer, QByteArray, QIODevice, QObject
from PySide6.QtGui import QAction, QFont, QColor, QPalette, QIcon, QTextCursor, QPixmap

try:
    from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QVideoSink
    _MULTIMEDIA = True
except Exception:
    _MULTIMEDIA = False

from kairos.gui.voice_widgets import VoiceWorker, SpeakWorker, VoiceMeter, MoodIndicator
from kairos.characters_presets import ALL_CAPABILITIES, CAPABILITY_LABELS
from kairos import updater

# ---------------------------------------------------------------------------
# Colour palette (dark theme + fluorescent green accents + grey-white buttons)
# ---------------------------------------------------------------------------
BG_DARK = "#0d1117"
BG_PANEL = "#161b22"
BG_INPUT = "#1c2128"
BG_BUTTON = "#2d333b"
BG_BUTTON_HOVER = "#3a4149"
GREEN = "#00ff66"
GREEN_DIM = "#00b84d"
TEXT = "#e6edf3"
TEXT_GREY = "#9aa5b1"
BORDER = "#30363d"
RED = "#ff4d4d"



from .common import *  # noqa
from .common import _merge_save, _dialog_style, _MainThreadInvoker  # noqa
from .widgets import *  # noqa
from .widgets import _format_response  # noqa
from .workers import *  # noqa

class ProviderDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("LLM Providers")
        self.setStyleSheet(_dialog_style())
        self.resize(520, 420)
        self.build_ui()
        self.refresh()

    def build_ui(self):
        layout = QVBoxLayout(self)
        header = QLabel("LLM Providers")
        header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {GREEN};")
        layout.addWidget(header)

        active_row = QHBoxLayout()
        active_row.addWidget(QLabel("Active:"))
        self.active_label = QLabel("")
        self.active_label.setStyleSheet(f"color: {GREEN}; font-weight: bold;")
        active_row.addWidget(self.active_label)
        active_row.addStretch()
        layout.addLayout(active_row)

        self.provider_list = QListWidget()
        layout.addWidget(self.provider_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self.add_provider)
        self.set_btn = QPushButton("Set Active")
        self.set_btn.clicked.connect(self.set_active)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_provider)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.set_btn)
        btn_row.addWidget(self.remove_btn)
        layout.addLayout(btn_row)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def refresh(self):
        self.provider_list.clear()
        providers = self.engine.llm.providers
        active = self.engine.llm.active_provider
        self.active_label.setText(active or "None")
        for pid, p in providers.items():
            model = p.get("model", "")
            key = "key OK" if p.get("api_key") else "NO KEY"
            vision = " | vision" if p.get("vision") else ""
            marker = " * " if pid == active else "   "
            item = QListWidgetItem(f"{marker} {pid}   |   {model}   |   {key}{vision}")
            item.setData(Qt.UserRole, pid)
            self.provider_list.addItem(item)

    def _selected_pid(self):
        item = self.provider_list.currentItem()
        if not item:
            return None
        pid = item.data(Qt.UserRole)
        if not pid:
            # Fallback for older items without stored data.
            pid = item.text().strip().lstrip("* ").split(" ")[0]
        return pid

    def add_provider(self):
        dlg = ProviderEditDialog(self)
        if dlg.exec():
            self.engine.llm.add_provider(dlg.provider_id, dlg.api_url, dlg.api_key, dlg.model, dlg.vision)
            self.refresh()

    def set_active(self):
        pid = self._selected_pid()
        if not pid:
            return
        if self.engine.llm.set_active(pid):
            self.refresh()

    def remove_provider(self):
        pid = self._selected_pid()
        if not pid:
            return
        self.engine.llm.remove_provider(pid)
        self.refresh()


class ProviderEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add LLM Provider")
        self.setStyleSheet(_dialog_style())
        self.resize(420, 280)
        layout = QFormLayout(self)
        layout.setSpacing(12)
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("e.g. moonshot, openai, deepseek")
        self.url_edit = QLineEdit()
        self.url_edit.setText("https://api.moonshot.ai/v1/chat/completions")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit()
        self.model_edit.setText("kimi-k3")
        self.vision_check = QCheckBox("Vision-capable (accepts images)")
        layout.addRow("Provider ID:", self.id_edit)
        layout.addRow("API URL:", self.url_edit)
        layout.addRow("API Key:", self.key_edit)
        layout.addRow("Model:", self.model_edit)
        layout.addRow(self.vision_check)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self):
        self.provider_id = self.id_edit.text().strip()
        self.api_url = self.url_edit.text().strip()
        self.api_key = self.key_edit.text().strip()
        self.model = self.model_edit.text().strip()
        self.vision = self.vision_check.isChecked()
        if not self.provider_id or not self.api_url:
            QMessageBox.warning(self, "Kairos", "Provider ID and API URL are required.")
            return
        if "|" in self.provider_id:
            QMessageBox.warning(self, "Kairos", "Provider ID cannot contain the '|' character.")
            return
        super().accept()


class StorageDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Storage Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(520, 160)
        layout = QFormLayout(self)
        layout.setSpacing(12)
        self.path_edit = QLineEdit()
        self.path_edit.setText(self.engine.config.get("storage_root", ""))
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.path_edit)
        row.addWidget(self.browse_btn)
        layout.addRow("Storage drive:", row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Storage Drive", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def accept(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Kairos", "Please select a valid path.")
            return
        self.engine.config = _merge_save(lambda c: c.__setitem__("storage_root", path))
        try:
            self.engine.reload_characters()
        except Exception:
            pass
        QMessageBox.information(self, "Kairos", f"Storage set to {path}")
        super().accept()


class MiroFishDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("MiroFish / Predictive Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(460, 260)
        layout = QFormLayout(self)
        layout.setSpacing(12)

        cfg = engine.config.get("mirofish", {})
        self.enabled_check = QCheckBox("Enable MiroFish swarm simulation")
        self.enabled_check.setChecked(bool(cfg.get("enabled", False)))
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setText(cfg.get("base_url", "http://localhost:5001"))
        self.zep_key_edit = QLineEdit()
        self.zep_key_edit.setEchoMode(QLineEdit.Password)
        self.zep_key_edit.setText(cfg.get("zep_api_key") or "")
        self.zep_key_edit.setPlaceholderText("Zep API key (for MiroFish agent memory)")

        layout.addRow(self.enabled_check)
        layout.addRow("MiroFish base URL:", self.base_url_edit)
        layout.addRow("Zep API Key:", self.zep_key_edit)

        hint = QLabel("Get a free Zep key at https://app.getzep.com/\nMiroFish runs separately (see README).")
        hint.setStyleSheet(f"color: {TEXT_GREY}; font-family: 'Segoe UI', sans-serif;")
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self):
        def _apply(c):
            m = c.setdefault("mirofish", {})
            m["enabled"] = self.enabled_check.isChecked()
            m["base_url"] = self.base_url_edit.text().strip() or "http://localhost:5001"
            m["zep_api_key"] = self.zep_key_edit.text().strip() or None
        self.engine.config = _merge_save(_apply)
        QMessageBox.information(self, "Kairos", "MiroFish settings saved.")
        super().accept()


class EmailDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Email Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(460, 320)
        layout = QFormLayout(self)
        layout.setSpacing(12)
        cfg = engine.config.get("email", {})
        self.email_edit = QLineEdit()
        self.email_edit.setText(cfg.get("email", ""))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setText(cfg.get("password", ""))
        self.imap_edit = QLineEdit()
        self.imap_edit.setText(cfg.get("imap_host", "imap.gmail.com"))
        self.imap_port = QLineEdit()
        self.imap_port.setText(str(cfg.get("imap_port", 993)))
        self.smtp_edit = QLineEdit()
        self.smtp_edit.setText(cfg.get("smtp_host", "smtp.gmail.com"))
        self.smtp_port = QLineEdit()
        self.smtp_port.setText(str(cfg.get("smtp_port", 465)))
        layout.addRow("Email:", self.email_edit)
        layout.addRow("Password:", self.password_edit)
        layout.addRow("IMAP Host:", self.imap_edit)
        layout.addRow("IMAP Port:", self.imap_port)
        layout.addRow("SMTP Host:", self.smtp_edit)
        layout.addRow("SMTP Port:", self.smtp_port)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self):
        email_cfg = {
            "email": self.email_edit.text().strip(),
            "password": self.password_edit.text(),
            "imap_host": self.imap_edit.text().strip(),
            "imap_port": int(self.imap_port.text() or 993),
            "smtp_host": self.smtp_edit.text().strip(),
            "smtp_port": int(self.smtp_port.text() or 465),
        }
        self.engine.config = _merge_save(lambda c: c.__setitem__("email", email_cfg))
        self.engine.email = __import__("kairos.email_client", fromlist=["EmailClient"]).EmailClient()
        QMessageBox.information(self, "Kairos", "Email settings saved.")
        super().accept()


class TelegramDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Telegram Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(520, 260)
        layout = QFormLayout(self)
        layout.setSpacing(12)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("Bot token from @BotFather")
        current = engine.config.get("telegram_token") or ""
        self.token_edit.setText(current)
        layout.addRow("Bot Token:", self.token_edit)

        self.allowed_edit = QLineEdit()
        self.allowed_edit.setPlaceholderText("e.g. 123456789, 987654321  (blank = nobody)")
        existing = (engine.config.get("telegram", {}) or {}).get("allowed_user_ids", [])
        self.allowed_edit.setText(", ".join(str(x) for x in existing))
        layout.addRow("Allowed user IDs:", self.allowed_edit)

        self.show_check = QCheckBox("Show token")
        self.show_check.toggled.connect(
            lambda on: self.token_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        layout.addRow("", self.show_check)

        status = "connected" if getattr(engine.telegram, "running", False) else "not running"
        self.status_label = QLabel(f"Telegram bot is currently {status}.")
        self.status_label.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addRow(self.status_label)

        verify_row = QHBoxLayout()
        self.verify_btn = QPushButton("Test Token")
        self.verify_btn.clicked.connect(self._verify)
        self.verify_result = QLabel("")
        self.verify_result.setStyleSheet(f"color: {TEXT_GREY};")
        self.verify_result.setWordWrap(True)
        verify_row.addWidget(self.verify_btn)
        verify_row.addWidget(self.verify_result, 1)
        layout.addRow("", verify_row)

        hint = QLabel("Create a bot with \u0040BotFather in Telegram and paste its token.\n"
                      "Saving restarts the bot with the new token.")
        hint.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _verify(self):
        from kairos.telegram_bot import validate_token_format
        token = self.token_edit.text().strip()
        if not token:
            self.verify_result.setText("Enter a token first.")
            return
        if not validate_token_format(token):
            self.verify_result.setText("Format looks wrong (expected <digits>:<secret>).")
            return
        try:
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                u = data.get("result", {})
                self.verify_result.setText(
                    f"OK \u2014 bot @{u.get('username')} ({u.get('first_name', '')})"
                )
            else:
                self.verify_result.setText(
                    f"Telegram: {data.get('description', 'invalid token (401)')}"
                )
        except Exception as e:
            self.verify_result.setText(f"Could not reach Telegram: {e}")

    def accept(self):
        from kairos.telegram_bot import validate_token_format
        token = self.token_edit.text().strip()
        if token and not validate_token_format(token):
            QMessageBox.warning(
                self, "Kairos",
                "That does not look like a valid bot token.\nExpected format: "
                "<digits>:<secret> (e.g. 123456789:ABCdef...).",
            )
            return
        if not token:
            try:
                import keyring
                keyring.delete_password("kairos", "telegram_token")
            except Exception:
                pass
        self.engine.config = _merge_save(
            lambda c: c.__setitem__("telegram_token", token or None)
        )
        ids = []
        for part in self.allowed_edit.text().replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if not part.lstrip("-").isdigit():
                QMessageBox.warning(self, "Kairos",
                                    f"Ignoring invalid Telegram user ID: {part}")
                continue
            ids.append(int(part))
        self.engine.config = _merge_save(
            lambda c: c.setdefault("telegram", {}).__setitem__("allowed_user_ids", ids)
        )
        try:
            self.engine.restart_telegram()
            self.engine.config = __import__("kairos.config", fromlist=["load_config"]).load_config()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Saved, but the bot did not start:\n{e}")
            super().accept()
            return
        if token:
            # Give the bot thread a moment to authenticate, then report the result.
            import time as _time
            for _ in range(20):
                if getattr(self.engine.telegram, "running", False):
                    break
                if getattr(self.engine.telegram, "last_error", None):
                    break
                _time.sleep(0.25)
            if getattr(self.engine.telegram, "running", False):
                QMessageBox.information(self, "Kairos", "Telegram connected. Bot is running.")
            else:
                err = getattr(self.engine.telegram, "last_error", None) or "unknown error"
                QMessageBox.warning(self, "Kairos",
                                    f"Telegram could not start:\n{err}")
        else:
            QMessageBox.information(self, "Kairos", "Telegram token cleared.")
        super().accept()


class PeripheralDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Peripheral Control (Serial USB)")
        self.setStyleSheet(_dialog_style())
        self.resize(580, 500)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("Serial Devices")
        header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(header)

        top = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Ports")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        top.addWidget(self.refresh_btn)
        top.addStretch()
        layout.addLayout(top)

        self.ports_list = QListWidget()
        layout.addWidget(self.ports_list)

        form = QFormLayout()
        form.setSpacing(10)
        self.baud_edit = QLineEdit()
        self.baud_edit.setText(str(self.engine.config["peripherals"]["default_baud"]))
        form.addRow("Baud rate:", self.baud_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_port)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close_port)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Send data:"))
        self.send_edit = QLineEdit()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_data)
        send_row = QHBoxLayout()
        send_row.addWidget(self.send_edit)
        send_row.addWidget(self.send_btn)
        layout.addLayout(send_row)

        layout.addWidget(QLabel("Received data:"))
        self.read_display = QTextEdit()
        self.read_display.setReadOnly(True)
        self.read_btn = QPushButton("Read")
        self.read_btn.clicked.connect(self.read_data)
        layout.addWidget(self.read_display)
        layout.addWidget(self.read_btn)

        self.refresh_ports()

    def _selected_port(self):
        item = self.ports_list.currentItem()
        if not item:
            QMessageBox.information(self, "Kairos", "Select a port first.")
            return None
        return item.text().split(" ")[0]

    def refresh_ports(self):
        self.ports_list.clear()
        for p in self.engine.list_ports():
            state = "OPEN" if p.get("open") else "closed"
            self.ports_list.addItem(f"{p['device']}    [{state}]    {p['description']}")

    def open_port(self):
        device = self._selected_port()
        if not device:
            return
        try:
            baud = int(self.baud_edit.text() or self.engine.config["peripherals"]["default_baud"])
            self.engine.open_port(device, baud)
            self.read_display.append(f"[opened {device} @ {baud}]")
            self.refresh_ports()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Open failed: {e}")

    def close_port(self):
        device = self._selected_port()
        if not device:
            return
        self.engine.close_port(device)
        self.read_display.append(f"[closed {device}]")
        self.refresh_ports()

    def send_data(self):
        device = self._selected_port()
        if not device:
            return
        text = self.send_edit.text()
        if not text:
            return
        try:
            self.engine.write_port(device, text + "\n")
            self.read_display.append(f"> {text}")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Write failed: {e}")

    def read_data(self):
        device = self._selected_port()
        if not device:
            return
        try:
            data = self.engine.read_port(device)
            if data:
                self.read_display.append(data)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Read failed: {e}")


class SkillDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Skills")
        self.setStyleSheet(_dialog_style())
        self.resize(820, 560)
        layout = QHBoxLayout(self)

        # Left: skill tree
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Installed Skills"))
        left_layout.addWidget(self._build_new_btn())
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Skill", "Description"])
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(self._on_item_run)
        left_layout.addWidget(self.tree)
        left_layout.addWidget(self._build_left_buttons())
        layout.addWidget(left, 1)

        # Right: code editor
        right = QWidget()
        right_layout = QVBoxLayout(right)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Source Code"))
        header_row.addStretch()
        self.current_file_label = QLabel("")
        header_row.addWidget(self.current_file_label)
        right_layout.addLayout(header_row)

        self.code_edit = QTextEdit()
        self.code_edit.setPlaceholderText("Select a skill to view/edit its code, or click 'New Skill'.")
        monospace = QFont("Consolas", 10)
        self.code_edit.setFont(monospace)
        right_layout.addWidget(self.code_edit, 1)

        self.save_btn = QPushButton("Save & Reload")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_code)
        self.test_btn = QPushButton("Run Skill")
        self.test_btn.setEnabled(False)
        self.test_btn.clicked.connect(self._run_skill)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.test_btn)
        right_layout.addLayout(btn_row)

        layout.addWidget(right, 2)

        self.refresh_tree()

    def _build_new_btn(self):
        btn = QPushButton("+ New Skill")
        btn.clicked.connect(self._new_skill)
        return btn

    def _build_left_buttons(self):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 6, 0, 0)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_tree)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        self.delete_btn.clicked.connect(self._delete_skill)
        layout.addWidget(refresh)
        layout.addWidget(self.delete_btn)
        return w

    def refresh_tree(self):
        self.tree.clear()
        for skill in self.engine.list_skills():
            item = QTreeWidgetItem([skill["name"], skill["description"]])
            item.setData(0, Qt.UserRole, skill["name"])
            self.tree.addTopLevelItem(item)
        self.current_file_label.clear()

    def _on_select(self):
        item = self.tree.currentItem()
        if not item:
            return
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        code = self.engine.skills.read_source(name)
        self.code_edit.setPlainText(code)
        self.current_file_label.setText(f"{name}.py")
        self.save_btn.setEnabled(True)
        self.test_btn.setEnabled(True)
        self._current_name = name

    def _on_item_run(self, item, column):
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        self._on_select()
        self._run_skill()

    def _new_skill(self):
        name, ok = self._input("New Skill", "Skill name (lowercase, underscores):")
        if not ok or not name.strip():
            return
        name = name.strip()
        description, ok2 = self._input("New Skill", "Description:")
        if not ok2:
            return
        description = description.strip() or name
        self.code_edit.setPlainText("Generating skill code via LLM ...")
        self._current_name = name
        self.current_file_label.setText(f"{name}.py  (generating...)")
        self.save_btn.setEnabled(False)
        self.test_btn.setEnabled(False)
        worker = SkillGenWorker(self.engine, name, description)
        worker.finished.connect(self._on_generated)
        worker.start()
        self._gen_worker = worker

    def _on_generated(self, code: str):
        self.code_edit.setPlainText(code)
        self.current_file_label.setText(f"{getattr(self, '_current_name', '')}.py  (new)")
        self.save_btn.setEnabled(True)
        self.test_btn.setEnabled(True)

    def _save_code(self):
        name = getattr(self, "_current_name", None)
        if not name:
            return
        code = self.code_edit.toPlainText()
        try:
            self.engine.skills.save_source(name, code)
            self.refresh_tree()
            self.refresh_status_bar()
            QMessageBox.information(self, "Kairos", f"Skill '{name}' saved.")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Save failed: {e}")

    def _run_skill(self):
        name = getattr(self, "_current_name", None)
        if not name:
            return
        try:
            result = self.engine.run_skill(name)
            QMessageBox.information(self, "Kairos", str(result))
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Run failed: {e}")

    def _delete_skill(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "Kairos", "Select a skill to delete.")
            return
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        confirm = QMessageBox.question(
            self, "Delete Skill",
            f"Delete skill '{name}' permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.engine.delete_skill(name)
            self.code_edit.clear()
            self.current_file_label.clear()
            self.save_btn.setEnabled(False)
            self.test_btn.setEnabled(False)
            self.refresh_tree()
            self.refresh_status_bar()
            QMessageBox.information(self, "Kairos", f"Skill '{name}' deleted.")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Delete failed: {e}")

    def _input(self, title, label, default=""):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, label, text=default)

    def refresh_status_bar(self):
        parent = self.parent()
        if isinstance(parent, KairosGUI):
            parent.refresh_status_bar()


class CharacterDialog(QDialog):
    """Manage agent characters: view, create, edit, duplicate, delete, activate."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Agent Characters")
        self.setStyleSheet(_dialog_style())
        self.resize(900, 640)
        self._current_id = None
        self.build_ui()
        self.refresh_list()

    def build_ui(self):
        layout = QHBoxLayout(self)

        # --- Left: character list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Characters"))
        self.char_list = QListWidget()
        self.char_list.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.char_list, 1)

        row = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new)
        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._duplicate)
        self.active_btn = QPushButton("Set Active")
        self.active_btn.setStyleSheet(
            f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;"
        )
        self.active_btn.clicked.connect(self._set_active)
        row.addWidget(new_btn)
        row.addWidget(dup_btn)
        row.addWidget(self.active_btn)
        left_layout.addLayout(row)
        layout.addWidget(left, 1)

        # --- Right: profile editor ---
        right = QWidget()
        right_layout = QVBoxLayout(right)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.icon_edit = QLineEdit()
        self.icon_edit.setMaxLength(4)
        self.desc_edit = QLineEdit()
        form.addRow("Name:", self.name_edit)
        form.addRow("Icon:", self.icon_edit)
        form.addRow("Description:", self.desc_edit)
        right_layout.addLayout(form)

        self.builtin_label = QLabel("")
        self.builtin_label.setStyleSheet(f"color: {TEXT_GREY}; font-style: italic;")
        self.builtin_label.setWordWrap(True)
        right_layout.addWidget(self.builtin_label)

        right_layout.addWidget(QLabel("System prompt:"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.prompt_edit, 3)

        right_layout.addWidget(QLabel("Disclaimer (shown on switch, optional):"))
        self.disclaimer_edit = QLineEdit()
        right_layout.addWidget(self.disclaimer_edit)

        self.all_caps_check = QCheckBox("All tools (no restriction)")
        self.all_caps_check.toggled.connect(self._toggle_all_caps)
        right_layout.addWidget(self.all_caps_check)

        cap_box = QGroupBox("Allowed tools")
        cap_grid = QGridLayout(cap_box)
        self.cap_checks = {}
        for i, cap in enumerate(ALL_CAPABILITIES):
            chk = QCheckBox(CAPABILITY_LABELS.get(cap, cap))
            self.cap_checks[cap] = chk
            cap_grid.addWidget(chk, i // 2, i % 2)
        right_layout.addWidget(cap_box)

        right_layout.addWidget(QLabel("Allowed skills (comma-separated; blank = all):"))
        self.skills_edit = QLineEdit()
        right_layout.addWidget(self.skills_edit)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        self.delete_btn.clicked.connect(self._delete)
        self.reset_btn = QPushButton("Restore Default")
        self.reset_btn.clicked.connect(self._restore)
        self.restore_all_btn = QPushButton("Restore All Defaults")
        self.restore_all_btn.clicked.connect(self._restore_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.restore_all_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        right_layout.addLayout(btn_row)
        layout.addWidget(right, 2)

    # ---- list ----
    def refresh_list(self):
        self.char_list.blockSignals(True)
        self.char_list.clear()
        active_id = self.engine.active_character
        for prof in self.engine.list_characters():
            marker = "\u25CF " if prof["id"] == active_id else "   "
            tag = "  [built-in]" if prof.get("builtin") else ""
            item = QListWidgetItem(f"{marker}{prof.get('icon', '')} {prof['name']}{tag}")
            item.setData(Qt.UserRole, prof["id"])
            if prof["id"] == active_id:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.char_list.addItem(item)
        self.char_list.blockSignals(False)
        # Select active
        for i in range(self.char_list.count()):
            if self.char_list.item(i).data(Qt.UserRole) == active_id:
                self.char_list.setCurrentRow(i)
                break
        if self.char_list.count() and self.char_list.currentRow() < 0:
            self.char_list.setCurrentRow(0)

    def _on_select(self, current, previous=None):
        if not current:
            return
        cid = current.data(Qt.UserRole)
        prof = self.engine.characters.get(cid)
        if not prof:
            return
        self._current_id = cid
        self._load(prof)

    def _load(self, prof):
        builtin = bool(prof.get("builtin"))
        self.name_edit.setText(prof.get("name", ""))
        self.icon_edit.setText(prof.get("icon", "") or "")
        self.desc_edit.setText(prof.get("description", "") or "")
        self.prompt_edit.setPlainText(prof.get("system_prompt", "") or "")
        self.disclaimer_edit.setText(prof.get("disclaimer") or "")

        caps = prof.get("capabilities")
        self.all_caps_check.setChecked(caps is None)
        for cap, chk in self.cap_checks.items():
            chk.setChecked(caps is None or cap in caps)
        self._toggle_all_caps(self.all_caps_check.isChecked())

        skills = prof.get("skills")
        self.skills_edit.setText("" if skills is None else ", ".join(skills))

        if builtin:
            self.builtin_label.setText(
                "Built-in character (read-only). Use Duplicate to create an "
                "editable copy."
            )
        else:
            self.builtin_label.setText("Custom character.")

        for w in (self.name_edit, self.icon_edit, self.desc_edit, self.prompt_edit,
                  self.disclaimer_edit, self.all_caps_check, self.skills_edit):
            w.setEnabled(not builtin)
        for chk in self.cap_checks.values():
            chk.setEnabled(not builtin and not self.all_caps_check.isChecked())
        self.save_btn.setEnabled(not builtin)
        self.delete_btn.setEnabled(not builtin)
        self.reset_btn.setEnabled(builtin)

    def _toggle_all_caps(self, checked):
        for chk in self.cap_checks.values():
            if checked:
                chk.setChecked(True)
            chk.setEnabled(not checked and self.name_edit.isEnabled())

    def _collect(self):
        caps = None
        if not self.all_caps_check.isChecked():
            caps = [c for c, chk in self.cap_checks.items() if chk.isChecked()]
        skills_text = self.skills_edit.text().strip()
        skills = None
        if skills_text:
            skills = [s.strip() for s in skills_text.split(",") if s.strip()]
        return {
            "id": self._current_id,
            "name": self.name_edit.text().strip(),
            "icon": self.icon_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
            "system_prompt": self.prompt_edit.toPlainText().strip(),
            "disclaimer": self.disclaimer_edit.text().strip() or None,
            "capabilities": caps,
            "skills": skills,
        }

    # ---- actions ----
    def _new(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Character", "Character name:")
        if not ok or not name.strip():
            return
        description, ok2 = QInputDialog.getText(
            self, "New Character", "Short description (optional):"
        )
        if not ok2:
            description = ""
        try:
            prof = self.engine.create_character(name.strip(), description.strip())
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Create failed: {e}")
            return
        self.refresh_list()
        self._select_id(prof["id"])

    def _duplicate(self):
        if not self._current_id:
            return
        try:
            prof = self.engine.duplicate_character(self._current_id)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Duplicate failed: {e}")
            return
        self.refresh_list()
        self._select_id(prof["id"])

    def _select_id(self, cid):
        for i in range(self.char_list.count()):
            if self.char_list.item(i).data(Qt.UserRole) == cid:
                self.char_list.setCurrentRow(i)
                return

    def _save(self):
        if not self._current_id:
            return
        profile = self._collect()
        if not profile["name"] or not profile["system_prompt"]:
            QMessageBox.warning(self, "Kairos", "Name and system prompt are required.")
            return
        try:
            self.engine.save_character(profile)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Save failed: {e}")
            return
        self.refresh_list()
        self._select_id(profile["id"])

    def _delete(self):
        if not self._current_id:
            return
        prof = self.engine.characters.get(self._current_id)
        if not prof or prof.get("builtin"):
            return
        confirm = QMessageBox.question(
            self, "Delete Character",
            f"Delete character '{prof['name']}' permanently?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.engine.delete_character(self._current_id)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Delete failed: {e}")
            return
        self.refresh_list()

    def _set_active(self):
        if not self._current_id:
            return
        try:
            self.engine.set_character(self._current_id)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Activate failed: {e}")
            return
        self.refresh_list()

    def _restore(self):
        if not self._current_id:
            return
        confirm = QMessageBox.question(
            self, "Restore Default",
            "Overwrite this built-in character with the packaged default?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.engine.reset_character(self._current_id)
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Restore failed: {e}")
            return
        self.refresh_list()
        self._select_id(self._current_id)

    def _restore_all(self):
        confirm = QMessageBox.question(
            self, "Restore All Defaults",
            "Reset every built-in character to its packaged default?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.engine.restore_default_characters()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Restore failed: {e}")
            return
        self.refresh_list()
        self._select_id(self._current_id)


class PendingDialog(QDialog):
    """Review, edit, approve or reject proposed graph knowledge."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Pending Knowledge")
        self.setStyleSheet(_dialog_style())
        self.resize(820, 560)
        layout = QHBoxLayout(self)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Proposed items (not stored until approved)"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, slot in (("Approve", self._approve), ("Reject", self._reject)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        ll.addLayout(row)
        row2 = QHBoxLayout()
        all_btn = QPushButton("Approve All")
        all_btn.clicked.connect(self._approve_all)
        rej_btn = QPushButton("Reject All")
        rej_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        rej_btn.clicked.connect(self._reject_all)
        row2.addWidget(all_btn)
        row2.addWidget(rej_btn)
        ll.addLayout(row2)
        layout.addWidget(left, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Edit payload (JSON) before approving:"))
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 9))
        rl.addWidget(self.editor, 1)
        row3 = QHBoxLayout()
        save_btn = QPushButton("Save Edits")
        save_btn.clicked.connect(self._save_edits)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row3.addWidget(save_btn)
        row3.addStretch()
        row3.addWidget(close_btn)
        rl.addLayout(row3)
        layout.addWidget(right, 2)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for item in self.engine.list_pending_graph():
            p = item.get("payload", {})
            n_e = len(p.get("entities", []))
            n_r = len(p.get("relations", []))
            text = f"[{item['source']}] {n_e} entities, {n_r} relations"
            qitem = QListWidgetItem(text)
            qitem.setData(Qt.UserRole, item["id"])
            self.list.addItem(qitem)
        self._on_select(self.list.currentItem())

    def _on_select(self, current, previous=None):
        import json
        if not current:
            self.editor.clear()
            return
        item = self.engine.get_pending_graph(current.data(Qt.UserRole))
        if item:
            self.editor.setPlainText(json.dumps(item.get("payload", {}), indent=2, ensure_ascii=False))

    def _current_id(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _save_edits(self):
        import json
        pid = self._current_id()
        if not pid:
            return
        try:
            data = json.loads(self.editor.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Invalid JSON: {e}")
            return
        self.engine.update_pending_graph(pid, data)

    def _approve(self):
        pid = self._current_id()
        if not pid:
            return
        self._save_edits()
        if self.engine.approve_pending_graph(pid):
            self.refresh()

    def _reject(self):
        pid = self._current_id()
        if not pid:
            return
        self.engine.reject_pending_graph(pid)
        self.refresh()

    def _approve_all(self):
        self._save_edits()
        self.engine.approve_all_pending_graph()
        self.refresh()

    def _reject_all(self):
        self.engine.reject_all_pending_graph()
        self.refresh()


class GraphDialog(QDialog):
    """Search, edit and delete long-term knowledge graph data."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Knowledge Graph")
        self.setStyleSheet(_dialog_style())
        self.resize(860, 600)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search entities, relations and notes...")
        self.search_edit.returnPressed.connect(self.search)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search)
        refresh_btn = QPushButton("List All")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.search_edit, 1)
        top.addWidget(search_btn)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Type", "Name", "Detail"])
        self.tree.setColumnWidth(0, 90)
        self.tree.setColumnWidth(1, 220)
        layout.addWidget(self.tree, 1)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(self.stats_label)

        row = QHBoxLayout()
        edit_btn = QPushButton("Edit Entity")
        edit_btn.clicked.connect(self.edit_entity)
        del_btn = QPushButton("Delete Selected")
        del_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        del_btn.clicked.connect(self.delete_selected)
        pending_btn = QPushButton("Pending Review")
        pending_btn.clicked.connect(lambda: PendingDialog(self.engine, self).exec())
        repair_btn = QPushButton("Repair / Rebuild")
        repair_btn.setToolTip("Quarantine a corrupt WAL (backup kept) and re-ingest "
                              "retained memories + documents from knowledge.db")
        repair_btn.clicked.connect(self.repair_graph)
        clear_btn = QPushButton("Clear All")
        clear_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        clear_btn.clicked.connect(self.clear_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(edit_btn)
        row.addWidget(del_btn)
        row.addWidget(pending_btn)
        row.addWidget(repair_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._update_stats()
        self.refresh()

    def _update_stats(self):
        try:
            s = self.engine.graph_stats()
            self.stats_label.setText(
                f"Entities: {s.get('entities', 0)}  |  Relations: {s.get('relations', 0)}  |  "
                f"Memories: {s.get('memories', 0)}  |  Vector: {s.get('vector')}  |  {s.get('db_path','')}"
            )
        except Exception:
            self.stats_label.setText("Graph memory unavailable.")

    def refresh(self):
        self.tree.clear()
        for e in self.engine.graph_list_entities():
            item = QTreeWidgetItem(["entity", e["name"], f"{e['kind']} | mentions={e.get('mentions',0)} | {e.get('summary','')}"])
            item.setData(0, Qt.UserRole, ("entity", e["id"], None, None))
            self.tree.addTopLevelItem(item)
        for m in self.engine.graph_list_memories():
            item = QTreeWidgetItem(["memory", (m.get("kind") or "memory"),
                                    (m.get("text") or "")[:200]])
            item.setData(0, Qt.UserRole, ("memory", m.get("id"), None, None))
            self.tree.addTopLevelItem(item)

    def search(self):
        q = self.search_edit.text().strip()
        if not q:
            self.refresh()
            return
        self.tree.clear()
        res = self.engine.graph_search(q, limit=25)
        for e in res.get("entities", []):
            item = QTreeWidgetItem(["entity", e["name"], f"{e['kind']} | {e.get('summary','')}"])
            item.setData(0, Qt.UserRole, ("entity", e["id"], None, None))
            for rel in e.get("relations", []):
                child = QTreeWidgetItem(["relation", rel["predicate"], rel["target"]])
                # store subject/object loosely; deletion needs ids - use predicate + target name
                child.setData(0, Qt.UserRole, ("relation", e["id"], rel["predicate"], rel["target"]))
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
        for m in res.get("memories", []):
            item = QTreeWidgetItem(["memory", (m.get("kind") or "note"), (m.get("text") or "")[:200]])
            item.setData(0, Qt.UserRole, ("memory", m.get("id") or m.get("text"), None, None))
            self.tree.addTopLevelItem(item)

    def _selected(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def edit_entity(self):
        sel = self._selected()
        if not sel or sel[0] != "entity":
            QMessageBox.information(self, "Kairos", "Select an entity first.")
            return
        from PySide6.QtWidgets import QInputDialog
        eid = sel[1]
        current = None
        for e in self.engine.graph_list_entities():
            if e["id"] == eid:
                current = e
                break
        name, ok = QInputDialog.getText(self, "Edit Entity", "Name:", text=(current or {}).get("name", ""))
        if not ok:
            return
        kind, ok2 = QInputDialog.getText(self, "Edit Entity", "Kind:", text=(current or {}).get("kind", ""))
        if not ok2:
            return
        summary, ok3 = QInputDialog.getText(self, "Edit Entity", "Summary:", text=(current or {}).get("summary", ""))
        if not ok3:
            return
        self.engine.graph_update_entity(eid, name=name.strip(), kind=kind.strip(), summary=summary.strip())
        self._update_stats()
        self.refresh()

    def delete_selected(self):
        sel = self._selected()
        if not sel:
            QMessageBox.information(self, "Kairos", "Select an item to delete.")
            return
        kind = sel[0]
        if kind == "entity":
            if QMessageBox.question(self, "Delete", f"Delete entity '{sel[1]}' and its links?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self.engine.graph_delete_entity(sel[1])
        elif kind == "memory":
            if QMessageBox.question(self, "Delete", "Delete this memory note from the graph?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self.engine.graph_delete_memory(sel[1])
        elif kind == "relation":
            QMessageBox.information(self, "Kairos", "Select the parent entity and use Clear All, or edit via the graph.")
            return
        self._update_stats()
        self.refresh()

    def clear_all(self):
        if QMessageBox.question(self, "Clear Graph", "Delete ALL graph knowledge permanently?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.engine.graph_clear()
        self._update_stats()
        self.refresh()

    def repair_graph(self):
        if QMessageBox.question(
                self, "Repair Knowledge Graph",
                "Repair the knowledge graph?\n\n"
                "This backs up the database file, quarantines a corrupt WAL (nothing "
                "is deleted), reopens the graph, and re-ingests retained memories and "
                "document summaries. Source data in knowledge.db is never touched.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self.stats_label.setText("Repairing / rebuilding\u2026")
        self.worker = GraphRepairWorker(self.engine)
        self.worker.finished.connect(self._on_repaired)
        self.worker.start()

    def _on_repaired(self, result):
        self._update_stats()
        self.refresh()
        QMessageBox.information(
            self, "Kairos",
            f"Graph recovered: {result.get('recovered')}\n"
            f"Re-ingested from knowledge.db: {result.get('reingested', 0)} item(s)"
            + (f"\nError: {result.get('error')}" if result.get("error") else ""))


class MyCallSignDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("My Call Sign")
        self.setStyleSheet(_dialog_style())
        self.resize(580, 260)
        layout = QVBoxLayout(self)
        collab = getattr(engine, "collab", None)
        if not collab:
            layout.addWidget(QLabel("Collaboration is not enabled or failed to start."))
            btn = QPushButton("Close"); btn.clicked.connect(self.accept)
            layout.addWidget(btn)
            return
        cfg = engine.config.get("collaboration", {})
        form = QFormLayout()
        self.transport = QComboBox()
        self.transport.addItems(["direct", "ts", "public", "ngrok"])
        self.transport.setCurrentText(cfg.get("transport", "direct"))
        self.port = QLineEdit(str(cfg.get("listen_port", 7777)))
        form.addRow("Transport:", self.transport)
        form.addRow("Port:", self.port)
        layout.addLayout(form)
        apply_btn = QPushButton("Start / Refresh Listener")
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)
        layout.addWidget(QLabel("Share this call sign with your peer:"))
        self.cs = QLineEdit(self._callsign())
        self.cs.setReadOnly(True)
        layout.addWidget(self.cs)
        row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.cs.text()))
        qr_btn = QPushButton("Show QR")
        qr_btn.clicked.connect(self._show_qr)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn); row.addWidget(qr_btn); row.addStretch(); row.addWidget(close_btn)
        layout.addLayout(row)

    def _callsign(self):
        try:
            return self.engine.collab.my_callsign()
        except Exception as e:
            return f"(error: {e})"

    def _apply(self):
        try:
            self.engine.collab.start_listener(self.transport.currentText(),
                                              int(self.port.text() or 7777))
            from kairos.config import load_config, save_config
            c = load_config()
            col = c.setdefault("collaboration", {})
            col["transport"] = self.transport.currentText()
            col["listen_port"] = int(self.port.text() or 7777)
            save_config(c)
            self.engine.config = load_config()
            self.cs.setText(self._callsign())
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Could not start listener:\n{e}")

    def _show_qr(self):
        from kairos.collab import callsign as csmod
        png = csmod.qr_png(self.cs.text())
        if not png:
            QMessageBox.information(self, "Kairos", "QR code not available.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Call Sign QR")
        v = QVBoxLayout(dlg)
        lbl = QLabel()
        pix = QPixmap()
        pix.loadFromData(png)
        lbl.setPixmap(pix)
        v.addWidget(lbl)
        dlg.exec()


class ConnectDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Connect to a Peer")
        self.setStyleSheet(_dialog_style())
        self.resize(600, 180)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Paste your peer's call sign:"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("K1!LABEL!direct!host!port!FP32!CK")
        layout.addWidget(self.edit)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._connect)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.connect_btn); row.addStretch(); row.addWidget(close_btn)
        layout.addLayout(row)
        self._worker = None

    def _connect(self):
        cs = self.edit.text().strip()
        if not cs:
            return
        if not getattr(self.engine, "collab", None):
            QMessageBox.warning(self, "Kairos", "Collaboration is not enabled.")
            return
        self.connect_btn.setEnabled(False)
        self.status.setText("Connecting (waiting for peer approval) ...")
        self._worker = ConnectWorker(self.engine, cs)
        self._worker.ok.connect(self._ok)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _ok(self, sess):
        self.connect_btn.setEnabled(True)
        label = sess.remote_label or sess.remote_fp[:12]
        # Enforce an explicit out-of-band SAS check before trusting the peer.
        try:
            from kairos.collab import identity as _id
            import asyncio as _asyncio
            sas = _id.sas(self.engine.collab.identity.fp_hex, sess.remote_fp)
            keep = QMessageBox.question(
                self, "Verify Safety Code",
                f"Connected to {label}.\n\nSafety code (SAS): {sas}\n\n"
                "Compare this with your peer over another channel (e.g. voice). "
                "Keep the connection?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if keep != QMessageBox.Yes:
                try:
                    _asyncio.run_coroutine_threadsafe(sess.close(), self.engine.collab._loop)
                except Exception:
                    pass
                self.status.setText("Rejected (SAS not verified).")
                return
        except Exception:
            pass
        self.status.setText("Connected.")
        QMessageBox.information(self, "Kairos", f"Connected to {label}.")
        self.accept()

    def _fail(self, msg):
        self.connect_btn.setEnabled(True)
        self.status.setText(f"Failed: {msg}")
        QMessageBox.warning(self, "Kairos", msg)


class IncomingRequestDialog(QDialog):
    def __init__(self, req, parent=None):
        super().__init__(parent)
        self.req = req
        self.accepted = False
        self.setWindowTitle("Incoming Collaboration Request")
        self.setStyleSheet(_dialog_style())
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{html.escape(req.label or 'Unknown peer')}</b> wants to connect."))
        info = QLabel(
            f"Fingerprint: {req.remote_fp[:32]}...\n"
            f"Safety code (SAS): <b>{req.sas}</b>"
        )
        info.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(info)
        note = QLabel("Verify this SAS with your peer over another channel "
                      "(phone/voice) before accepting.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(note)
        row = QHBoxLayout()
        accept_btn = QPushButton("Accept")
        accept_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        accept_btn.clicked.connect(self._accept)
        reject_btn = QPushButton("Reject")
        reject_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        reject_btn.clicked.connect(self._reject)
        row.addWidget(accept_btn); row.addWidget(reject_btn)
        layout.addLayout(row)

    def _accept(self):
        self.accepted = True
        self.accept()

    def _reject(self):
        self.accepted = False
        self.reject()


class CollaborationWindow(QDialog):
    sig_project = Signal()
    sig_remote_video = Signal(bytes)

    def __init__(self, engine, session, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.session = session
        self._proj = None
        self._applying = False
        self._audio = None
        self._camera = None
        self._cap_session = None
        self._video_sink = None
        self.setWindowTitle(f"Collaboration - {session.remote_label or session.remote_fp[:12]}")
        self.setStyleSheet(_dialog_style())
        self.resize(780, 620)
        layout = QVBoxLayout(self)
        header = QLabel(f"Connected to <b>{html.escape(session.remote_label or session.remote_fp[:12])}</b>"
                        f"  ·  FP {session.remote_fp[:16]}…")
        header.setStyleSheet(f"color: {GREEN};")
        layout.addWidget(header)

        tabs = QTabWidget()

        chat_tab = QWidget()
        cl = QVBoxLayout(chat_tab)
        self.view = QTextBrowser()
        self.view.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        cl.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.input.returnPressed.connect(self._send)
        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        send_btn.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)
        cl.addLayout(row)
        tabs.addTab(chat_tab, "Chat")

        proj_tab = QWidget()
        pl = QVBoxLayout(proj_tab)
        pl.addWidget(QLabel("Shared project notes (CRDT-synced with your peer):"))
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Collaborate on notes here — both sides see changes.")
        self.notes.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        pl.addWidget(self.notes, 1)
        tabs.addTab(proj_tab, "Project")

        call_tab = QWidget()
        vl = QVBoxLayout(call_tab)
        ctrl = QHBoxLayout()
        self.voice_btn = QPushButton("Start Voice")
        self.voice_btn.setCheckable(True)
        self.voice_btn.toggled.connect(self._toggle_voice)
        self.mute_btn = QPushButton("Mute Speaker")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._toggle_mute)
        self.video_btn = QPushButton("Start Camera")
        self.video_btn.setCheckable(True)
        self.video_btn.toggled.connect(self._toggle_video)
        ctrl.addWidget(self.voice_btn)
        ctrl.addWidget(self.mute_btn)
        ctrl.addWidget(self.video_btn)
        ctrl.addStretch()
        vl.addLayout(ctrl)
        self.local_video = QLabel("Local camera (off)")
        self.local_video.setAlignment(Qt.AlignCenter)
        self.local_video.setMinimumHeight(160)
        self.local_video.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT_GREY}; border: 1px solid {BORDER};")
        self.remote_video = QLabel("Remote camera (off)")
        self.remote_video.setAlignment(Qt.AlignCenter)
        self.remote_video.setMinimumHeight(160)
        self.remote_video.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT_GREY}; border: 1px solid {BORDER};")
        vids = QHBoxLayout()
        vids.addWidget(self.local_video, 1)
        vids.addWidget(self.remote_video, 1)
        vl.addLayout(vids, 1)
        self.call_status = QLabel("")
        self.call_status.setStyleSheet(f"color: {TEXT_GREY};")
        vl.addWidget(self.call_status)
        tabs.addTab(call_tab, "Call")

        layout.addWidget(tabs, 1)
        self.sig_project.connect(self._refresh_project)
        self.sig_remote_video.connect(self._show_remote_video)
        self._bind_project()

    # ---- voice ----
    def _toggle_voice(self, on):
        if on:
            try:
                from kairos.collab.media import AudioStream
                self._audio = AudioStream(
                    on_frame=lambda pcm: self.engine.collab.send_audio(self.session.remote_fp, pcm))
                self._audio.start()
                self.voice_btn.setText("Stop Voice")
                if getattr(self.engine, "on_collab_audio", None) is None:
                    self.engine.on_collab_audio = (
                        lambda s, d: self._audio and self._audio.feed(d))
                self.call_status.setText("Voice active (16 kHz PCM over the encrypted link).")
            except Exception as e:
                self.call_status.setText(f"Voice failed: {e}")
                self.voice_btn.setChecked(False)
        else:
            if self._audio:
                self._audio.stop()
                self._audio = None
            self.voice_btn.setText("Start Voice")
            self.call_status.setText("Voice stopped.")

    def _toggle_mute(self, on):
        if self._audio:
            self._audio.speaker_muted = on
        self.mute_btn.setText("Unmute Speaker" if on else "Mute Speaker")

    # ---- video ----
    def _toggle_video(self, on):
        if not _MULTIMEDIA:
            self.call_status.setText("QtMultimedia not available; video disabled.")
            self.video_btn.setChecked(False)
            return
        if on:
            try:
                self._camera = QCamera()
                self._cap_session = QMediaCaptureSession()
                self._video_sink = QVideoSink()
                self._cap_session.setCamera(self._camera)
                self._cap_session.setVideoOutput(self._video_sink)
                self._video_sink.videoFrameChanged.connect(self._on_video_frame)
                self._camera.start()
                self.video_btn.setText("Stop Camera")
                self.call_status.setText("Camera active (JPEG frames to peer).")
            except Exception as e:
                self.call_status.setText(f"Camera failed: {e}")
                self.video_btn.setChecked(False)
        else:
            try:
                if self._camera:
                    self._camera.stop()
            except Exception:
                pass
            self._camera = None
            self.video_btn.setText("Start Camera")
            self.local_video.setText("Local camera (off)")
            self.call_status.setText("Camera stopped.")

    def _on_video_frame(self, frame):
        try:
            img = frame.toImage()
            if img.isNull():
                return
            small = img.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap.fromImage(small)
            self.local_video.setPixmap(pix)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            small.save(buf, "JPG", 55)
            buf.close()
            self.engine.collab.send_video(self.session.remote_fp, bytes(ba))
        except Exception:
            pass

    def _show_remote_video(self, data):
        try:
            pix = QPixmap()
            if pix.loadFromData(bytes(data)):
                self.remote_video.setPixmap(pix)
        except Exception:
            pass

    def _bind_project(self):
        collab = getattr(self.engine, "collab", None)
        if not collab:
            return
        proj = collab.get_project(self.session.remote_fp)
        self._proj = proj
        if proj:
            self._applying = True
            try:
                self.notes.setPlainText(proj.get_notes())
            finally:
                self._applying = False
            proj.on_refresh = lambda: self.sig_project.emit()
            self.notes.textChanged.connect(self._on_notes_edited)

    def _on_notes_edited(self):
        if self._applying or not self._proj:
            return
        self._proj.set_notes(self.notes.toPlainText())

    def _refresh_project(self):
        if not self._proj:
            return
        self._applying = True
        try:
            self.notes.setPlainText(self._proj.get_notes())
        finally:
            self._applying = False

    def append_peer(self, text):
        self._append("peer", text)

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        try:
            self.engine.collab.send_chat(self.session.remote_fp, text)
            self._append("me", text)
        except Exception as e:
            self._append("system", f"send failed: {e}")
        self.input.clear()

    def _append(self, who, text):
        color = {"me": "#58a6ff", "peer": GREEN, "system": TEXT_GREY}.get(who, TEXT)
        label = {"me": "You", "peer": "Peer", "system": "system"}.get(who, who)
        self.view.append(f'<span style="color:{color}"><b>{label}:</b> {html.escape(text)}</span>')


class SendFileDialog(QDialog):
    def __init__(self, engine, sessions, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.sessions = sessions
        self.setWindowTitle("Send File to Peer")
        self.setStyleSheet(_dialog_style())
        self.resize(560, 200)
        layout = QFormLayout(self)
        layout.setSpacing(10)
        self.peer = QComboBox()
        for s in sessions:
            self.peer.addItem(s.remote_label or s.remote_fp[:12], s.remote_fp)
        layout.addRow("Peer:", self.peer)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        layout.addRow("File:", path_row)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addRow(self.status)
        row = QHBoxLayout()
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.send_btn.clicked.connect(self._send)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.send_btn); row.addStretch(); row.addWidget(close_btn)
        layout.addRow(row)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file to send")
        if path:
            self.path_edit.setText(path)

    def _send(self):
        path = self.path_edit.text().strip()
        if not path:
            return
        fp = self.peer.currentData()
        self.send_btn.setEnabled(False)
        self.status.setText("Sending (waiting for peer acceptance)…")
        self._worker = SendFileWorker(self.engine, fp, path)
        self._worker.ok.connect(self._ok)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _ok(self, info):
        self.send_btn.setEnabled(True)
        self.status.setText(f"Sent: {info.get('name')} ({info.get('size')} bytes)")

    def _fail(self, msg):
        self.send_btn.setEnabled(True)
        self.status.setText(f"Failed: {msg}")


class FederatedDialog(QDialog):
    def __init__(self, engine, sessions, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.sessions = sessions
        self.setWindowTitle("Federated LLM Task")
        self.setStyleSheet(_dialog_style())
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        top = QFormLayout()
        self.peer = QComboBox()
        for s in sessions:
            self.peer.addItem(s.remote_label or s.remote_fp[:12], s.remote_fp)
        top.addRow("Peer:", self.peer)
        self.ask_local = QCheckBox("Also ask my own LLM and show both")
        self.ask_local.setChecked(True)
        top.addRow(self.ask_local)
        layout.addLayout(top)
        layout.addWidget(QLabel("Prompt:"))
        self.prompt = QTextEdit()
        self.prompt.setFixedHeight(90)
        layout.addWidget(self.prompt)
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.ask_btn.clicked.connect(self._ask)
        layout.addWidget(self.ask_btn)
        self.result = QTextBrowser()
        self.result.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        layout.addWidget(self.result, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _ask(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        self.ask_btn.setEnabled(False)
        self.result.setHtml("<i>Waiting for peer...</i>")
        self._worker = FederatedLlmWorker(self.engine, self.peer.currentData(),
                                          prompt, self.ask_local.isChecked())
        self._worker.ok.connect(self._ok)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _ok(self, out):
        self.ask_btn.setEnabled(True)
        parts = []
        if "local" in out:
            parts.append("<b>Your LLM:</b><br>" + html.escape(out["local"] or "").replace("\n", "<br>"))
        pr = out.get("peer", {})
        parts.append("<br><br><b>Peer's LLM (" + html.escape(str(pr.get("model", "peer"))) + "):</b><br>"
                     + html.escape(pr.get("text", "")).replace("\n", "<br>"))
        self.result.setHtml("".join(parts))

    def _fail(self, msg):
        self.ask_btn.setEnabled(True)
        self.result.setHtml(f"<span style='color:{RED}'>Failed: {html.escape(msg)}</span>")


class DiscoverDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Discover Peers (LAN)")
        self.setStyleSheet(_dialog_style())
        self.resize(560, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Peers advertising on the local network:"))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        scan_btn = QPushButton("Scan")
        scan_btn.clicked.connect(self._scan)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.connect_btn.clicked.connect(self._connect)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(scan_btn); row.addWidget(self.connect_btn); row.addStretch(); row.addWidget(close_btn)
        layout.addLayout(row)
        self._scan()

    def _scan(self):
        self.status.setText("Scanning LAN (about 4 seconds)…")
        self.list.clear()
        self._w = DiscoverWorker(self.engine)
        self._w.ok.connect(self._populate)
        self._w.failed.connect(lambda m: self.status.setText(f"Scan failed: {m}"))
        self._w.start()

    def _populate(self, peers):
        for p in peers:
            it = QListWidgetItem(f"{p['name']}  {p['host']}:{p['port']}  fp {p['fp'][:8]}")
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
        self.status.setText(f"{len(peers)} peer(s) found")

    def _connect(self):
        it = self.list.currentItem()
        if not it:
            return
        from kairos.collab import callsign as _cs
        p = it.data(Qt.UserRole)
        try:
            cs = _cs.build(p.get("name", "peer"), p.get("transport", "direct"),
                           p["host"], p["port"], p["fp"])
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Bad peer record: {e}")
            return
        self.connect_btn.setEnabled(False)
        self.status.setText("Connecting (waiting for peer approval)…")
        self._cw = ConnectWorker(self.engine, cs)
        self._cw.ok.connect(lambda s: (self.connect_btn.setEnabled(True),
                                       QMessageBox.information(self, "Kairos", "Connected."),
                                       self.accept()))
        self._cw.failed.connect(lambda m: (self.connect_btn.setEnabled(True),
                                           self.status.setText(f"Failed: {m}")))
        self._cw.start()


class AgentSettingsDialog(QDialog):
    """Configure agent capabilities, MCP, connectors, image gen and Discord."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Agent Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(640, 720)
        import json as _json
        cfg = engine.config
        agent = cfg.get("agent", {}) or {}
        layout = QVBoxLayout(self)

        base = QGroupBox("Agent")
        bf = QFormLayout(base)
        self.streaming = QCheckBox("Stream responses")
        self.streaming.setChecked(bool(agent.get("streaming", True)))
        self.native_tools = QCheckBox("Native tool-calling")
        self.native_tools.setChecked(bool(agent.get("native_tools", False)))
        self.allow_write = QCheckBox("Allow file writes (confined)")
        self.allow_write.setChecked(bool(agent.get("allow_file_write", True)))
        self.allow_shell = QCheckBox("Allow shell commands")
        self.allow_shell.setChecked(bool(agent.get("allow_shell", False)))
        self.sandbox = QComboBox()
        self.sandbox.addItems(["subprocess", "docker"])
        self.sandbox.setCurrentText(agent.get("skill_sandbox", "subprocess"))
        self.file_root = QLineEdit(agent.get("file_root") or "")
        self.daily_tokens = QLineEdit(str((agent.get("budgets", {}) or {}).get("daily_tokens", 0)))
        bf.addRow(self.streaming)
        bf.addRow(self.native_tools)
        bf.addRow(self.allow_write)
        bf.addRow(self.allow_shell)
        bf.addRow("Skill sandbox:", self.sandbox)
        bf.addRow("File root:", self.file_root)
        bf.addRow("Daily token budget (0=off):", self.daily_tokens)
        layout.addWidget(base)

        mcp = QGroupBox("MCP")
        mf = QVBoxLayout(mcp)
        self.mcp_enabled = QCheckBox("Enable MCP client (connect to external MCP servers)")
        self.mcp_enabled.setChecked(bool((cfg.get("mcp", {}) or {}).get("enabled")))
        mf.addWidget(self.mcp_enabled)
        mf.addWidget(QLabel("MCP servers (JSON):"))
        self.mcp_edit = QTextEdit()
        self.mcp_edit.setFont(QFont("Consolas", 9))
        self.mcp_edit.setPlainText(_json.dumps((cfg.get("mcp", {}) or {}).get("servers", {}), indent=2))
        mf.addWidget(self.mcp_edit, 1)
        srv_cfg = (cfg.get("mcp", {}) or {}).get("server", {}) or {}
        self.mcp_server_enabled = QCheckBox("Expose Kairos as an MCP server "
                                            "(run: python -m kairos.mcp_server)")
        self.mcp_server_enabled.setChecked(bool(srv_cfg.get("enabled")))
        self.mcp_expose_res = QCheckBox("Expose resources")
        self.mcp_expose_res.setChecked(bool(srv_cfg.get("expose_resources", True)))
        self.mcp_expose_prompts = QCheckBox("Expose prompts")
        self.mcp_expose_prompts.setChecked(bool(srv_cfg.get("expose_prompts", True)))
        copy_cmd = QPushButton("Copy server command")
        copy_cmd.clicked.connect(lambda: QApplication.clipboard().setText(
            "python -m kairos.mcp_server"))
        mf.addWidget(self.mcp_server_enabled)
        mf.addWidget(self.mcp_expose_res)
        mf.addWidget(self.mcp_expose_prompts)
        mf.addWidget(copy_cmd)
        layout.addWidget(mcp)

        conn = QGroupBox("Connectors (tokens stored in the OS keyring)")
        cf = QFormLayout(conn)
        ccfg = cfg.get("connectors", {}) or {}
        self.gh_enabled = QCheckBox("GitHub enabled"); self.gh_enabled.setChecked(bool(ccfg.get("github", {}).get("enabled")))
        self.gh_token = QLineEdit(); self.gh_token.setEchoMode(QLineEdit.Password); self.gh_token.setPlaceholderText("GitHub token")
        self.nt_enabled = QCheckBox("Notion enabled"); self.nt_enabled.setChecked(bool(ccfg.get("notion", {}).get("enabled")))
        self.nt_token = QLineEdit(); self.nt_token.setEchoMode(QLineEdit.Password); self.nt_token.setPlaceholderText("Notion token")
        self.go_enabled = QCheckBox("Google Drive enabled"); self.go_enabled.setChecked(bool(ccfg.get("google", {}).get("enabled")))
        self.go_token = QLineEdit(); self.go_token.setEchoMode(QLineEdit.Password); self.go_token.setPlaceholderText("Google OAuth access token")
        cf.addRow(self.gh_enabled); cf.addRow("GitHub token:", self.gh_token)
        cf.addRow(self.nt_enabled); cf.addRow("Notion token:", self.nt_token)
        cf.addRow(self.go_enabled); cf.addRow("Google token:", self.go_token)
        layout.addWidget(conn)

        img = QGroupBox("Image generation")
        inf = QFormLayout(img)
        icfg = agent.get("image", {}) or {}
        self.img_enabled = QCheckBox("Enabled"); self.img_enabled.setChecked(bool(icfg.get("enabled")))
        self.img_url = QLineEdit(icfg.get("api_url", ""))
        self.img_model = QLineEdit(icfg.get("model", ""))
        self.img_key = QLineEdit(); self.img_key.setEchoMode(QLineEdit.Password); self.img_key.setPlaceholderText("API key")
        inf.addRow(self.img_enabled); inf.addRow("API URL:", self.img_url)
        inf.addRow("Model:", self.img_model); inf.addRow("API key:", self.img_key)
        layout.addWidget(img)

        disc = QGroupBox("Discord")
        df = QFormLayout(disc)
        dcfg = cfg.get("discord", {}) or {}
        self.dc_enabled = QCheckBox("Enabled"); self.dc_enabled.setChecked(bool(dcfg.get("enabled")))
        self.dc_ids = QLineEdit(", ".join(str(x) for x in dcfg.get("allowed_user_ids", [])))
        self.dc_token = QLineEdit(); self.dc_token.setEchoMode(QLineEdit.Password); self.dc_token.setPlaceholderText("Discord bot token")
        df.addRow(self.dc_enabled); df.addRow("Allowed user IDs:", self.dc_ids); df.addRow("Token:", self.dc_token)
        layout.addWidget(disc)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def accept(self):
        import json as _json
        import keyring
        schedule = self.sandbox.currentText()
        try:
            budget = int(self.daily_tokens.text() or 0)
        except ValueError:
            budget = 0
        try:
            servers = _json.loads(self.mcp_edit.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"MCP servers JSON invalid: {e}")
            return
        ids = [int(x) for x in self.dc_ids.text().replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()]

        def _apply(c):
            a = c.setdefault("agent", {})
            a["streaming"] = self.streaming.isChecked()
            a["native_tools"] = self.native_tools.isChecked()
            a["allow_file_write"] = self.allow_write.isChecked()
            a["allow_shell"] = self.allow_shell.isChecked()
            a["skill_sandbox"] = schedule
            a["file_root"] = self.file_root.text().strip() or None
            a.setdefault("budgets", {})["daily_tokens"] = budget
            a.setdefault("image", {})
            a["image"]["enabled"] = self.img_enabled.isChecked()
            a["image"]["api_url"] = self.img_url.text().strip()
            a["image"]["model"] = self.img_model.text().strip()
            a["image"]["api_key"] = None
            c.setdefault("mcp", {})["enabled"] = self.mcp_enabled.isChecked()
            c["mcp"]["servers"] = servers
            srv = c["mcp"].setdefault("server", {})
            srv["enabled"] = self.mcp_server_enabled.isChecked()
            srv["expose_resources"] = self.mcp_expose_res.isChecked()
            srv["expose_prompts"] = self.mcp_expose_prompts.isChecked()
            conn = c.setdefault("connectors", {})
            conn.setdefault("github", {})["enabled"] = self.gh_enabled.isChecked()
            conn.setdefault("notion", {})["enabled"] = self.nt_enabled.isChecked()
            conn.setdefault("google", {})["enabled"] = self.go_enabled.isChecked()
            for k in ("github", "notion", "google"):
                conn[k]["token"] = None
            d = c.setdefault("discord", {})
            d["enabled"] = self.dc_enabled.isChecked()
            d["allowed_user_ids"] = ids
            d["token"] = None

        self.engine.config = _merge_save(_apply)
        for entry, edit in (("github_token", self.gh_token), ("notion_token", self.nt_token),
                            ("google_token", self.go_token), ("image_api_key", self.img_key),
                            ("discord_token", self.dc_token)):
            val = edit.text().strip()
            if val:
                try:
                    keyring.set_password("kairos", entry, val)
                except Exception:
                    pass
        self.engine.config = __import__("kairos.config", fromlist=["load_config"]).load_config()
        QMessageBox.information(self, "Kairos", "Agent settings saved.")
        super().accept()


class UsageTracesDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Usage & Traces")
        self.setStyleSheet(_dialog_style())
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        row.addWidget(refresh); row.addStretch()
        layout.addLayout(row)
        self.view = QTextBrowser()
        self.view.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        layout.addWidget(self.view, 1)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self):
        s = self.engine.usage_summary(30)
        lines = [f"Usage (30 days): {s.get('total_calls',0)} calls, "
                 f"{s.get('total_tokens',0)} tokens", ""]
        for p in s.get("by_provider", []):
            lines.append(f"  {p['provider']}: {p['calls']} calls, "
                         f"{p['prompt_tokens'] + p['completion_tokens']} tokens")
        lines.append("")
        lines.append("Recent spans:")
        try:
            for ts, source, prov, model, pt, ct, ms, ok in self.engine.tracing.recent(20):
                lines.append(f"  {ts[:19]} {source} {prov}/{model} "
                             f"in={pt} out={ct} {ms}ms {'ok' if ok else 'err'}")
        except Exception:
            pass
        self.view.setPlainText("\n".join(lines))


class PlansDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Plans & Scheduled Tasks")
        self.setStyleSheet(_dialog_style())
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self._refresh)
        layout.addWidget(refresh)
        self.view = QTextBrowser()
        self.view.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        layout.addWidget(self.view, 1)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self):
        lines = ["PLANS", "====="]
        for pid, goal, status, created in self.engine.plan_list(20):
            lines.append(f"- [{status}] {goal}  ({pid})")
            p = self.engine.plan_get(pid)
            for st in (p or {}).get("steps", []):
                lines.append(f"    {st['idx']}. [{st['status']}] {st['title']}")
        lines.append("")
        lines.append("SCHEDULED TASKS")
        lines.append("===============")
        for t in self.engine.list_scheduled_tasks():
            _tid, name, kind, _payload, interval, _next, _en, _last, last_result = t
            lines.append(f"- {name} [{kind}] every {interval}s | last: {(last_result or '')[:80]}")
        self.view.setPlainText("\n".join(lines))


class PredictDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Predictive Engine")
        self.setStyleSheet(_dialog_style())
        self.resize(640, 520)
        self.files = []
        self.links = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("Ask Kairos to predict an outcome")
        header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(header)

        layout.addWidget(QLabel("Prediction question:"))
        self.question_edit = QTextEdit()
        self.question_edit.setPlaceholderText("e.g. How will this news affect public opinion in the next month?")
        self.question_edit.setFixedHeight(80)
        layout.addWidget(self.question_edit)

        # Files (Excel/CSV)
        files_row = QHBoxLayout()
        files_row.addWidget(QLabel("Data files (Excel/CSV):"))
        self.add_files_btn = QPushButton("Add Files")
        self.add_files_btn.clicked.connect(self._add_files)
        files_row.addWidget(self.add_files_btn)
        files_row.addStretch()
        layout.addLayout(files_row)
        self.files_label = QLabel("(none)")
        self.files_label.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(self.files_label)

        # Links
        layout.addWidget(QLabel("News / social media links (one per line):"))
        self.links_edit = QTextEdit()
        self.links_edit.setPlaceholderText("https://...\nhttps://...")
        self.links_edit.setFixedHeight(70)
        layout.addWidget(self.links_edit)

        # Extra context
        layout.addWidget(QLabel("Additional context (optional):"))
        self.text_edit = QTextEdit()
        self.text_edit.setFixedHeight(70)
        layout.addWidget(self.text_edit)

        # Mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Engine:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Auto (MiroFish if available, else Quick)", "auto")
        self.mode_combo.addItem("Quick (in-Kairos debate)", "quick")
        self.mode_combo.addItem("MiroFish (swarm simulation)", "mirofish")
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        # Run button
        self.run_btn = QPushButton("Run Prediction")
        self.run_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.run_btn.clicked.connect(self._run)
        layout.addWidget(self.run_btn)

        # Result
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(self.status_label)
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        layout.addWidget(self.result_display, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select data files", "",
            "Data files (*.xlsx *.xls *.csv);;All files (*)"
        )
        if paths:
            self.files.extend(paths)
            self.files_label.setText("\n".join(p.split("/")[-1].split("\\")[-1] for p in self.files))

    def _run(self):
        question = self.question_edit.toPlainText().strip()
        if not question:
            QMessageBox.warning(self, "Kairos", "Enter a prediction question.")
            return
        links = [l.strip() for l in self.links_edit.toPlainText().splitlines() if l.strip()]
        text = self.text_edit.toPlainText().strip() or None
        mode = self.mode_combo.currentData()

        self.run_btn.setEnabled(False)
        self.status_label.setText("Running prediction (this may take a while)...")
        self.result_display.clear()
        self.worker = PredictWorker(self.engine, question, self.files, links, text, mode)
        self.worker.finished.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_done(self, result):
        self.run_btn.setEnabled(True)
        source = result.get("source", "?")
        report = result.get("report", "")
        self.status_label.setText(f"Done (engine: {source})")
        self.result_display.setPlainText(report)

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.status_label.setText("Failed")
        self.result_display.setPlainText(f"[Error] {msg}")


class RetentionDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Retention - Saved Data")
        self.setStyleSheet(_dialog_style())
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Add new retained data ---
        add_header = QLabel("Add Data to Retention")
        add_header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(add_header)

        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("Type a note / fact / idea to save for later recall...")
        self.add_edit.returnPressed.connect(self._add_memory)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_edit, 1)
        self.add_btn = QPushButton("Save")
        self.add_btn.setStyleSheet(f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.add_btn.clicked.connect(self._add_memory)
        add_row.addWidget(self.add_btn)
        layout.addLayout(add_row)

        # --- Retained data list ---
        mem_header = QLabel("Retained Data")
        mem_header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(mem_header)

        self.mem_list = QListWidget()
        layout.addWidget(self.mem_list, 1)
        self._refresh_memories()

        mem_btn_row = QHBoxLayout()
        self.del_mem_btn = QPushButton("Delete Selected Memory")
        self.del_mem_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        self.del_mem_btn.clicked.connect(self._delete_memory)
        mem_btn_row.addWidget(self.del_mem_btn)
        mem_btn_row.addStretch()
        layout.addLayout(mem_btn_row)

        # --- Expired items (deletion) ---
        exp_header = QLabel("Expired Items (older than retention period)")
        exp_header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(exp_header)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        items = self.engine.collect_expired()
        self.item_ids = []
        for item in items:
            qitem = QListWidgetItem(f"[{item['kind']}] {item['label']}")
            qitem.setFlags(qitem.flags() | Qt.ItemIsUserCheckable)
            qitem.setCheckState(Qt.Unchecked)
            qitem.setData(Qt.UserRole, item["id"])
            self.list_widget.addItem(qitem)
            self.item_ids.append(item["id"])

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

    def _refresh_memories(self):
        self.mem_list.clear()
        try:
            memories = self.engine.list_memories()
        except Exception as e:
            self.add_edit.setEnabled(False)
            self.mem_list.addItem(f"Unavailable: {e}")
            return
        for mem_id, content, created in memories:
            qitem = QListWidgetItem(content[:120])
            qitem.setData(Qt.UserRole, mem_id)
            qitem.setToolTip(content)
            self.mem_list.addItem(qitem)

    def _add_memory(self):
        text = self.add_edit.text().strip()
        if not text:
            return
        try:
            self.engine.add_memory(text)
            self.add_edit.clear()
            self._refresh_memories()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Save failed: {e}")

    def _delete_memory(self):
        item = self.mem_list.currentItem()
        if not item:
            QMessageBox.information(self, "Kairos", "Select a memory to delete.")
            return
        mem_id = item.data(Qt.UserRole)
        try:
            self.engine.delete_memory(mem_id)
            self._refresh_memories()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Delete failed: {e}")

    def delete_selected(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        if not selected:
            QMessageBox.information(self, "Kairos", "No items selected.")
            return
        deleted = self.engine.approve_retention_deletion(selected)
        QMessageBox.information(self, "Kairos", f"Deleted {deleted} item(s).")
        self.accept()


class GitDialog(QDialog):
    """Git & version-control workflows (uses the system git CLI)."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Git & Version Control")
        self.setStyleSheet(_dialog_style())
        self.resize(780, 660)
        cfg = engine.config.get("git", {}) or {}
        layout = QVBoxLayout(self)

        settings = QGroupBox("Settings")
        sf = QFormLayout(settings)
        self.g_enabled = QCheckBox("Enable git integration")
        self.g_enabled.setChecked(bool(cfg.get("enabled")))
        self.g_root = QLineEdit(cfg.get("repo_root") or "")
        root_row = QHBoxLayout()
        root_row.addWidget(self.g_root, 1)
        browse = QPushButton("Browse\u2026")
        browse.clicked.connect(self._browse)
        root_row.addWidget(browse)
        self.g_push = QCheckBox("Allow push")
        self.g_push.setChecked(bool(cfg.get("allow_push")))
        self.g_pull = QCheckBox("Allow pull")
        self.g_pull.setChecked(bool(cfg.get("allow_pull")))
        self.g_destructive = QCheckBox("Allow destructive operations")
        self.g_destructive.setChecked(bool(cfg.get("allow_destructive")))
        self.g_name = QLineEdit(cfg.get("author_name") or "")
        self.g_email = QLineEdit(cfg.get("author_email") or "")
        sf.addRow(self.g_enabled)
        sf.addRow("Repository root:", root_row)
        sf.addRow(self.g_push)
        sf.addRow(self.g_pull)
        sf.addRow(self.g_destructive)
        sf.addRow("Author name:", self.g_name)
        sf.addRow("Author email:", self.g_email)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save)
        sf.addRow(save)
        layout.addWidget(settings)

        actions = QGroupBox("Repository")
        af = QHBoxLayout(actions)
        for label, op in (("Status", "status"), ("Diff", "diff"), ("Log", "log"),
                          ("Branches", "branches")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, o=op: self._run(o))
            af.addWidget(b)
        layout.addWidget(actions)

        commit_row = QHBoxLayout()
        self.commit_msg = QLineEdit()
        self.commit_msg.setPlaceholderText("Commit message\u2026")
        commit_btn = QPushButton("Commit All")
        commit_btn.clicked.connect(self._commit)
        commit_row.addWidget(self.commit_msg, 1)
        commit_row.addWidget(commit_btn)
        layout.addLayout(commit_row)

        branch_row = QHBoxLayout()
        self.branch_name = QLineEdit()
        self.branch_name.setPlaceholderText("branch name")
        nb = QPushButton("New Branch")
        nb.clicked.connect(self._new_branch)
        co = QPushButton("Checkout")
        co.clicked.connect(self._checkout)
        branch_row.addWidget(self.branch_name, 1)
        branch_row.addWidget(nb)
        branch_row.addWidget(co)
        layout.addLayout(branch_row)

        if cfg.get("allow_push"):
            push = QPushButton("Push")
            push.clicked.connect(lambda: self._run("push"))
            layout.addWidget(push)
        if cfg.get("allow_pull"):
            pull = QPushButton("Pull")
            pull.clicked.connect(lambda: self._run("pull"))
            layout.addWidget(pull)

        self.out = QTextBrowser()
        self.out.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        layout.addWidget(self.out, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select repository root")
        if d:
            self.g_root.setText(d)

    def _save(self):
        def _apply(c):
            g = c.setdefault("git", {})
            g["enabled"] = self.g_enabled.isChecked()
            g["repo_root"] = self.g_root.text().strip() or None
            g["allow_push"] = self.g_push.isChecked()
            g["allow_pull"] = self.g_pull.isChecked()
            g["allow_destructive"] = self.g_destructive.isChecked()
            g["author_name"] = self.g_name.text().strip()
            g["author_email"] = self.g_email.text().strip()
        self.engine.config = _merge_save(_apply)
        QMessageBox.information(self, "Kairos", "Git settings saved.")

    def _run(self, op):
        self.worker = GitWorker(self.engine, op)
        self.worker.finished.connect(self.out.setPlainText)
        self.worker.start()

    def _commit(self):
        msg = self.commit_msg.text().strip()
        if not msg:
            QMessageBox.warning(self, "Kairos", "Enter a commit message.")
            return
        self.worker = GitWorker(self.engine, "commit", message=msg, add_all=True)
        self.worker.finished.connect(self.out.setPlainText)
        self.worker.start()
        self.commit_msg.clear()

    def _new_branch(self):
        name = self.branch_name.text().strip()
        if not name:
            return
        self.worker = GitWorker(self.engine, "create_branch", name=name)
        self.worker.finished.connect(self.out.setPlainText)
        self.worker.start()
        self.branch_name.clear()

    def _checkout(self):
        name = self.branch_name.text().strip()
        if not name:
            return
        self.worker = GitWorker(self.engine, "checkout", name=name)
        self.worker.finished.connect(self.out.setPlainText)
        self.worker.start()
        self.branch_name.clear()


class WebhookDialog(QDialog):
    """Configure the inbound/outbound webhook endpoint."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        import json as _json
        self.engine = engine
        self.setWindowTitle("Webhook Settings")
        self.setStyleSheet(_dialog_style())
        self.resize(680, 700)
        cfg = engine.config.get("webhook", {}) or {}
        out = cfg.get("outbound", {}) or {}
        layout = QVBoxLayout(self)

        inbound = QGroupBox("Inbound (external \u2192 Kairos)")
        inf = QFormLayout(inbound)
        self.w_enabled = QCheckBox("Enable webhook endpoint")
        self.w_enabled.setChecked(bool(cfg.get("enabled")))
        self.w_host = QLineEdit(cfg.get("host", "127.0.0.1"))
        self.w_port = QLineEdit(str(cfg.get("port", 8765)))
        self.w_sig = QCheckBox("Require HMAC signature (X-Kairos-Signature)")
        self.w_sig.setChecked(bool(cfg.get("require_signature")))
        self.w_public = QCheckBox("Allow non-loopback bind (unsafe)")
        self.w_public.setChecked(bool(cfg.get("allow_public_bind")))
        self.w_secret = QLineEdit()
        self.w_secret.setEchoMode(QLineEdit.Password)
        self.w_secret.setPlaceholderText("shared secret (stored in the OS keyring)")
        self.hooks_edit = QTextEdit()
        self.hooks_edit.setFont(QFont("Consolas", 9))
        self.hooks_edit.setPlainText(_json.dumps(cfg.get("hooks", {}), indent=2))
        inf.addRow(self.w_enabled)
        inf.addRow("Host:", self.w_host)
        inf.addRow("Port:", self.w_port)
        inf.addRow(self.w_public)
        inf.addRow(self.w_sig)
        inf.addRow("Secret:", self.w_secret)
        inf.addRow(QLabel("Hooks (JSON):"))
        inf.addRow(self.hooks_edit)
        layout.addWidget(inbound)

        outbound = QGroupBox("Outbound (Kairos \u2192 URL)")
        of = QFormLayout(outbound)
        self.o_enabled = QCheckBox("Enable outbound notifications")
        self.o_enabled.setChecked(bool(out.get("enabled")))
        self.o_urls = QTextEdit()
        self.o_urls.setFixedHeight(70)
        self.o_urls.setPlainText("\n".join(out.get("urls", []) or []))
        self.o_secret = QLineEdit()
        self.o_secret.setEchoMode(QLineEdit.Password)
        self.o_secret.setPlaceholderText("outbound signing secret (keyring)")
        of.addRow(self.o_enabled)
        of.addRow(QLabel("URLs (one per line):"), self.o_urls)
        of.addRow("Secret:", self.o_secret)
        test = QPushButton("Send test event")
        test.clicked.connect(self._test)
        of.addRow(test)
        layout.addWidget(outbound)

        hint = QLabel(f"Endpoint: POST http://{cfg.get('host','127.0.0.1')}:"
                      f"{cfg.get('port',8765)}/hook/<name>  \u00b7  GET /health")
        hint.setStyleSheet(f"color: {TEXT_GREY};")
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _test(self):
        self.worker = WebhookTestWorker(self.engine)
        self.worker.finished.connect(lambda t: QMessageBox.information(self, "Webhook", t))
        self.worker.start()

    def _save(self):
        import json as _json
        import keyring
        try:
            port = int(self.w_port.text().strip() or 8765)
        except ValueError:
            QMessageBox.warning(self, "Kairos", "Port must be a number.")
            return
        try:
            hooks = _json.loads(self.hooks_edit.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Hooks JSON invalid: {e}")
            return

        def _apply(c):
            w = c.setdefault("webhook", {})
            w["enabled"] = self.w_enabled.isChecked()
            w["host"] = self.w_host.text().strip() or "127.0.0.1"
            w["port"] = port
            w["require_signature"] = self.w_sig.isChecked()
            w["allow_public_bind"] = self.w_public.isChecked()
            w["hooks"] = hooks
            o = w.setdefault("outbound", {})
            o["enabled"] = self.o_enabled.isChecked()
            o["urls"] = [u.strip() for u in self.o_urls.toPlainText().splitlines() if u.strip()]
        self.engine.config = _merge_save(_apply)
        if self.w_secret.text().strip():
            try:
                keyring.set_password("kairos", "webhook_secret", self.w_secret.text().strip())
            except Exception:
                pass
        if self.o_secret.text().strip():
            try:
                keyring.set_password("kairos", "webhook_outbound_secret", self.o_secret.text().strip())
            except Exception:
                pass
        self.engine.config = __import__("kairos.config", fromlist=["load_config"]).load_config()
        QMessageBox.information(self, "Kairos", "Webhook settings saved. Restart Kairos to (re)start the endpoint.")
        self.accept()


class ArtifactsDialog(QDialog):
    """Drawings & Design: generate SVG from a description, write documents, manage files."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Drawings & Design")
        self.setStyleSheet(_dialog_style())
        self.resize(760, 680)
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        open_btn = QPushButton("Open Selected")
        open_btn.clicked.connect(self._open)
        reveal = QPushButton("Reveal Folder")
        reveal.clicked.connect(self._reveal)
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setStyleSheet(f"background-color: {RED}; color: white;")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(refresh)
        row.addWidget(open_btn)
        row.addWidget(reveal)
        row.addStretch()
        row.addWidget(self.delete_btn)
        layout.addLayout(row)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        # --- Design from a description (SVG) ---
        design_box = QGroupBox("Design from description (SVG)")
        df = QVBoxLayout(design_box)
        self.design_name = QLineEdit()
        self.design_name.setPlaceholderText("name (e.g. esp32_schematic)")
        self.design_desc = QTextEdit()
        self.design_desc.setPlaceholderText(
            "Describe what to draw, e.g. \u201cA block diagram of an ESP32-S3 with "
            "a 3.3V regulator and USB-C connector, labelled.\u201d")
        self.design_desc.setFixedHeight(80)
        self.draw_btn = QPushButton("Generate SVG")
        self.draw_btn.setStyleSheet(
            f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.draw_btn.clicked.connect(self._generate_svg)
        self.design_status = QLabel("")
        self.design_status.setStyleSheet(f"color: {TEXT_GREY};")
        df.addWidget(self.design_name)
        df.addWidget(self.design_desc)
        df.addWidget(self.draw_btn)
        df.addWidget(self.design_status)
        layout.addWidget(design_box)

        # --- Write a document (secondary) ---
        doc_box = QGroupBox("Write document")
        nf = QVBoxLayout(doc_box)
        self.doc_name = QLineEdit()
        self.doc_name.setPlaceholderText("filename (e.g. notes.md)")
        self.doc_body = QTextEdit()
        self.doc_body.setPlaceholderText("Document content\u2026")
        self.doc_body.setFixedHeight(70)
        save = QPushButton("Save Document")
        save.clicked.connect(self._save_doc)
        nf.addWidget(self.doc_name)
        nf.addWidget(self.doc_body)
        nf.addWidget(save)
        layout.addWidget(doc_box)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        try:
            items = self.engine.list_artifacts()
        except Exception as e:
            self.list_widget.addItem(f"Unavailable: {e}")
            return
        for a in items:
            self.list_widget.addItem(f"{a['name']}  ({a['size']} bytes)  {a['mtime'][:19]}")
            self.list_widget.item(self.list_widget.count() - 1).setData(Qt.UserRole, a["path"])

    def _selected_path(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _open(self):
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "Kairos", "Select an artifact first.")
            return
        _open_path(path)

    def _reveal(self):
        try:
            from kairos import artifacts
            _open_path(str(artifacts._dir()))
        except Exception as e:
            QMessageBox.warning(self, "Kairos", str(e))

    def _delete(self):
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "Kairos", "Select an artifact to delete first.")
            return
        import os
        name = os.path.basename(path)
        if QMessageBox.question(self, "Delete artifact",
                                f"Delete \u201c{name}\u201d permanently?",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.engine.delete_artifact(path)
            self._refresh()
            self.design_status.setText(f"Deleted {name}")
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Delete failed: {e}")

    def _generate_svg(self):
        description = self.design_desc.toPlainText().strip()
        if not description:
            QMessageBox.warning(self, "Kairos", "Enter a description to draw.")
            return
        name = self.design_name.text().strip() or "design"
        self.draw_btn.setEnabled(False)
        self.draw_btn.setText("Generating\u2026")
        self.design_status.setText("Generating SVG from the description\u2026")
        self.worker = ArtifactGenWorker(self.engine, name, description)
        self.worker.finished.connect(self._on_svg_generated)
        self.worker.start()

    def _on_svg_generated(self, result):
        self.draw_btn.setEnabled(True)
        self.draw_btn.setText("Generate SVG")
        if result.startswith("[Error]"):
            self.design_status.setText(result)
            return
        self.design_status.setText(result)
        self.design_name.clear()
        self.design_desc.clear()
        self._refresh()
        path = result.split("Saved:", 1)[-1].strip() if "Saved:" in result else None
        if path and QMessageBox.question(self, "Artifact",
                                         "SVG created. Open it now?",
                                         QMessageBox.Yes | QMessageBox.No,
                                         QMessageBox.Yes) == QMessageBox.Yes:
            _open_path(path)

    def _save_doc(self):
        name = self.doc_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Kairos", "Enter a filename.")
            return
        try:
            path = self.engine.write_document(name, self.doc_body.toPlainText())
            QMessageBox.information(self, "Kairos", f"Saved: {path}")
            self.doc_name.clear()
            self.doc_body.clear()
            self._refresh()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Save failed: {e}")


class BrowserAgentDialog(QDialog):
    """Browser Agent: drive a real browser to browse, fill forms and design."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._choices = []
        self._workers = []
        self.setWindowTitle("Browser Agent")
        self.setStyleSheet(_dialog_style())
        self.resize(920, 780)
        layout = QVBoxLayout(self)

        self.cap_banner = QLabel("")
        self.cap_banner.setWordWrap(True)
        self.cap_banner.setStyleSheet(f"color: {GREEN_DIM};")
        layout.addWidget(self.cap_banner)
        self._update_cap_banner()

        bcfg = engine.config.get("browser", {}) or {}

        # --- Session ---
        sess = QGroupBox("Browser")
        sg = QVBoxLayout(sess)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        self.browser_combo.setMinimumWidth(240)
        row1.addWidget(self.browser_combo, 1)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.clicked.connect(self._detect)
        row1.addWidget(self.detect_btn)
        row1.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Auto (attach if possible)", "ask")
        self.mode_combo.addItem("Launch controlled", "launch")
        self.mode_combo.addItem("Attach (CDP)", "attach")
        idx = self.mode_combo.findData(bcfg.get("mode", "ask"))
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self._apply_settings)
        row1.addWidget(self.mode_combo)
        sg.addLayout(row1)

        row2 = QHBoxLayout()
        self.enable_chk = QCheckBox("Enable browser session")
        self.enable_chk.setChecked(bool(bcfg.get("enabled")))
        self.enable_chk.toggled.connect(self._apply_settings)
        self.js_chk = QCheckBox("Allow JS evaluation")
        self.js_chk.setChecked(bool(bcfg.get("allow_js_eval")))
        self.js_chk.toggled.connect(self._apply_settings)
        self.up_chk = QCheckBox("Allow uploads")
        self.up_chk.setChecked(bool(bcfg.get("allow_uploads")))
        self.up_chk.toggled.connect(self._apply_settings)
        self.vision_chk = QCheckBox("Vision assist")
        self.vision_chk.setChecked(bool(bcfg.get("vision_assist")))
        self.vision_chk.toggled.connect(self._apply_settings)
        row2.addWidget(self.enable_chk)
        row2.addWidget(self.js_chk)
        row2.addWidget(self.up_chk)
        row2.addWidget(self.vision_chk)
        sg.addLayout(row2)

        row3 = QHBoxLayout()
        self.start_btn = QPushButton("Start / Attach")
        self.start_btn.setStyleSheet(
            f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.install_btn = QPushButton("Install Chromium (Playwright)")
        self.install_btn.clicked.connect(self._install_chromium)
        self.grant_btn = QPushButton("Grant browser control")
        self.grant_btn.clicked.connect(self._grant_capability)
        row3.addWidget(self.start_btn)
        row3.addWidget(self.stop_btn)
        row3.addWidget(self.install_btn)
        row3.addWidget(self.grant_btn)
        row3.addStretch()
        sg.addLayout(row3)
        layout.addWidget(sess)

        # --- Browse ---
        browse = QGroupBox("Browse")
        bg = QVBoxLayout(browse)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit("https://www.google.com")
        brow.addWidget(self.url_edit, 1)
        for label, fn in (("Go", self._go), ("Back", self._back),
                          ("Forward", self._forward), ("Reload", self._reload)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            brow.addWidget(b)
        bg.addLayout(brow)
        self.page_label = QLabel("No page open")
        self.page_label.setStyleSheet(f"color: {TEXT_GREY};")
        self.page_label.setWordWrap(True)
        bg.addWidget(self.page_label)
        layout.addWidget(browse)

        # --- Forms ---
        form = QGroupBox("Fill form")
        fg = QVBoxLayout(form)
        frow = QHBoxLayout()
        self.inputs_btn = QPushButton("List inputs")
        self.inputs_btn.clicked.connect(self._list_inputs)
        frow.addWidget(self.inputs_btn)
        self.fill_btn = QPushButton("Fill form (JSON)")
        self.fill_btn.clicked.connect(self._fill_form)
        frow.addWidget(self.fill_btn)
        frow.addStretch()
        fg.addLayout(frow)
        self.form_edit = QTextEdit()
        self.form_edit.setFixedHeight(64)
        self.form_edit.setPlaceholderText('{"Email": "a@b.com", "Name": "RC"}')
        fg.addWidget(self.form_edit)
        layout.addWidget(form)

        # --- Design ---
        design = QGroupBox("Design task")
        dg = QVBoxLayout(design)
        self.goal_edit = QTextEdit()
        self.goal_edit.setPlaceholderText(
            "e.g. On EasyEDA, place an ESP32-S3, a 3.3V regulator and a USB-C "
            "connector, then wire and label them.")
        self.goal_edit.setFixedHeight(64)
        dg.addWidget(self.goal_edit)
        drow = QHBoxLayout()
        self.run_btn = QPushButton("Run design task")
        self.run_btn.setStyleSheet(
            f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;")
        self.run_btn.clicked.connect(self._run)
        drow.addWidget(self.run_btn)
        self.captcha_btn = QPushButton("Detect CAPTCHA")
        self.captcha_btn.clicked.connect(self._detect_captcha)
        drow.addWidget(self.captcha_btn)
        self.wait_captcha_btn = QPushButton("Wait until CAPTCHA solved")
        self.wait_captcha_btn.clicked.connect(self._wait_captcha)
        drow.addWidget(self.wait_captcha_btn)
        drow.addStretch()
        dg.addLayout(drow)
        layout.addWidget(design)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {TEXT_GREY};")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.out = QTextBrowser()
        self.out.setStyleSheet(f"background-color: {BG_INPUT}; color: {TEXT};")
        layout.addWidget(self.out, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

        self._detect()

    # -- capability -------------------------------------------------------
    def _update_cap_banner(self):
        try:
            ok = self.engine.can("browser_control")
        except Exception:
            ok = True
        if ok:
            self.cap_banner.setText("")
            return
        try:
            prof = self.engine.active_character_profile()
        except Exception:
            prof = {}
        self.cap_banner.setText(
            f"The active character '{prof.get('name', '?')}' lacks browser control. "
            "Use 'Grant browser control' (custom characters) or switch to General.")

    def _grant_capability(self):
        try:
            prof = dict(self.engine.active_character_profile())
            caps = list(prof.get("capabilities") or [])
            if "browser_control" not in caps:
                caps.append("browser_control")
            prof["capabilities"] = caps
            self.engine.save_character(prof)
            import kairos.config as _cfg
            self.engine.config = _cfg.load_config()
            self.status.setText("Browser control enabled for this character.")
            self._update_cap_banner()
        except Exception as e:
            self.status.setText(f"Could not enable (built-in? switch to General): {e}")

    # -- settings ---------------------------------------------------------
    def _apply_settings(self, _=False):
        def _mut(c):
            b = c.setdefault("browser", {})
            b["enabled"] = self.enable_chk.isChecked()
            b["allow_js_eval"] = self.js_chk.isChecked()
            b["allow_uploads"] = self.up_chk.isChecked()
            b["vision_assist"] = self.vision_chk.isChecked()
            b["mode"] = self.mode_combo.currentData()
        try:
            self.engine.config = _merge_save(_mut)
        except Exception as e:
            self.status.setText(f"Could not save settings: {e}")

    # -- worker helper ----------------------------------------------------
    def _call(self, fn, on_ok=None, busy=None):
        if busy:
            self.status.setText(busy)
        w = BrowserCallWorker(fn)
        self._workers.append(w)

        def _cleanup(*_a):
            try:
                self._workers.remove(w)
            except Exception:
                pass

        w.finished.connect(_cleanup)
        w.failed.connect(_cleanup)
        w.finished.connect(lambda r: self._on_call_done(r, on_ok))
        w.failed.connect(self._on_call_fail)
        w.start()

    def _on_call_done(self, result, on_ok):
        if on_ok:
            try:
                on_ok(result)
            except Exception as e:
                self.status.setText(f"Error: {e}")
        else:
            self.status.setText("Done.")
            self.out.setPlainText(str(result))

    def _on_call_fail(self, msg):
        self.status.setText(f"Error: {msg}")
        self.out.setPlainText(f"[Error] {msg}")

    # -- detection / lifecycle -------------------------------------------
    def _detect(self):
        self.status.setText("Detecting browsers\u2026")
        self._call(lambda: self.engine.browser_detect(), self._on_detected)

    def _on_detected(self, res):
        res = res or {}
        choices = res.get("choices") or []
        self._choices = choices
        selected = (self.engine.config.get("browser", {}) or {}).get("selected")
        self.browser_combo.blockSignals(True)
        self.browser_combo.clear()
        for c in choices:
            label = (c.get("name") or c.get("id") or "?")
            if c.get("running"):
                label += " (running)"
            self.browser_combo.addItem(label, c.get("id"))
        if selected:
            for i in range(self.browser_combo.count()):
                if self.browser_combo.itemData(i) == selected:
                    self.browser_combo.setCurrentIndex(i)
                    break
        self.browser_combo.blockSignals(False)
        cdp = res.get("debug_endpoint")
        msg = f"Detected {len(choices)} browser(s)."
        if cdp:
            msg += f" CDP endpoint at {cdp.get('url')} ({cdp.get('label')})."
        self.status.setText(msg)

    def _start(self):
        if not self.enable_chk.isChecked():
            self.enable_chk.setChecked(True)
        choice = self.browser_combo.currentData()
        mode = self.mode_combo.currentData()
        url = self.url_edit.text().strip()
        self._call(lambda: self.engine.browser_start(choice_id=choice, url=url, mode=mode),
                   self._on_started, busy=f"Starting {choice or 'browser'}\u2026")

    def _on_started(self, info):
        info = info or {}
        self.status.setText(
            f"Session: {info.get('browser', '?')} [{info.get('mode', '?')}]")
        self.page_label.setText(f"{info.get('title', '')} \u2014 {info.get('url', '')}")
        self.out.setPlainText(json.dumps(info, indent=2))
        self._refresh_info()

    def _stop(self):
        self._call(lambda: self.engine.browser_stop(),
                   lambda r: self.status.setText(str(r)))

    def _install_chromium(self):
        self.status.setText("Installing Chromium (this may take a few minutes)\u2026")
        self.install_btn.setEnabled(False)
        self._install_worker = PlaywrightInstallWorker()
        self._install_worker.finished.connect(self._on_install_done)
        self._install_worker.start()

    def _on_install_done(self, text):
        self.install_btn.setEnabled(True)
        self.status.setText("Chromium install finished."
                            if not text.startswith("[Error]") else text)
        self.out.setPlainText(text)

    # -- browsing ---------------------------------------------------------
    def _refresh_info(self):
        self._call(lambda: self.engine.browser_info(), self._on_info)

    def _on_info(self, info):
        if info and info.get("running"):
            self.page_label.setText(f"{info.get('title', '')} \u2014 {info.get('url', '')}")

    def _go(self):
        url = self.url_edit.text().strip()
        self._call(lambda: self.engine.browser_goto(url), self._on_after,
                   busy=f"Opening {url}\u2026")

    def _back(self):
        from kairos import browser
        self._call(lambda: browser.session_do("back"), self._on_after)

    def _forward(self):
        from kairos import browser
        self._call(lambda: browser.session_do("forward"), self._on_after)

    def _reload(self):
        from kairos import browser
        self._call(lambda: browser.session_do("reload"), self._on_after)

    def _on_after(self, result):
        self.out.setPlainText(str(result))
        self.status.setText("Done.")
        self._refresh_info()

    def _list_inputs(self):
        self._call(lambda: self.engine.browser_list_inputs(), self._on_inputs,
                   busy="Reading inputs\u2026")

    def _on_inputs(self, items):
        self.out.setPlainText(json.dumps(items or [], indent=2))
        self.status.setText(f"{len(items or [])} input(s) found.")

    def _fill_form(self):
        try:
            fields = json.loads(self.form_edit.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.warning(self, "Browser Agent", f"Invalid JSON: {e}")
            return
        self._call(lambda: self.engine.browser_form(fields), self._on_after,
                   busy="Filling form\u2026")

    # -- design / captcha -------------------------------------------------
    def _run(self):
        goal = self.goal_edit.toPlainText().strip()
        if not goal:
            QMessageBox.warning(self, "Browser Agent", "Enter a design/browse goal.")
            return
        if not self.enable_chk.isChecked():
            self.enable_chk.setChecked(True)
        url = self.url_edit.text().strip()
        self.run_btn.setEnabled(False)
        self.status.setText("Running task\u2026")
        self.out.clear()
        self._design_worker = DesignWorker(self.engine, goal, url,
                                           vision=self.vision_chk.isChecked())
        self._design_worker.progress.connect(lambda t: self.status.setText(t))
        self._design_worker.finished.connect(self._design_done)
        self._design_worker.failed.connect(self._design_failed)
        self._design_worker.start()

    def _design_done(self, res):
        self.run_btn.setEnabled(True)
        self.status.setText("Done.")
        self.out.setPlainText(str(res.get("result", res)))
        self._refresh_info()

    def _design_failed(self, msg):
        self.run_btn.setEnabled(True)
        self.status.setText("Failed.")
        self.out.setPlainText(f"[Error] {msg}")

    def _detect_captcha(self):
        self._call(lambda: self.engine.browser_detect_captcha(), self._on_captcha,
                   busy="Checking for CAPTCHA\u2026")

    def _on_captcha(self, found):
        if found:
            self.status.setText(
                f"CAPTCHA detected: {', '.join(found)} \u2014 solve it in the "
                "browser window, then click 'Wait until CAPTCHA solved'.")
        else:
            self.status.setText("No CAPTCHA detected.")

    def _wait_captcha(self):
        self.status.setText("Waiting for you to solve the CAPTCHA in the browser\u2026")
        self._call(lambda: self.engine.browser_wait_captcha(300000),
                   lambda r: self.status.setText(str(r)))


# Backwards-compatible alias.
DesignerDialog = BrowserAgentDialog


def _open_path(path):
    import os
    import sys
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        else:
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(path))
    except Exception as e:
        QMessageBox.warning(None, "Kairos", f"Could not open {path}: {e}")


