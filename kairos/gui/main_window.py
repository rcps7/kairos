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
                               QScrollArea)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QTimer
from PySide6.QtGui import QAction, QFont, QColor, QPalette, QIcon, QTextCursor

from kairos.gui.voice_widgets import VoiceWorker, SpeakWorker, VoiceMeter, MoodIndicator

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


class LLMWorker(QThread):
    finished = Signal(str)

    def __init__(self, engine, prompt, task="chat"):
        super().__init__()
        self.engine = engine
        self.prompt = prompt
        self.task = task

    def run(self):
        try:
            if self.task == "reflect":
                reply = self.engine.reflect()
            else:
                reply = self.engine.ask_llm(self.prompt)
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
            marker = " * " if pid == active else "   "
            self.provider_list.addItem(f"{marker} {pid}   |   {model}   |   {key}")

    def add_provider(self):
        dlg = ProviderEditDialog(self)
        if dlg.exec():
            self.engine.llm.add_provider(dlg.provider_id, dlg.api_url, dlg.api_key, dlg.model)
            self.refresh()

    def set_active(self):
        item = self.provider_list.currentItem()
        if not item:
            return
        pid = item.text().strip().lstrip("* ").split(" ")[0]
        if self.engine.llm.set_active(pid):
            self.refresh()

    def remove_provider(self):
        item = self.provider_list.currentItem()
        if not item:
            return
        pid = item.text().strip().lstrip("* ").split(" ")[0]
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
        layout.addRow("Provider ID:", self.id_edit)
        layout.addRow("API URL:", self.url_edit)
        layout.addRow("API Key:", self.key_edit)
        layout.addRow("Model:", self.model_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self):
        self.provider_id = self.id_edit.text().strip()
        self.api_url = self.url_edit.text().strip()
        self.api_key = self.key_edit.text().strip()
        self.model = self.model_edit.text().strip()
        if not self.provider_id or not self.api_url:
            QMessageBox.warning(self, "Kairos", "Provider ID and API URL are required.")
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
        cfg = self.engine.config
        cfg["storage_root"] = path
        from kairos.config import save_config
        save_config(cfg)
        self.engine.config = cfg
        QMessageBox.information(self, "Kairos", f"Storage set to {path}")
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
        cfg = self.engine.config
        email_cfg = {
            "email": self.email_edit.text().strip(),
            "password": self.password_edit.text(),
            "imap_host": self.imap_edit.text().strip(),
            "imap_port": int(self.imap_port.text() or 993),
            "smtp_host": self.smtp_edit.text().strip(),
            "smtp_port": int(self.smtp_port.text() or 465),
        }
        cfg["email"] = email_cfg
        from kairos.config import save_config
        save_config(cfg)
        self.engine.config = cfg
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


class RetentionDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Retention - Delete Expired Items")
        self.setStyleSheet(_dialog_style())
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("Expired Items (older than retention period)")
        header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {GREEN};")
        layout.addWidget(header)

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


