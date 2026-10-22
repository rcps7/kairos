"""A tiny FIFO background job queue.

Jobs run strictly one at a time, in submission order, each on its own worker
thread. This lets the UI stay responsive and lets the user *submit* more work
(chat turns, skills, background actions) while an earlier job is still running:
they simply wait their turn instead of colliding with the active one.

Deliberately free of any GUI toolkit so it can be unit-tested without a display.
Callers supply callbacks; when used from Qt those callbacks should emit signals
so widget updates happen on the GUI thread.
"""

import collections
import itertools
import logging
import threading

logger = logging.getLogger(__name__)

_ids = itertools.count(1)
_ids_lock = threading.Lock()


def _new_id() -> str:
    with _ids_lock:
        return f"job-{next(_ids)}"


class Job:
    """A unit of background work.

    ``run`` is called as ``run(emit_chunk, emit_progress)`` and should return the
    job's result. ``on_start``/``on_chunk``/``on_progress``/``on_done``/``on_error``
    receive the job id (and payload) and are invoked on the worker thread.
    """

    def __init__(self, run, label="job", on_start=None, on_chunk=None,
                 on_progress=None, on_done=None, on_error=None, id=None):
        self.id = id or _new_id()
        self.label = label
        self.run = run
        self.on_start = on_start
        self.on_chunk = on_chunk
        self.on_progress = on_progress
        self.on_done = on_done
        self.on_error = on_error

    def emit_chunk(self, text):
        if self.on_chunk and text:
            self.on_chunk(self.id, text)

    def emit_progress(self, text):
        if self.on_progress and text:
            self.on_progress(self.id, text)


class JobQueue:
    """Serial FIFO runner for :class:`Job` objects."""

    def __init__(self):
        self._queue = collections.deque()
        self._lock = threading.Lock()
        self._current = None
        self._thread = None
        self._idle = threading.Event()
        self._idle.set()

    # -- public API -----------------------------------------------------
    def submit(self, job: Job) -> str:
        """Append ``job`` and start it if the queue is idle."""
        with self._lock:
            self._queue.append(job)
            self._idle.clear()
            start = self._current is None
        if start:
            self._start_next()
        return job.id

    def is_busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def pending(self) -> int:
        """Number of jobs queued or running."""
        with self._lock:
            return len(self._queue) + (1 if self._current is not None else 0)

    def wait_idle(self, timeout: float = None) -> bool:
        """Block until the queue drains (used by tests)."""
        return self._idle.wait(timeout)

    # -- internals ------------------------------------------------------
    def _start_next(self):
        with self._lock:
            if self._current is not None or not self._queue:
                return
            job = self._queue.popleft()
            self._current = job
            self._thread = threading.Thread(
                target=self._run_job, args=(job,), daemon=True,
                name=f"kairos-{job.label}")
            thread = self._thread
        thread.start()

    def _run_job(self, job: Job):
        try:
            if job.on_start:
                job.on_start(job.id)
            result = job.run(job.emit_chunk, job.emit_progress)
            if job.on_done:
                job.on_done(job.id, result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller's handler
            logger.exception("Job '%s' failed", job.label)
            if job.on_error:
                job.on_error(job.id, exc)
        finally:
            with self._lock:
                self._current = None
                self._thread = None
                empty = not self._queue
            if empty:
                self._idle.set()
            self._start_next()
