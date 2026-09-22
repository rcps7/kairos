import html
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
                               QScrollArea, QMenu)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QTimer
from PySide6.QtGui import QAction, QFont, QColor, QPalette, QIcon, QTextCursor

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


def _merge_save(mutate):
    """Apply a change to the on-disk config without clobbering other settings.

    Always reloads the current config first so changes made elsewhere (e.g. a
    provider added by LLMClient) are not lost.
    """
    from kairos.config import load_config, save_config
    cfg = load_config()
    mutate(cfg)
    save_config(cfg)
    return load_config()


class LLMWorker(QThread):
    finished = Signal(str)
    progress = Signal(str)

    def __init__(self, engine, prompt, task="chat", attachments=None):
        super().__init__()
        self.engine = engine
        self.prompt = prompt
        self.task = task
        self.attachments = attachments or []

    def run(self):
        try:
            if self.task == "reflect":
                reply = self.engine.reflect()
            else:
                reply = self.engine.chat(
                    self.prompt or "",
                    attachment_paths=self.attachments,
                    progress=lambda t: self.progress.emit(t),
                )
            self.finished.emit(reply)
        except Exception as e:
            self.finished.emit(f"[Error] {e}")


class SkillGenWorker(QThread):
    finished = Signal(str)

    def __init__(self, engine, name, description):
        super().__init__()
        self.engine = engine
        self.name = name
        self.description = description

    def run(self):
        try:
            code = self.engine.generate_skill(self.name, self.description)
            self.finished.emit(code)
        except Exception as e:
            self.finished.emit(f"[Error] {e}")


class UpdateCheckWorker(QThread):
    result = Signal(dict)

    def run(self):
        self.result.emit(updater.check_for_update())


class UpdateDownloadWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            import tempfile
            tmp = tempfile.mkdtemp(prefix="kairos_update_")
            updater.download_and_extract(self.url, tmp)
            root = updater.find_update_root(tmp)
            self.done.emit(str(root))
        except Exception as e:
            self.failed.emit(str(e))


