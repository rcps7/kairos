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


class _MainThreadInvoker(QObject):
    """Run a callable on the Qt main thread and return its result (blocking)."""

    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._handle, Qt.BlockingQueuedConnection)

    def _handle(self, box):
        fn, holder = box
        try:
            holder["result"] = fn()
        except Exception as e:
            holder["error"] = e

    def __call__(self, fn):
        holder = {}
        self._call.emit((fn, holder))
        if "error" in holder:
            raise holder["error"]
        return holder.get("result")


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