class KairosGUI(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
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
        edit_menu.addSeparator()
        edit_menu.addAction("Peripheral Control", self.open_peripheral_dialog)
        edit_menu.addAction("Retention (Delete Expired)", self.open_retention_dialog)
        edit_menu.addSeparator()
        edit_menu.addAction("Skills", self.open_skill_dialog)

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

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        actions = [
            ("Search", self._tool_search),
            ("Learn URL", self._tool_learn),
            ("Download", self._tool_download),
            ("Skills", self.open_skill_dialog),
            ("Providers", self.open_provider_dialog),
            ("Peripherals", self.open_peripheral_dialog),
            ("Self-Reflect", self.run_reflection),
        ]
        for label, handler in actions:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)

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
            "Self-Reflect",
            "Create / View Skills",
        ])
        self.skills_list.itemClicked.connect(self._on_skill_clicked)
        layout.addWidget(self.skills_list)

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
            btn = QPushButton(name)
            btn.setToolTip(skill.get("description", name))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {BG_BUTTON}; color: {TEXT}; "
                f"border: 1px solid {BORDER}; border-radius: 4px; padding: 6px 8px; "
                f"text-align: left; font-family: 'Segoe UI', sans-serif; }}"
                f"QPushButton:hover {{ background-color: {BG_BUTTON_HOVER}; color: {GREEN}; }}"
                f"QPushButton:pressed {{ background-color: {GREEN_DIM}; color: {BG_DARK}; }}"
            )
            btn.clicked.connect(lambda checked=False, n=name: self._run_skill_button(n))
            self.custom_skills_layout.addWidget(btn)

    def _run_skill_button(self, name):
        self.chat_display.append(f"<b style='color:{GREEN}'>Running skill:</b> {name}")
        self._run_bg(lambda: str(self.engine.run_skill(name)), f"Skill {name}")

    def _build_chat_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("CONSOLE")
        title.setStyleSheet(f"color: {GREEN}; font-weight: bold; font-family: 'Consolas', monospace;")
        self.active_llm_label = QLabel("")
        self.active_llm_label.setStyleSheet(f"color: {TEXT_GREY}; font-family: 'Segoe UI', sans-serif;")
        self.mood = MoodIndicator()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.active_llm_label)
        header.addSpacing(12)
        header.addWidget(self.mood)
        layout.addLayout(header)

        self.chat_display = QTextBrowser()
        self.chat_display.setReadOnly(True)
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setPlaceholderText("Kairos is ready. Type a message below...")
        layout.addWidget(self.chat_display, 1)

        self.voice_meter = VoiceMeter()
        self.voice_meter.setVisible(False)
        layout.addWidget(self.voice_meter)

        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your instruction here...")
        self.chat_input.returnPressed.connect(self.send_message)
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
        input_row.addWidget(self.talk_btn)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.clear_btn)
        layout.addLayout(input_row)

        return panel

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
            self.status_llm.setText(str(active))
            self.status_skills.setText(str(skills))
            self.status_storage.setText(str(storage))
            self.active_llm_label.setText(f"LLM: {active}")
        except Exception:
            pass

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
            "Self-Reflect": self.run_reflection,
            "Create / View Skills": self.open_skill_dialog,
        }
        handler = mapping.get(item.text())
        if handler:
            handler()

    def _tool_search(self):
        query, ok = self._prompt("Web Search", "Enter search query:")
        if ok and query:
            self.chat_display.append(f"<b style='color:{GREEN}'>Searching:</b> {query}")
            self._run_bg(lambda: self._fmt_search(self.engine.search_web(query, max_results=10)), "Search")

    def _tool_learn(self):
        url, ok = self._prompt("Learn From Page", "Enter URL to scrape and summarize:")
        if ok and url:
            self.chat_display.append(f"<b style='color:{GREEN}'>Learning:</b> {url}")
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
                self.chat_display.append(f"<b style='color:{GREEN}'>Downloading:</b> {url} ({fmt})")
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
    def _run_bg(self, fn, task_name):
        class Task(QThread):
            finished = Signal(str)

            def run(self):
                try:
                    self.finished.emit(str(fn()))
                except Exception as e:
                    self.finished.emit(f"[Error] {e}")

        worker = Task()
        worker.finished.connect(lambda r: self._append_result(task_name, r))
        worker.start()
        self._worker = worker

    def _append_result(self, task_name, result):
        self.chat_display.append(f"<b style='color:{GREEN}'>{task_name}:</b> {result}")

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def send_message(self):
        text = self.chat_input.text().strip()
        if not text:
            return
        self.chat_display.append(f"<b style='color:#58a6ff'>You:</b> {text}")
        self.chat_input.clear()
        self.chat_display.append(f"<b style='color:{GREEN}'>Kairos:</b> ...")
        self._set_mood("thinking")
        self._start_deep_thinking_timer()
        self.worker = LLMWorker(self.engine, text)
        self.worker.finished.connect(self.on_llm_reply)
        self.worker.start()

    def on_llm_reply(self, reply: str):
        self._stop_deep_thinking_timer()
        if reply.startswith("[Error]"):
            self._set_mood("error")
        else:
            self._set_mood("success")
        self.chat_display.append(f"<b style='color:{GREEN}'>Kairos:</b> {reply}")
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
        self.chat_display.append(f"<b style='color:{RED}'>Voice:</b> {msg}")
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
        self._thinking_elapsed = 0
        self._deep_timer = QTimer(self)
        self._deep_timer.timeout.connect(self._tick_thinking)
        self._deep_timer.start(1000)

    def _tick_thinking(self):
        self._thinking_elapsed += 1
        if self._thinking_elapsed >= 10:
            self._set_mood("deep_thinking")

    def _stop_deep_thinking_timer(self):
        if hasattr(self, "_deep_timer"):
            self._deep_timer.stop()
            self._deep_timer = None

    def new_session(self):
        self.chat_display.clear()
        self.chat_display.setPlaceholderText("Kairos is ready. Type a message below...")

    def clear_chat(self):
        """Clear only the on-screen chat window (no data is deleted)."""
        self.chat_display.clear()
        self.chat_display.setPlaceholderText("Kairos is ready. Type a message below...")

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def open_provider_dialog(self):
        ProviderDialog(self.engine, self).exec()
        self.refresh_status_bar()

    def open_storage_dialog(self):
        StorageDialog(self.engine, self).exec()
        self.refresh_status_bar()

    def open_email_dialog(self):
        EmailDialog(self.engine, self).exec()

    def open_peripheral_dialog(self):
        PeripheralDialog(self.engine, self).exec()

    def open_retention_dialog(self):
        RetentionDialog(self.engine, self).exec()

    def open_skill_dialog(self):
        SkillDialog(self.engine, self).exec()
        self.refresh_status_bar()
        self.refresh_skill_buttons()

    def run_reflection(self):
        self.chat_display.append(f"<b style='color:{GREEN}'>Kairos:</b> Reflecting on recent errors ...")
        self.worker = LLMWorker(self.engine, None, task="reflect")
        self.worker.finished.connect(self.on_llm_reply)
        self.worker.start()

    def show_lessons(self):
        lessons = self.engine.recent_lessons(5)
        if not lessons:
            self.chat_display.append(f"<b style='color:{GREEN}'>Kairos:</b> No lessons learned yet.")
            return
        self.chat_display.append(f"<b style='color:{GREEN}'>Kairos:</b> Recent lessons:")
        for l in lessons:
            self.chat_display.append(l)

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
