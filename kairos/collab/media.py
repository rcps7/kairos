"""Audio transport for collaboration: 16 kHz mono PCM capture and playback
using the ``soundcard`` library (already a Kairos dependency). No native deps.
"""

import logging
import queue
import threading

logger = logging.getLogger(__name__)


class AudioStream:
    def __init__(self, on_frame, sample_rate: int = 16000, frame_ms: int = 20):
        self.on_frame = on_frame
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self._q = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._cap_thread = None
        self._play_thread = None
        self.speaker_muted = False

    def start(self):
        self._stop.clear()
        self._cap_thread = threading.Thread(target=self._capture, daemon=True, name="kairos-audio-cap")
        self._play_thread = threading.Thread(target=self._playback, daemon=True, name="kairos-audio-play")
        self._cap_thread.start()
        self._play_thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._q.put_nowait(b"")
        except Exception:
            pass

    def feed(self, pcm_bytes: bytes):
        """Queue remote audio for playback."""
        if self.speaker_muted or not pcm_bytes:
            return
        try:
            self._q.put_nowait(pcm_bytes)
        except queue.Full:
            pass

    def _capture(self):
        try:
            import numpy as np
            import soundcard as sc
        except Exception as e:
            logger.warning("Audio capture unavailable: %s", e)
            return
        try:
            mic = sc.default_microphone()
        except Exception as e:
            logger.warning("No microphone: %s", e)
            return
        n = max(1, self.sample_rate * self.frame_ms // 1000)
        try:
            with mic.recorder(samplerate=self.sample_rate, channels=1) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=n)
                    arr = np.asarray(data).reshape(-1)
                    pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    try:
                        self.on_frame(pcm)
                    except Exception:
                        pass
        except Exception:
            logger.exception("Audio capture loop failed")

    def _playback(self):
        try:
            import numpy as np
            import soundcard as sc
        except Exception as e:
            logger.warning("Audio playback unavailable: %s", e)
            return
        try:
            spk = sc.default_speaker()
        except Exception as e:
            logger.warning("No speaker: %s", e)
            return
        blocksize = max(1, self.sample_rate * self.frame_ms // 1000)
        try:
            with spk.player(samplerate=self.sample_rate, channels=1, blocksize=blocksize) as player:
                while not self._stop.is_set():
                    try:
                        chunk = self._q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if not chunk or self.speaker_muted:
                        continue
                    arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                    try:
                        player.play(arr)
                    except Exception:
                        pass
        except Exception:
            logger.exception("Audio playback loop failed")