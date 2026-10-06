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
from .dialogs import *  # noqa

class KairosGUI(QMainWindow):
    sig_collab_incoming = Signal(object)
    sig_collab_connected = Signal(object)
    sig_collab_chat = Signal(object, str)
    sig_collab_event = Signal(str)
    sig_collab_file_offer = Signal(object, object)
    sig_collab_file_done = Signal(object, object)
    sig_collab_llm_task = Signal(object, object)
    sig_collab_video = Signal(bytes)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._deep_timer = None
        self._thinking_elapsed = 0
        self.collab_windows = {}
        try:
            self._invoker = _MainThreadInvoker()
            engine.main_thread_caller = self._invoker
        except Exception:
            self._invoker = None
        self.sig_collab_incoming.connect(self._on_collab_incoming)
        self.sig_collab_connected.connect(self._on_collab_connected)
        self.sig_collab_chat.connect(self._on_collab_chat)
        self.sig_collab_event.connect(lambda t: self.statusBar().showMessage(t, 5000))
        self.setWindowTitle("KAIROS  -  Self-Evolving AI Agent")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.apply_stylesheet()
        self.init_ui()
        self._wire_collaboration()

    def _wire_collaboration(self):
        collab = getattr(self.engine, "collab", None)
        if not collab:
            return
        self.engine.on_collab_incoming = lambda req: self.sig_collab_incoming.emit(req)
        self.engine.on_collab_connected = lambda s: self.sig_collab_connected.emit(s)
        self.engine.on_collab_chat = lambda s, t: self.sig_collab_chat.emit(s, t)
        self.engine.on_collab_event = lambda t: self.sig_collab_event.emit(t)
        self.engine.on_collab_file_offer = lambda s, o: self.sig_collab_file_offer.emit(s, o)
        self.engine.on_collab_file_done = lambda s, i: self.sig_collab_file_done.emit(s, i)
        self.sig_collab_file_offer.connect(self._on_collab_file_offer)
        self.sig_collab_file_done.connect(self._on_collab_file_done)
        self.engine.on_collab_llm_task = lambda s, t: self.sig_collab_llm_task.emit(s, t)
        self.engine.on_collab_video = lambda s, d: self.sig_collab_video.emit(d)
        self.sig_collab_llm_task.connect(self._on_collab_llm_task)
        self.sig_collab_video.connect(self._on_collab_video)

    def _on_collab_incoming(self, req):
        dlg = IncomingRequestDialog(req, self)
        dlg.exec()
        self.engine.collab.resolve_incoming(req.id, dlg.accepted)

    def _on_collab_connected(self, sess):
        self._append_bubble(
            "Collaboration",
            f"Connected to {sess.remote_label or sess.remote_fp[:12]} "
            f"(FP {sess.remote_fp[:16]}…).",
            "system", GREEN,
        )
        win = CollaborationWindow(self.engine, sess, self)
        self.collab_windows[sess.remote_fp] = win
        win.show()

    def _on_collab_chat(self, sess, text):
        win = self.collab_windows.get(sess.remote_fp)
        if not win:
            win = CollaborationWindow(self.engine, sess, self)
            self.collab_windows[sess.remote_fp] = win
            win.show()
        win.append_peer(text)

    def _on_collab_file_offer(self, sess, offer):
        size = offer.get("size", 0)
        resp = QMessageBox.question(
            self, "Incoming File",
            f"{html.escape(offer.get('name', 'file'))} ({size} bytes) from "
            f"{sess.remote_label or sess.remote_fp[:12]}.\n\n"
            "Accept and save it to the quarantine folder?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        try:
            self.engine.collab.resolve_file(offer["transfer_id"], resp == QMessageBox.Yes)
        except Exception:
            pass

    def _on_collab_file_done(self, sess, info):
        ok = info.get("ok")
        if ok:
            msg = f"File received: {info.get('name')} saved to {info.get('path')}"
        else:
            msg = f"File transfer failed verification: {info.get('name')}"
        self._append_bubble("Collaboration", msg, "system", GREEN if ok else RED)

    def open_send_file_dialog(self):
        collab = getattr(self.engine, "collab", None)
        if not collab:
            QMessageBox.information(self, "Kairos", "Collaboration is not enabled.")
            return
        sessions = collab.sessions()
        if not sessions:
            QMessageBox.information(self, "Kairos", "Not connected to any peer.")
            return
        SendFileDialog(self.engine, sessions, self).exec()

    def _on_collab_llm_task(self, sess, task):
        resp = QMessageBox.question(
            self, "Remote LLM Request",
            f"{sess.remote_label or sess.remote_fp[:12]} asks your Kairos to answer:\n\n"
            f"{html.escape((task.get('prompt') or '')[:800])}\n\n"
            "Allow? This uses your own LLM provider.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        try:
            self.engine.collab.resolve_llm(task["task_id"], resp == QMessageBox.Yes)
        except Exception:
            pass

    def _on_collab_video(self, data):
        for w in self.collab_windows.values():
            try:
                w.sig_remote_video.emit(data)
            except Exception:
                pass

    def open_federated_dialog(self):
        collab = getattr(self.engine, "collab", None)
        if not collab:
            QMessageBox.information(self, "Kairos", "Collaboration is not enabled.")
            return
        sessions = collab.sessions()
        if not sessions:
            QMessageBox.information(self, "Kairos", "Not connected to any peer.")
            return
        FederatedDialog(self.engine, sessions, self).exec()

    def open_discover_dialog(self):
        if not getattr(self.engine, "collab", None):
            QMessageBox.information(self, "Kairos", "Collaboration is not enabled.")
            return
        DiscoverDialog(self.engine, self).exec()

    def open_agent_settings(self):
        AgentSettingsDialog(self.engine, self).exec()
        from kairos.config import load_config
        self.engine.config = load_config()
        self.refresh_status_bar()

    def open_usage_dialog(self):
        UsageTracesDialog(self.engine, self).exec()

    def open_plans_dialog(self):
        PlansDialog(self.engine, self).exec()

    def open_my_callsign_dialog(self):
        if not getattr(self.engine, "collab", None):
            QMessageBox.information(self, "Kairos", "Collaboration is not enabled.")
            return
        MyCallSignDialog(self.engine, self).exec()

    def open_connect_dialog(self):
        if not getattr(self.engine, "collab", None):
            QMessageBox.information(self, "Kairos", "Collaboration is not enabled.")
            return
        ConnectDialog(self.engine, self).exec()

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

        # Notify when proposed knowledge awaits approval.
        self._last_pending = 0
        self.pending_timer = QTimer(self)
        self.pending_timer.timeout.connect(self._check_pending_knowledge)
        self.pending_timer.start(6000)
        QTimer.singleShot(2500, self._check_pending_knowledge)

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
        edit_menu.addAction("Telegram Settings\u2026", self.open_telegram_dialog)
        edit_menu.addAction("MiroFish Settings", self.open_mirofish_dialog)
        edit_menu.addSeparator()
        edit_menu.addAction("Peripheral Control", self.open_peripheral_dialog)
        self._peripheral_action = edit_menu.actions()[-1]
        edit_menu.addAction("Retention (Delete Expired)", self.open_retention_dialog)
        edit_menu.addSeparator()
        self._skills_action = edit_menu.addAction("Skills", self.open_skill_dialog)
        edit_menu.addAction("Agent Character\u2026", self.open_character_dialog)
        edit_menu.addAction("Knowledge Graph\u2026", self.open_graph_dialog)
        edit_menu.addAction("Pending Knowledge\u2026", self.open_pending_dialog)

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("Predictive Engine", self.open_predict_dialog)

        collab_menu = menubar.addMenu("&Collaborate")
        collab_menu.addAction("My Call Sign\u2026", self.open_my_callsign_dialog)
        collab_menu.addAction("Connect to Peer\u2026", self.open_connect_dialog)
        collab_menu.addAction("Send File to Peer\u2026", self.open_send_file_dialog)
        collab_menu.addAction("Ask Peer's LLM\u2026", self.open_federated_dialog)
        collab_menu.addAction("Discover Peers\u2026", self.open_discover_dialog)

        agent_menu = menubar.addMenu("&Agent")
        agent_menu.addAction("Settings\u2026", self.open_agent_settings)
        agent_menu.addAction("Usage & Traces\u2026", self.open_usage_dialog)
        agent_menu.addAction("Plans & Tasks\u2026", self.open_plans_dialog)

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
        self._dl_worker = UpdateDownloadWorker(url, info.get("asset_digest"),
                                               info.get("signature_url"))
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
            ("Graph", None, self.open_graph_dialog),
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
        self.pending_label = QLabel("")
        self.pending_label.setStyleSheet(f"color: {GREEN_DIM}; font-weight: bold; font-family: 'Segoe UI', sans-serif;")
        self.mood = MoodIndicator()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.pending_label)
        header.addSpacing(12)
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
            ("Telegram", self.open_telegram_dialog),
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
        self._stream_buf = ""
        self._set_mood("thinking")
        self._start_deep_thinking_timer()
        self.worker = LLMWorker(self.engine, text, attachments=attachments)
        self.worker.finished.connect(self.on_llm_reply)
        self.worker.chunk.connect(self._on_llm_chunk)
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

    def _on_llm_chunk(self, text):
        if not text:
            return
        self._stream_buf = getattr(self, "_stream_buf", "") + text
        if getattr(self, "_pending_kairos_bubble", None):
            self._pending_kairos_bubble.set_text(self._stream_buf)

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

    def open_telegram_dialog(self):
        TelegramDialog(self.engine, self).exec()
        self.refresh_status_bar()

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

    def open_graph_dialog(self):
        GraphDialog(self.engine, self).exec()
        self._check_pending_knowledge()

    def open_pending_dialog(self):
        before = self.engine.graph_pending_count()
        PendingDialog(self.engine, self).exec()
        self._last_pending = self.engine.graph_pending_count()
        self._check_pending_knowledge()

    def _check_pending_knowledge(self):
        try:
            n = self.engine.graph_pending_count()
        except Exception:
            n = 0
        if n > 0:
            self.pending_label.setText(f"\u25CF Pending knowledge: {n}")
            self.pending_label.setToolTip("New knowledge awaiting your approval. Click Edit \u2192 Pending Knowledge.")
        else:
            self.pending_label.setText("")
            self.pending_label.setToolTip("")
        if n > getattr(self, "_last_pending", 0):
            self._append_bubble(
                "Knowledge",
                f"{n} new item(s) await your approval. Open Edit \u2192 Pending Knowledge to review.",
                "system", GREEN,
            )
        self._last_pending = n

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
