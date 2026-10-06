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

class LLMWorker(QThread):
    finished = Signal(str)
    progress = Signal(str)
    chunk = Signal(str)

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
                cfg = self.engine.config.get("agent", {}) or {}
                if cfg.get("streaming", True) and hasattr(self.engine, "stream_chat"):
                    parts = []
                    for piece in self.engine.stream_chat(
                            self.prompt or "", attachment_paths=self.attachments):
                        parts.append(piece)
                        self.chunk.emit(piece)
                    reply = "".join(parts)
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

    def __init__(self, url, digest=None, signature_url=None):
        super().__init__()
        self.url = url
        self.digest = digest
        self.signature_url = signature_url

    def run(self):
        try:
            import tempfile
            tmp = tempfile.mkdtemp(prefix="kairos_update_")
            updater.download_and_extract(self.url, tmp, expected_sha256=self.digest,
                                         signature_url=self.signature_url)
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


class ConnectWorker(QThread):
    ok = Signal(object)
    failed = Signal(str)

    def __init__(self, engine, call_sign):
        super().__init__()
        self.engine = engine
        self.call_sign = call_sign

    def run(self):
        try:
            sess = self.engine.collab.connect(self.call_sign)
            self.ok.emit(sess)
        except Exception as e:
            self.failed.emit(str(e))


class SendFileWorker(QThread):
    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine, peer_fp, path):
        super().__init__()
        self.engine = engine
        self.peer_fp = peer_fp
        self.path = path

    def run(self):
        try:
            self.ok.emit(self.engine.collab.send_file(self.peer_fp, self.path))
        except Exception as e:
            self.failed.emit(str(e))


class FederatedLlmWorker(QThread):
    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine, peer_fp, prompt, ask_local):
        super().__init__()
        self.engine = engine
        self.peer_fp = peer_fp
        self.prompt = prompt
        self.ask_local = ask_local

    def run(self):
        out = {}
        try:
            if self.ask_local:
                try:
                    out["local"] = self.engine.ask_llm(self.prompt, use_character=False)
                except Exception as e:
                    out["local"] = f"(local error: {e})"
            out["peer"] = self.engine.collab.federated_task(self.peer_fp, self.prompt)
            self.ok.emit(out)
        except Exception as e:
            self.failed.emit(str(e))


class DiscoverWorker(QThread):
    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine

    def run(self):
        try:
            self.ok.emit(self.engine.collab.discover_peers(4.0))
        except Exception as e:
            self.failed.emit(str(e))


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