class CouncilWorker(QThread):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine, prompt, members, attachments, mode):
        super().__init__()
        self.engine = engine
        self.prompt = prompt
        self.members = members
        self.attachments = attachments
        self.mode = mode

    def run(self):
        try:
            result = self.engine.council(
                self.prompt, members=self.members,
                attachment_paths=self.attachments, mode=self.mode,
                progress=lambda t: self.progress.emit(t),
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


def _dialog_style() -> str:
    return f"""
        QDialog {{ background-color: {BG_DARK}; }}
        QLabel {{ color: {TEXT}; font-family: 'Segoe UI', sans-serif; }}
        QLineEdit, QTextEdit, QListWidget, QComboBox {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 6px;
            font-family: 'Consolas', monospace;
        }}
        QLineEdit:focus {{ border: 1px solid {GREEN}; }}
        QListWidget::item:selected {{ background-color: {GREEN_DIM}; color: {BG_DARK}; }}
        QPushButton {{
            background-color: {BG_BUTTON};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 6px 14px;
            font-family: 'Segoe UI', sans-serif;
        }}
        QPushButton:hover {{ background-color: {BG_BUTTON_HOVER}; }}
        QPushButton:pressed {{ background-color: {GREEN_DIM}; color: {BG_DARK}; }}
    """


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


class PredictWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, engine, question, files, links, text, mode):
        super().__init__()
        self.engine = engine
        self.question = question
        self.files = files
        self.links = links
        self.text = text
        self.mode = mode

    def run(self):
        try:
            result = self.engine.predict(
                self.question, files=self.files, links=self.links,
                text=self.text, mode=self.mode
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


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


def _format_response(text: str) -> str:
    """Convert a response into HTML, preserving code blocks with indentation."""
    if "```" not in text:
        return html.escape(text).replace("\n", "<br>")

    parts = text.split("```")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                escaped = html.escape(part).replace("\n", "<br>")
                out.append(f"<span>{escaped}</span>")
        else:
            # Code block: strip an optional language tag on the first line.
            lines = part.split("\n")
            if lines and lines[0].strip() and not lines[0].strip().startswith(("import", "def", "print", "class")):
                # likely a language hint like "python"
                if len(lines[0].strip()) < 12 and " " not in lines[0].strip():
                    lines = lines[1:]
            code = "\n".join(lines).rstrip("\n")
            escaped_code = html.escape(code).replace(" ", "&nbsp;")
            escaped_code = escaped_code.replace("\n", "<br>")
            out.append(
                f"<span style='font-family: Consolas, monospace; background-color: {BG_INPUT}; "
                f"padding: 2px 4px;'>{escaped_code}</span>"
            )
    return "".join(out)


class MessageBubble(QFrame):
    """A single chat message with optional copy/edit buttons."""

    def __init__(self, gui, sender: str, text: str, role: str, color: str, raw_html: bool = False, parent=None):
        super().__init__(parent)
        self.gui = gui
        self.sender = sender
        self.raw_text = text
        self.role = role
        self.color = color
        self.raw_html = raw_html

        self.setObjectName("messageBubble")
        self.setStyleSheet(
            f"#messageBubble {{ background-color: {BG_PANEL}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Header row: sender + action buttons
        header = QHBoxLayout()
        header.setSpacing(4)
        sender_label = QLabel(sender)
        sender_label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-family: 'Segoe UI', sans-serif; font-size: 12px;"
        )
        header.addWidget(sender_label)
        header.addStretch()

        self.copy_btn = None
        self.edit_btn = None

        if role in ("kairos", "system"):
            self.copy_btn = self._small_icon("⧉", "Copy")
            self.copy_btn.clicked.connect(self.copy_text)
            header.addWidget(self.copy_btn)

        if role == "user":
            self.edit_btn = self._small_icon("✎", "Edit")
            self.edit_btn.clicked.connect(self.edit_text)
            header.addWidget(self.edit_btn)

        outer.addLayout(header)

        # Body
        self.body = QTextBrowser()
        self.body.setReadOnly(True)
        self.body.setOpenExternalLinks(True)
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.document().setDefaultStyleSheet(
            f"body {{ color: {TEXT}; font-family: 'Consolas', monospace; font-size: 13pt; "
            f"line-height: 160%; word-spacing: 2px; }}"
        )
        self.body.setHtml(self._render())
        self.body.document().setTextWidth(600)
        outer.addWidget(self.body)
        QTimer.singleShot(0, self._adjust_height)

    def _render(self) -> str:
        if self.raw_html:
            return self.raw_text
        if self.role in ("kairos", "system"):
            return _format_response(self.raw_text)
        return html.escape(self.raw_text).replace("\n", "<br>")

    def _adjust_height(self):
        width = self.body.viewport().width()
        if width <= 0:
            width = 600
        self.body.document().setTextWidth(width)
        height = self.body.document().size().height()
        self.body.setFixedHeight(int(height) + 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_height()

    def _small_icon(self, glyph: str, tip: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border: none; color: {TEXT_GREY}; "
            f"font-size: 13px; font-family: 'Segoe UI', sans-serif; }}"
            f"QPushButton:hover {{ color: {GREEN}; background-color: {BG_BUTTON_HOVER}; border-radius: 4px; }}"
        )
        return btn

    def copy_text(self):
        QApplication.clipboard().setText(self.raw_text)

    def edit_text(self):
        self.gui.edit_user_message(self.raw_text)

    def set_text(self, text: str):
        self.raw_text = text
        self.body.setHtml(self._render())
        self._adjust_height()


class OutputDialog(QDialog):
    """A resizable, copyable window for long/verified output."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setWindowTitle(title)
        self.setStyleSheet(_dialog_style())
        self.resize(900, 700)
        layout = QVBoxLayout(self)

        self.view = QTextBrowser()
        self.view.setReadOnly(True)
        self.view.setOpenExternalLinks(True)
        self.view.document().setDefaultStyleSheet(
            f"body {{ color: {TEXT}; font-family: 'Consolas', monospace; font-size: 12pt; "
            f"line-height: 155%; }} pre {{ background-color: {BG_INPUT}; }}"
        )
        self.view.setHtml(_format_response(text))
        layout.addWidget(self.view, 1)

        row = QHBoxLayout()
        copy_btn = QPushButton("Copy All")
        copy_btn.clicked.connect(self._copy)
        save_btn = QPushButton("Save…")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn)
        row.addWidget(save_btn)
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _copy(self):
        QApplication.clipboard().setText(self.text)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Output", "kairos_output.md",
                                              "Markdown (*.md);;Text (*.txt);;All files (*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.text)
            except Exception as e:
                QMessageBox.warning(self, "Kairos", f"Save failed: {e}")


class KairosGUI(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._deep_timer = None
        self._thinking_elapsed = 0
        self.setWindowTitle("KAIROS  -  Self-Evolving AI Agent")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.apply_stylesheet()
        self.init_ui()

    # ------------------------------------------------------------------
    # Stylesheet
    # ------------------------------------------------------------------
    def apply_stylesheet(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {BG_DARK}; }}
            QWidget {{ background-color: {BG_DARK}; color: {TEXT}; }}
            QMenuBar {{
                background-color: {BG_PANEL};
                color: {TEXT};
                border-bottom: 1px solid {BORDER};
                font-family: 'Segoe UI', sans-serif;
            }}
            QMenuBar::item {{ padding: 6px 14px; background: transparent; }}
            QMenuBar::item:selected {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}
            QMenu {{
                background-color: {BG_PANEL};
                color: {TEXT};
                border: 1px solid {BORDER};
            }}
            QMenu::item {{ padding: 6px 24px; }}
            QMenu::item:selected {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}
            QToolBar {{
                background-color: {BG_PANEL};
                border-bottom: 1px solid {BORDER};
                spacing: 6px;
                padding: 4px;
            }}
            QStatusBar {{ background-color: {BG_PANEL}; color: {TEXT_GREY}; border-top: 1px solid {BORDER}; }}
            QSplitter::handle {{ background-color: {BORDER}; width: 1px; }}
            QTextEdit, QListWidget {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {TEXT};
                font-family: 'Consolas', monospace;
            }}
            QTextEdit:focus, QListWidget:focus {{ border: 1px solid {GREEN}; }}
            QLineEdit {{
                background-color: {BG_INPUT};
                color: {GREEN};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                font-family: 'Consolas', monospace;
            }}
            QLineEdit:focus {{ border: 1px solid {GREEN}; }}
            QPushButton {{
                background-color: {BG_BUTTON};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 7px 16px;
                font-family: 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}
            QPushButton:pressed {{ background-color: {GREEN_DIM}; color: {BG_DARK}; }}
            QListWidget::item {{ padding: 8px; border-radius: 4px; }}
            QListWidget::item:hover {{ background-color: {BG_BUTTON_HOVER}; }}
            QListWidget::item:selected {{
                background-color: {GREEN_DIM};
                color: {BG_DARK};
            }}
            QGroupBox {{
                border: 1px solid {BORDER};
                border-radius: 6px;
                margin-top: 10px;
                color: {GREEN};
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)

    # ------------------------------------------------------------------
    # Main UI
    # ------------------------------------------------------------------
    def init_ui(self):
        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()

        splitter = QSplitter(Qt.Horizontal)

        # --- Left panel: skill tools ---
        splitter.addWidget(self._build_left_panel())
        # --- Center panel: chat ---
        splitter.addWidget(self._build_chat_panel())
        # --- Right panel: system info / details ---
        splitter.addWidget(self._build_right_panel())

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([190, 850, 240])

        self.setCentralWidget(splitter)

        self._apply_character_capabilities()

        # Check for updates (at most once per day).
        QTimer.singleShot(1500, self.maybe_auto_check_updates)

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------
    def _build_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("New Session", self.new_session, "Ctrl+N")
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close, "Alt+F4")
        kill_action = QAction("Kill Switch (Emergency)", self)
        kill_action.triggered.connect(self.emergency_kill)
        file_menu.addSeparator()
        file_menu.addAction(kill_action)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction("LLM Providers", self.open_provider_dialog)
        edit_menu.addAction("Storage Settings", self.open_storage_dialog)
        edit_menu.addAction("Email Settings", self.open_email_dialog)
        edit_menu.addAction("MiroFish Settings", self.open_mirofish_dialog)
        edit_menu.addSeparator()
        edit_menu.addAction("Peripheral Control", self.open_peripheral_dialog)
        self._peripheral_action = edit_menu.actions()[-1]
        edit_menu.addAction("Retention (Delete Expired)", self.open_retention_dialog)
        edit_menu.addSeparator()
        self._skills_action = edit_menu.addAction("Skills", self.open_skill_dialog)
        edit_menu.addAction("Agent Character\u2026", self.open_character_dialog)

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("Predictive Engine", self.open_predict_dialog)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction("Self-Reflect", self.run_reflection)
        view_menu.addAction("Show Lessons", self.show_lessons)
        view_menu.addSeparator()
        view_menu.addAction("Refresh Status", self.refresh_status_bar)

        window_menu = menubar.addMenu("&Window")
        window_menu.addAction("Minimize", self.showMinimized)
        window_menu.addAction("Maximize", self._toggle_maximize)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("About Kairos", self.show_about)

        # --- Top-right update button ---
        self.update_btn = QPushButton("Check for updates")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setStyleSheet(
            f"QPushButton {{ background-color: {BG_BUTTON}; color: {TEXT}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; padding: 3px 10px; margin-right: 6px; }}"
            f"QPushButton:hover {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}"
        )
        self.update_btn.clicked.connect(self.on_update_button)
        self._update_info = None
        menubar.setCornerWidget(self.update_btn, Qt.TopRightCorner)

    # ------------------------------------------------------------------
    # Update checker
    # ------------------------------------------------------------------
    def maybe_auto_check_updates(self):
        """Check for updates at most once per day."""
        try:
            last = float(self.engine.config.get("update", {}).get("last_check", 0))
        except Exception:
            last = 0
        if time.time() - last >= 86400:
            self._check_updates(silent=True)

    def on_update_button(self):
        info = self._update_info
        if info and info.get("update_available"):
            self._confirm_and_install(info)
        else:
            self._check_updates(silent=False)

    def _check_updates(self, silent=True):
        self._update_silent = silent
        self.update_btn.setText("Checking...")
        self.update_btn.setEnabled(False)
        self._update_worker = UpdateCheckWorker()
        self._update_worker.result.connect(self._on_update_result)
        self._update_worker.start()

    def _on_update_result(self, info: dict):
        self.update_btn.setEnabled(True)
        self._update_info = info

        # Record the check time (merge-safe: never clobber providers/settings)
        try:
            self.engine.config = _merge_save(
                lambda c: c.setdefault("update", {}).__setitem__("last_check", time.time())
            )
        except Exception:
            pass

        if info.get("error"):
            self.update_btn.setText("Check for updates")
            if not self._update_silent:
                QMessageBox.information(self, "Updates", f"Could not check for updates:\n{info['error']}")
            return

        if info.get("update_available"):
            self.update_btn.setText("⬆ Update available")
            self.update_btn.setStyleSheet(
                f"QPushButton {{ background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold; "
                f"border: 1px solid {GREEN}; border-radius: 4px; padding: 3px 10px; margin-right: 6px; }}"
            )
        else:
            self.update_btn.setText("✓ Up to date")
            self.update_btn.setStyleSheet(
                f"QPushButton {{ background-color: {BG_BUTTON}; color: {TEXT_GREY}; "
                f"border: 1px solid {BORDER}; border-radius: 4px; padding: 3px 10px; margin-right: 6px; }}"
            )

    def _confirm_and_install(self, info):
        msg = (
            f"A new version of Kairos is available.\n\n"
            f"Installed: {info.get('local_version')}\n"
            f"New: {info.get('latest_version')}\n\n"
        )
        if info.get("notes"):
            msg += f"Release notes:\n{info['notes'][:800]}\n\n"
        msg += "Install now? Kairos will close, update itself, and restart."
        if QMessageBox.question(self, "Install Update", msg,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._install_update(info)

    def _install_update(self, info):
        url = info.get("download_url")
        if not url:
            QMessageBox.warning(self, "Update", "No download is available for this release.")
            return
        self.update_btn.setText("Downloading...")
        self.update_btn.setEnabled(False)
        self._dl_worker = UpdateDownloadWorker(url)
        self._dl_worker.done.connect(self._on_update_downloaded)
        self._dl_worker.failed.connect(self._on_update_failed)
        self._dl_worker.start()

    def _on_update_downloaded(self, update_root):
        try:
            bat = updater.create_updater_batch(update_root)
            updater.launch_updater(bat)
        except Exception as e:
            QMessageBox.warning(self, "Update", f"Failed to start the updater:\n{e}")
            self.update_btn.setEnabled(True)
            self.update_btn.setText("⬆ Update available")
            return
        # Hand over to the updater batch and exit.
        from PySide6.QtWidgets import QApplication as _QApp
        _QApp.quit()

    def _on_update_failed(self, msg):
        QMessageBox.warning(self, "Update", f"Download failed:\n{msg}")
        self.update_btn.setEnabled(True)
        self.update_btn.setText("⬆ Update available")

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        actions = [
            ("Search", "web_search", self._tool_search),
            ("Learn URL", "learn_web", self._tool_learn),
            ("Download", "download_media", self._tool_download),
            ("Predict", "predict", self.open_predict_dialog),
            ("Skills", "skills_manage", self.open_skill_dialog),
            ("Providers", None, self.open_provider_dialog),
            ("Peripherals", "peripherals", self.open_peripheral_dialog),
            ("Character", None, self.open_character_dialog),
            ("Self-Reflect", None, self.run_reflection),
        ]
        self._toolbar_buttons = {}
        for label, capability, handler in actions:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)
            self._toolbar_buttons[label] = (btn, capability)

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------
    def _build_left_panel(self):
        panel = QWidget()
        panel.setFixedWidth(210)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("SKILL TOOLS")
        title.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-family: 'Consolas', monospace;")
        layout.addWidget(title)

        self.skills_list = QListWidget()
        self.skills_list.addItems([
            "Web Search",
            "Learn From Page",
            "Email",
            "Downloads",
            "Peripheral Control",
            "Predictive Engine",
            "Self-Reflect",
            "Create / View Skills",
        ])
        self.skills_list.itemClicked.connect(self._on_skill_clicked)
        self.skills_list.setToolTip("Tools available to the active character")
        layout.addWidget(self.skills_list)
        self._left_cap_map = {
            "Web Search": "web_search",
            "Learn From Page": "learn_web",
            "Email": "email_read",
            "Downloads": "download_media",
            "Peripheral Control": "peripherals",
            "Predictive Engine": "predict",
            "Self-Reflect": None,
            "Create / View Skills": "skills_manage",
        }

        # --- Custom skills as clickable buttons ---
        custom_title = QLabel("MY SKILLS")
        custom_title.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-family: 'Consolas', monospace;")
        layout.addWidget(custom_title)

        self.custom_skills_container = QWidget()
        self.custom_skills_layout = QVBoxLayout(self.custom_skills_container)
        self.custom_skills_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_skills_layout.setSpacing(4)

        self.custom_skills_scroll = QScrollArea()
        self.custom_skills_scroll.setWidgetResizable(True)
        self.custom_skills_scroll.setWidget(self.custom_skills_container)
        self.custom_skills_scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.custom_skills_scroll, 1)

        layout.addStretch()
        self.refresh_skill_buttons()
        return panel

    def refresh_skill_buttons(self):
        """Rebuild the clickable buttons for user-created skills."""
        while self.custom_skills_layout.count():
            item = self.custom_skills_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        skills = self.engine.list_skills()
        if not skills:
            lbl = QLabel("No custom skills yet.\nUse 'Create / View Skills'.")
            lbl.setStyleSheet(f"color: {TEXT_GREY}; font-family: 'Segoe UI', sans-serif;")
            lbl.setWordWrap(True)
            self.custom_skills_layout.addWidget(lbl)
            return

        for skill in skills:
            name = skill["name"]
            try:
                ok = self.engine.can("skills_run") and self.engine.characters.allows_skill(name)
            except Exception:
                ok = True
            btn = QPushButton(name)
            btn.setToolTip(skill.get("description", name) if ok else "Not available for the active character")
            btn.setEnabled(ok)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {BG_BUTTON}; color: {TEXT}; "
                f"border: 1px solid {BORDER}; border-radius: 4px; padding: 6px 8px; "
                f"text-align: left; font-family: 'Segoe UI', sans-serif; }}"
                f"QPushButton:hover {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}"
                f"QPushButton:pressed {{ background-color: {GREEN_DIM}; color: {BG_DARK}; }}"
                f"QPushButton:disabled {{ color: {TEXT_GREY}; }}"
            )
            btn.clicked.connect(lambda checked=False, n=name: self._run_skill_button(n))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, n=name: self._skill_button_menu(n, pos)
            )
            self.custom_skills_layout.addWidget(btn)

    def _skill_button_menu(self, name, pos):
        menu = QMenu(self)
        run_action = menu.addAction("Run")
        edit_action = menu.addAction("Edit Code")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.custom_skills_container.mapToGlobal(pos))
        if action == run_action:
            self._run_skill_button(name)
        elif action == edit_action:
            self.open_skill_dialog()
        elif action == delete_action:
            self._delete_skill_by_name(name)

    def _delete_skill_by_name(self, name):
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
            self.refresh_skill_buttons()
            self.refresh_status_bar()
        except Exception as e:
            QMessageBox.warning(self, "Kairos", f"Delete failed: {e}")

    def _run_skill_button(self, name):
        self._append_bubble("Running skill", name, "system", GREEN)
        # Run on the main thread: skills may open Qt dialogs, which must
        # never be created from a background thread.
        try:
            result = self.engine.run_skill(name)
            self._append_bubble(f"Skill {name}", str(result), "kairos", GREEN)
        except Exception as e:
            self._append_bubble(f"Skill {name} error", str(e), "system", RED)

    def _build_chat_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("CONSOLE")
        title.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-family: 'Consolas', monospace;")
        self.active_llm_label = QLabel("")
        self.active_llm_label.setStyleSheet(f"color: {TEXT_GREY}; font-family: 'Segoe UI', sans-serif;")
        self.character_label = QLabel("")
        self.character_label.setStyleSheet(f"color: {GREEN}; font-family: 'Segoe UI', sans-serif;")
        self.mood = MoodIndicator()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.character_label)
        header.addSpacing(12)
        header.addWidget(self.active_llm_label)
        header.addSpacing(12)
        header.addWidget(self.mood)
        layout.addLayout(header)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 6, 0)
        self.chat_layout.setSpacing(6)
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_container)
        layout.addWidget(self.chat_scroll, 1)

        self.voice_meter = VoiceMeter()
        self.voice_meter.setVisible(False)
        layout.addWidget(self.voice_meter)

        # --- Council controls ---
        self.attachments = []
        council_row = QHBoxLayout()
        self.council_check = QCheckBox("Council (multi-LLM)")
        self.council_check.setToolTip("Use three LLMs that discuss, divide, and verify the task")
        self.council_check.setStyleSheet(f"color: {TEXT}; font-family: 'Segoe UI', sans-serif;")
        council_row.addWidget(self.council_check)
        self.member_combos = []
        for i in range(3):
            combo = QComboBox()
            combo.setEnabled(False)
            council_row.addWidget(combo)
            self.member_combos.append(combo)
        self.refresh_council_members()
        self.council_check.toggled.connect(self._toggle_council_controls)

        self.attachments_label = QLabel("")
        self.attachments_label.setStyleSheet(f"color: {TEXT_GREY}; font-family: 'Segoe UI', sans-serif;")
        council_row.addStretch()
        council_row.addWidget(self.attachments_label)
        layout.addLayout(council_row)

        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your instruction here...")
        self.chat_input.returnPressed.connect(self.send_message)
        self.attach_btn = QPushButton("📎 Attach")
        self.attach_btn.setToolTip("Attach files or a folder (PDF, DOCX, TXT, CSV, XLSX, images)")
        self.attach_btn.clicked.connect(self._show_attach_menu)
        self.talk_btn = QPushButton("Talk")
        self.talk_btn.setCheckable(True)
        self.talk_btn.clicked.connect(self.toggle_talk)
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(
            f"background-color: {GREEN_DIM}; color: {BG_DARK}; font-weight: bold;"
        )
        self.send_btn.clicked.connect(self.send_message)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_chat)
        input_row.addWidget(self.chat_input, 1)
        input_row.addWidget(self.attach_btn)
        input_row.addWidget(self.talk_btn)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.clear_btn)
        layout.addLayout(input_row)

        return panel

    def _toggle_council_controls(self, checked):
        self.refresh_council_members()
        for combo in self.member_combos:
            combo.setEnabled(checked)

    def refresh_council_members(self):
        """Repopulate the council member dropdowns from configured providers."""
        try:
            providers = self.engine.list_providers()
        except Exception:
            providers = []
        saved = self.engine.config.get("council", {}).get("members", [])
        for i, combo in enumerate(self.member_combos):
            current = combo.currentData() or combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for pid in providers:
                combo.addItem(pid, pid)
            target = None
            if i < len(saved) and saved[i] in providers:
                target = saved[i]
            elif current in providers:
                target = current
            elif i < len(providers):
                target = providers[i]
            if target:
                combo.setCurrentText(target)
            combo.blockSignals(False)

    def _show_attach_menu(self):
        menu = QMenu(self)
        files_action = menu.addAction("Attach Files…")
        folder_action = menu.addAction("Attach Folder…")
        clear_action = menu.addAction("Clear Attachments")
        action = menu.exec(self.attach_btn.mapToGlobal(self.attach_btn.rect().bottomLeft()))
        if action == files_action:
            self._attach_files()
        elif action == folder_action:
            self._attach_folder()
        elif action == clear_action:
            self.attachments = []
            self._update_attachment_label()

    def _attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach files", "",
            "Documents (*.pdf *.docx *.txt *.md *.csv *.xlsx *.xls *.py *.json *.log);;"
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)"
        )
        if paths:
            self.attachments.extend(paths)
            self._update_attachment_label()

    def _attach_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Attach folder")
        if folder:
            self.attachments.append(folder)
            self._update_attachment_label()

    def _update_attachment_label(self):
        n = len(self.attachments)
        self.attachments_label.setText(f"{n} attachment(s) attached" if n else "")

    def _build_right_panel(self):
        panel = QWidget()
        panel.setFixedWidth(250)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("SYSTEM")
        title.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-family: 'Consolas', monospace;")
        layout.addWidget(title)

        info = QGroupBox("Status")
        info_layout = QFormLayout(info)
        self.status_llm = QLabel("-")
        self.status_llm.setStyleSheet(f"color: {GREEN};")
        self.status_storage = QLabel("-")
        self.status_storage.setWordWrap(True)
        self.status_storage.setStyleSheet(f"color: {TEXT_GREY};")
        self.status_skills = QLabel("-")
        self.status_skills.setStyleSheet(f"color: {TEXT_GREY};")
        self.status_character = QLabel("-")
        self.status_character.setStyleSheet(f"color: {GREEN};")
        info_layout.addRow("Character:", self.status_character)
        info_layout.addRow("LLM:", self.status_llm)
        info_layout.addRow("Skills:", self.status_skills)
        info_layout.addRow("Storage:", self.status_storage)
        layout.addWidget(info)

        actions = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions)
        quick = [
            ("Self-Reflect", self.run_reflection),
            ("Show Lessons", self.show_lessons),
            ("LLM Providers", self.open_provider_dialog),
            ("Storage", self.open_storage_dialog),
            ("Email", self.open_email_dialog),
            ("Peripherals", self.open_peripheral_dialog),
            ("Retention", self.open_retention_dialog),
        ]
        for label, handler in quick:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            actions_layout.addWidget(btn)
        layout.addWidget(actions)

        danger = QGroupBox("Emergency")
        danger_layout = QVBoxLayout(danger)
        kill_btn = QPushButton("KILL SWITCH")
        kill_btn.setStyleSheet(
            f"background-color: {RED}; color: white; font-weight: bold;"
        )
        kill_btn.clicked.connect(self.emergency_kill)
        danger_layout.addWidget(kill_btn)
        layout.addWidget(danger)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------
    def _build_status_bar(self):
        self.statusBar().showMessage("Ready")
        self.refresh_status_bar()

    def refresh_status_bar(self):
        try:
            active = self.engine.llm.active_provider
            skills = len(self.engine.list_skills())
            storage = self.engine.config.get("storage_root", "-")
            prof = self.engine.characters.active()
            char_name = prof.get("name", "General")
            self.status_llm.setText(str(active))
            self.status_skills.setText(str(skills))
            self.status_storage.setText(str(storage))
            self.status_character.setText(char_name)
            self.active_llm_label.setText(f"LLM: {active}")
            self.character_label.setText(f"Character: {char_name}")
        except Exception:
            pass

    def _apply_character_capabilities(self):
        """Enable/disable available tools to match the active character."""
        try:
            caps = self.engine.character_capabilities()
        except Exception:
            caps = None

        def allowed(cap):
            return cap is None or caps is None or cap in caps

        # Toolbar
        for label, (btn, cap) in getattr(self, "_toolbar_buttons", {}).items():
            ok = allowed(cap)
            btn.setEnabled(ok)
            btn.setToolTip("" if ok else "Not available for the active character")

        # Left panel tool list
        for i in range(self.skills_list.count()):
            item = self.skills_list.item(i)
            cap = self._left_cap_map.get(item.text())
            ok = allowed(cap)
            if ok:
                item.setFlags(item.flags() | Qt.ItemIsEnabled)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)

        # Council checkbox
        try:
            self.council_check.setEnabled(allowed("council"))
        except Exception:
            pass

        # Menu actions
        try:
            self._skills_action.setEnabled(allowed("skills_manage"))
        except Exception:
            pass
        try:
            self._peripheral_action.setEnabled(allowed("peripherals"))
        except Exception:
            pass

        # Custom skill buttons
        self.refresh_skill_buttons()

    # ------------------------------------------------------------------
    # Toolbar / skill handlers
    # ------------------------------------------------------------------
    def _on_skill_clicked(self, item):
        mapping = {
            "Web Search": self._tool_search,
            "Learn From Page": self._tool_learn,
            "Email": self.open_email_dialog,
            "Downloads": self._tool_download,
            "Peripheral Control": self.open_peripheral_dialog,
            "Predictive Engine": self.open_predict_dialog,
            "Self-Reflect": self.run_reflection,
            "Create / View Skills": self.open_skill_dialog,
        }
        handler = mapping.get(item.text())
        if handler:
            handler()

    def _tool_search(self):
        query, ok = self._prompt("Web Search", "Enter search query:")
        if ok and query:
            self._append_bubble("Searching", query, "system", GREEN)
            self._run_bg(lambda: self._fmt_search(self.engine.search_web(query, max_results=10)), "Search", raw_html=True)

    def _tool_learn(self):
        url, ok = self._prompt("Learn From Page", "Enter URL to scrape and summarize:")
        if ok and url:
            self._append_bubble("Learning", url, "system", GREEN)
            self._run_bg(lambda: self._safe_learn(url), "Learn")

    def _safe_learn(self, url):
        try:
            return self._fmt_learn(self.engine.learn_from_page(url))
        except Exception as e:
            return f"Could not learn from this link: {e}"

    def _tool_download(self):
        url, ok = self._prompt("Download", "Enter media URL:")
        if ok and url:
            fmt, ok2 = self._prompt("Download", "Format (mp3 / mp4):", default="mp4")
            if ok2:
                self._append_bubble("Downloading", f"{url} ({fmt})", "system", GREEN)
                self._run_bg(
                    lambda: str(self.engine.download_media(url, fmt)), "Download"
                )

    def _fmt_search(self, results):
        if not results:
            return "No results found."
        items = []
        for i, r in enumerate(results[:10], 1):
            title = html.escape(r.get("title") or "Untitled")
            url = r.get("url") or ""
            desc = html.escape(r.get("description") or "").strip()
            items.append(
                f"<b>{i}. {title}</b><br>"
                f"<a href=\"{url}\" style=\"color:#58a6ff;\">{url}</a><br>"
                + (f"<span style=\"color:{TEXT_GREY};\">{desc}</span>" if desc else "")
            )
        return "<br>".join(items)

    def _fmt_learn(self, result):
        return f"Learned: {result['title']}\n\n{result['summary']}"

    def _prompt(self, title, label, default=""):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, label, text=default)

    # ------------------------------------------------------------------
    # Background task runner
    # ------------------------------------------------------------------
    def _run_bg(self, fn, task_name, raw_html=False):
        class Task(QThread):
            finished = Signal(str)

            def run(self):
                try:
                    self.finished.emit(str(fn()))
                except Exception as e:
                    self.finished.emit(f"[Error] {e}")

        worker = Task()
        worker.finished.connect(lambda r: self._append_result(task_name, r, raw_html))
        worker.start()
        self._worker = worker

    def _append_result(self, task_name, result, raw_html=False):
        self._append_bubble(f"{task_name}", result, "system", GREEN, raw_html=raw_html)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def _append_bubble(self, sender, text, role, color, raw_html=False):
        bubble = MessageBubble(self, sender, text, role, color, raw_html=raw_html)
        # insert before the trailing stretch item
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self._scroll_chat_bottom()
        return bubble

    def _scroll_chat_bottom(self):
        QTimer.singleShot(0, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))

    def _clear_bubbles(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def edit_user_message(self, text):
        self.chat_input.setText(text)
        self.chat_input.setFocus()

    def send_message(self):
        text = self.chat_input.text().strip()
        if not text and not self.attachments:
            return
        if self.council_check.isChecked():
            self._send_council(text)
            return
        attachments = list(self.attachments)
        self._append_bubble("You", text or "(attachments)", "user", "#58a6ff")
        if attachments:
            self._append_bubble("Attachments", "\n".join(str(a) for a in attachments), "system", GREEN)
            self.attachments = []
            self._update_attachment_label()
        self.chat_input.clear()
        self._pending_kairos_bubble = self._append_bubble("Kairos", "...", "kairos", GREEN)
        self._set_mood("thinking")
        self._start_deep_thinking_timer()
        self.worker = LLMWorker(self.engine, text, attachments=attachments)
        self.worker.finished.connect(self.on_llm_reply)
        self.worker.progress.connect(
            lambda t: self._append_bubble("Kairos", t, "system", TEXT_GREY)
        )
        self.worker.start()

    def _send_council(self, text):
        members = [c.currentData() or c.currentText() for c in self.member_combos if (c.currentData() or c.currentText())]
        members = [m for m in members if m]
        if len(members) < 2:
            QMessageBox.warning(self, "Council", "Need at least two providers configured for council mode.")
            return
        try:
            self.engine.config = _merge_save(
                lambda c: c.setdefault("council", {}).__setitem__("members", members)
            )
        except Exception:
            pass
        self._append_bubble("You", text, "user", "#58a6ff")
        if self.attachments:
            self._append_bubble("Attachments", "\n".join(str(a) for a in self.attachments), "system", GREEN)
        self.chat_input.clear()
        self._set_mood("thinking")
        self._start_deep_thinking_timer()
        self._append_bubble("Council", f"Members: {', '.join(members)}", "system", GREEN)
        self.council_worker = CouncilWorker(self.engine, text, members, list(self.attachments), "standard")
        self.council_worker.progress.connect(lambda t: self._append_bubble("Council", t, "system", TEXT_GREY))
        self.council_worker.finished.connect(self._on_council_done)
        self.council_worker.failed.connect(self._on_council_failed)
        self.council_worker.start()

    def _on_council_done(self, result: dict):
        self._stop_deep_thinking_timer()
        self._set_mood("success")
        final = result.get("final", "")
        primary = result.get("primary", "?")
        self._append_bubble("Kairos", f"[Council — primary: {primary}]\n\n{final}", "kairos", GREEN)
        OutputDialog("Kairos Council Result", final, self).exec()
        self.attachments = []
        self._update_attachment_label()
        QTimer.singleShot(2500, self._reset_mood)

    def _on_council_failed(self, msg: str):
        self._stop_deep_thinking_timer()
        self._set_mood("error")
        self._append_bubble("Council error", msg, "system", RED)
        QTimer.singleShot(2500, self._reset_mood)

    def on_llm_reply(self, reply: str):
        self._stop_deep_thinking_timer()
        if reply.startswith("[Error]"):
            self._set_mood("error")
        else:
            self._set_mood("success")
        if getattr(self, "_pending_kairos_bubble", None):
            self._pending_kairos_bubble.set_text(reply)
            self._pending_kairos_bubble = None
        else:
            self._append_bubble("Kairos", reply, "kairos", GREEN)
        if getattr(self, "_voice_reply", False):
            self._voice_reply = False
            self.speak_reply(reply)
        QTimer.singleShot(2500, self._reset_mood)

    # ------------------------------------------------------------------
    # Voice (speech-to-text + text-to-speech + meter + mood)
    # ------------------------------------------------------------------
    def toggle_talk(self):
        if self.talk_btn.isChecked():
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self):
        self._stop_speaking()
        self.voice_meter.setVisible(True)
        self._set_mood("listening")
        self.talk_btn.setText("Stop")
        self.voice_worker = VoiceWorker()
        self.voice_worker.level.connect(self.voice_meter.set_level)
        self.voice_worker.result.connect(self._on_voice_result)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()

    def _stop_listening(self):
        if hasattr(self, "voice_worker") and self.voice_worker is not None:
            self.voice_worker.stop()
            self.voice_worker = None
        self.talk_btn.setChecked(False)
        self.talk_btn.setText("Talk")
        self.voice_meter.setVisible(False)
        self.voice_meter.set_level(0.0)

    def _on_voice_result(self, text):
        self._stop_listening()
        if text and text.strip():
            self.chat_input.setText(text.strip())
            self._voice_reply = True
            self.send_message()

    def _on_voice_error(self, msg):
        self._stop_listening()
        self._set_mood("error")
        self._append_bubble("Voice", msg, "system", RED)
        QTimer.singleShot(2000, self._reset_mood)

    def speak_reply(self, text):
        clean = text.replace("[Error]", "").strip()
        if not clean:
            return
        self._speaking = True
        self.voice_meter.setVisible(True)
        self._set_mood("speaking")
        self.speak_worker = SpeakWorker(clean)
        self.speak_worker.finished_speaking.connect(self._on_speak_finished)
        self.speak_worker.start()
        self._speak_anim_timer = QTimer(self)
        self._speak_anim_timer.timeout.connect(self._speak_pulse)
        self._speak_anim_timer.start(80)

    def _speak_pulse(self):
        if not getattr(self, "_speaking", False):
            return
        v = 0.5 + 0.5 * math.sin(time.time() * 8)
        self.voice_meter.set_level(max(0.1, v))

    def _on_speak_finished(self):
        self._speaking = False
        if hasattr(self, "_speak_anim_timer"):
            self._speak_anim_timer.stop()
        self.voice_meter.set_level(0.0)
        self.voice_meter.setVisible(False)
        if self.mood.mood() == "speaking":
            self._set_mood("success")

    def _stop_speaking(self):
        self._speaking = False
        if hasattr(self, "_speak_anim_timer"):
            self._speak_anim_timer.stop()
        if hasattr(self, "speak_worker") and self.speak_worker is not None:
            try:
                self.speak_worker.requestInterruption()
            except Exception:
                pass

    def _set_mood(self, mood):
        self.mood.set_mood(mood)

    def _reset_mood(self):
        if self.mood.mood() not in ("listening", "speaking"):
            self._set_mood("idle")

    def _start_deep_thinking_timer(self):
        self._stop_deep_thinking_timer()
        self._thinking_elapsed = 0
        self._deep_timer = QTimer(self)
        self._deep_timer.timeout.connect(self._tick_thinking)
        self._deep_timer.start(1000)

    def _tick_thinking(self):
        self._thinking_elapsed += 1
        if self._thinking_elapsed >= 10:
            self._set_mood("deep_thinking")

    def _stop_deep_thinking_timer(self):
        timer = getattr(self, "_deep_timer", None)
        if timer is not None:
            timer.stop()
        self._deep_timer = None

    def new_session(self):
        self._clear_bubbles()

    def clear_chat(self):
        """Clear only the on-screen chat window (no data is deleted)."""
        self._clear_bubbles()

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def open_provider_dialog(self):
        ProviderDialog(self.engine, self).exec()
        self.engine.reload_llm()
        from kairos.config import load_config
        self.engine.config = load_config()
        self.refresh_status_bar()
        self.refresh_council_members()

    def open_storage_dialog(self):
        StorageDialog(self.engine, self).exec()
        self.refresh_status_bar()
        self._apply_character_capabilities()

    def open_email_dialog(self):
        EmailDialog(self.engine, self).exec()

    def open_mirofish_dialog(self):
        MiroFishDialog(self.engine, self).exec()

    def open_peripheral_dialog(self):
        PeripheralDialog(self.engine, self).exec()

    def open_retention_dialog(self):
        RetentionDialog(self.engine, self).exec()

    def open_predict_dialog(self):
        PredictDialog(self.engine, self).exec()

    def open_skill_dialog(self):
        SkillDialog(self.engine, self).exec()
        self.refresh_status_bar()
        self.refresh_skill_buttons()

    def open_character_dialog(self):
        before = self.engine.active_character
        CharacterDialog(self.engine, self).exec()
        from kairos.config import load_config
        self.engine.config = load_config()
        self.engine.active_character = self.engine.characters.active_id
        self.refresh_status_bar()
        self._apply_character_capabilities()
        if self.engine.active_character != before:
            prof = self.engine.characters.active()
            msg = f"Now operating as: {prof.get('name', self.engine.active_character)}"
            if prof.get("disclaimer"):
                msg += f"\n\n{prof['disclaimer']}"
            self._append_bubble("Character", msg, "system", GREEN)

    def run_reflection(self):
        self._pending_kairos_bubble = self._append_bubble("Kairos", "Reflecting on recent errors ...", "kairos", GREEN)
        self._set_mood("thinking")
        self._start_deep_thinking_timer()
        self.worker = LLMWorker(self.engine, None, task="reflect")
        self.worker.finished.connect(self.on_llm_reply)
        self.worker.start()

    def show_lessons(self):
        lessons = self.engine.recent_lessons(5)
        if not lessons:
            self._append_bubble("Kairos", "No lessons learned yet.", "kairos", GREEN)
            return
        self._append_bubble("Kairos", "Recent lessons:", "kairos", GREEN)
        for l in lessons:
            self._append_bubble("Kairos", l, "kairos", GREEN)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def show_about(self):
        QMessageBox.information(
            self, "About Kairos",
            "KAIROS - Self-Evolving AI Agent\n\n"
            "A lightweight, self-improving agent with web search,\n"
            "knowledge library, media download, email, peripheral control,\n"
            "and a watchdog kill switch.\n\n"
            "MIT License",
        )

    def emergency_kill(self):
        confirm = QMessageBox.question(
            self, "Kairos Kill Switch",
            "Shut down Kairos immediately?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.engine.emergency_kill()
