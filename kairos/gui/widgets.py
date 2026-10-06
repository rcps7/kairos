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


