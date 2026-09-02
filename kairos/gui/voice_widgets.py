"""Voice widgets and workers for the Kairos GUI.

Provides:
- VoiceWorker   : records the microphone, emits live level + transcription
- SpeakWorker   : speaks text via TTS (pyttsx3 / Windows SAPI)
- VoiceMeter    : animated horizontal audio-level meter
- MoodIndicator : glowing orb that changes colour/animation with agent mood
"""

import math
import time

import numpy as np

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
# Voice worker (speech-to-text)
# ---------------------------------------------------------------------------
class VoiceWorker(QThread):
    level = Signal(float)
    result = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None, max_seconds=15):
        super().__init__(parent)
        self._stop = False
        self.max_seconds = max_seconds

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import soundcard as sc
            import speech_recognition as sr
        except Exception as e:
            self.error.emit(f"Voice libraries not available: {e}")
            return

        try:
            mic = sc.default_microphone()
        except Exception as e:
            self.error.emit(f"No microphone found: {e}")
            return

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True

        sample_rate = 16000
        chunk = sample_rate // 10  # 100 ms frames
        chunks = []

        try:
            with mic.recorder(samplerate=sample_rate, channels=1) as rec:
                start = time.time()
                while not self._stop and (time.time() - start) < self.max_seconds:
                    data = rec.record(numframes=chunk)
                    data = np.asarray(data).reshape(-1).astype(np.float32)
                    chunks.append(data)
                    rms = float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
                    self.level.emit(min(1.0, rms * 6.0))
        except Exception as e:
            self.error.emit(f"Recording failed: {e}")
            return

        if not chunks:
            self.error.emit("No audio captured.")
            return

        audio = np.concatenate(chunks)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        audio_data = sr.AudioData(pcm, sample_rate, 2)

        try:
            text = recognizer.recognize_google(audio_data)
            self.result.emit(text)
        except sr.UnknownValueError:
            self.error.emit("Could not understand the audio.")
        except sr.RequestError as e:
            self.error.emit(f"Speech service error: {e}")
        except Exception as e:
            self.error.emit(f"Recognition failed: {e}")


# ---------------------------------------------------------------------------
# Speak worker (text-to-speech)
# ---------------------------------------------------------------------------
class SpeakWorker(QThread):
    finished_speaking = Signal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text

    def run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", 170)
            except Exception:
                pass
            engine.say(self.text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
        except Exception:
            pass
        self.finished_speaking.emit()


# ---------------------------------------------------------------------------
# Voice meter
# ---------------------------------------------------------------------------
class VoiceMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._target = 0.0
        self.setMinimumHeight(14)
        self.setFixedHeight(14)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(40)

    def set_level(self, value: float):
        self._target = max(0.0, min(1.0, float(value)))

    def _tick(self):
        self._level += (self._target - self._level) * 0.25
        self._target *= 0.85
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1c2128"))
        p.drawRoundedRect(0, 0, w, h, 6, 6)

        if self._level <= 0.001:
            p.end()
            return

        bar_w = int(w * self._level)
        # Colour shifts green -> yellow -> red with level.
        r = int(255 * min(1.0, self._level * 2.0))
        g = int(255 * (1.0 - abs(self._level - 0.5) * 2.0))
        b = 60
        p.setBrush(QColor(r, g, b))
        p.drawRoundedRect(0, 0, bar_w, h, 6, 6)
        p.end()


# ---------------------------------------------------------------------------
# Mood indicator (animated orb)
# ---------------------------------------------------------------------------
MOOD_COLORS = {
    "idle": QColor("#586069"),
    "listening": QColor("#00d4ff"),
    "thinking": QColor("#ff9f1c"),
    "deep_thinking": QColor("#ff3b30"),
    "speaking": QColor("#00ff66"),
    "success": QColor("#00ff66"),
    "error": QColor("#ff3b30"),
}


class MoodIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mood = "idle"
        self._phase = 0.0
        self.setFixedSize(34, 34)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(40)

    def set_mood(self, mood: str):
        if mood not in MOOD_COLORS:
            mood = "idle"
        self._mood = mood
        self.update()

    def mood(self):
        return self._mood

    def _animate(self):
        self._phase += 0.15
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = MOOD_COLORS.get(self._mood, QColor("#586069"))
        cx = self.width() / 2
        cy = self.height() / 2
        radius = self.width() / 2 - 3

        pulsing = self._mood in ("thinking", "deep_thinking", "speaking", "listening")
        if pulsing:
            radius *= 0.8 + 0.2 * math.sin(self._phase * 2.0)

        # Glow
        glow = QColor(c)
        glow.setAlpha(60)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(cx - radius - 4, cy - radius - 4, (radius + 4) * 2, (radius + 4) * 2))

        # Core
        p.setBrush(c)
        p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # Spinning ring while thinking / listening
        if self._mood in ("thinking", "deep_thinking", "listening"):
            pen = QPen(QColor("#ffffff"))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            arc_span = 60 * 16
            start = int(self._phase * 60 * 16) % (360 * 16)
            p.drawArc(QRectF(cx - radius - 2, cy - radius - 2, (radius + 2) * 2, (radius + 2) * 2), start, arc_span)

        p.end()
