"""FIFO job queue tests (no GUI toolkit required)."""

import threading
import time

from kairos.jobs import Job, JobQueue


def test_fifo_order_and_serialization():
    q = JobQueue()
    events = []
    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def make(i):
        def run(emit_chunk, emit_progress):
            with lock:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
            time.sleep(0.02)
            emit_chunk(f"c{i}")
            with lock:
                active["n"] -= 1
            return i
        return run

    for i in range(5):
        q.submit(Job(run=make(i), label=f"j{i}",
                     on_done=lambda jid, r: events.append(r)))

    assert q.wait_idle(5)
    assert events == [0, 1, 2, 3, 4]      # FIFO order
    assert active["max"] == 1             # never two at once


def test_chunks_and_progress_are_routed_with_job_id():
    q = JobQueue()
    chunks = {}
    progress = []

    def run(emit_chunk, emit_progress):
        emit_progress("working")
        emit_chunk("a")
        emit_chunk("b")
        return "ok"

    q.submit(Job(run=run, label="x",
                 on_chunk=lambda jid, t: chunks.setdefault(jid, []).append(t),
                 on_progress=lambda jid, t: progress.append(t)))
    assert q.wait_idle(5)
    assert list(chunks.values()) == [["a", "b"]]
    assert progress == ["working"]


def test_error_does_not_block_the_queue():
    q = JobQueue()
    done = []

    def bad(emit_chunk, emit_progress):
        raise ValueError("boom")

    q.submit(Job(run=bad, label="bad",
                 on_error=lambda jid, e: done.append(("err", str(e)))))
    q.submit(Job(run=lambda c, p: "ok", label="good",
                 on_done=lambda jid, r: done.append(("ok", r))))

    assert q.wait_idle(5)
    assert done[0][0] == "err" and "boom" in done[0][1]
    assert done[1] == ("ok", "ok")


def test_pending_and_busy_counts():
    q = JobQueue()
    release = threading.Event()
    q.submit(Job(run=lambda c, p: release.wait(5), label="block"))
    for _ in range(200):
        if q.is_busy():
            break
        time.sleep(0.005)
    q.submit(Job(run=lambda c, p: None, label="queued"))
    assert q.pending() == 2
    release.set()
    assert q.wait_idle(5)
    assert q.pending() == 0
