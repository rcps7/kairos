"""HTTP client for the MiroFish swarm-simulation service.

MiroFish runs as a SEPARATE service (see README). This client talks to its
backend API. If MiroFish is unreachable, callers should fall back to
QuickPredictor.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)


class MiroFishClient:
    def __init__(self, base_url: str = "http://localhost:5001"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)

    def is_available(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/health", timeout=5.0)
            return r.status_code < 500
        except Exception:
            return False

    def predict(self, seed: str, question: str, poll_interval: float = 5.0,
                max_wait: float = 600.0) -> str:
        """Submit a prediction and block until the report is ready."""
        job = self._create(seed, question)
        job_id = job.get("id") or job.get("job_id")
        if not job_id:
            # Fallback: if the service exposes a synchronous endpoint.
            return self._create_report(job)

        deadline = time.time() + max_wait
        while time.time() < deadline:
            status = self._status(job_id)
            if status.get("status") in ("done", "complete", "completed"):
                return self._report(job_id)
            if status.get("status") in ("failed", "error"):
                raise RuntimeError(f"MiroFish simulation failed: {status}")
            time.sleep(poll_interval)
        raise TimeoutError("MiroFish prediction timed out.")

    def _create(self, seed: str, question: str) -> dict:
        r = self.client.post(
            f"{self.base_url}/api/simulate",
            json={"seed": seed, "question": question},
        )
        r.raise_for_status()
        return r.json()

    def _status(self, job_id: str) -> dict:
        r = self.client.get(f"{self.base_url}/api/status/{job_id}")
        r.raise_for_status()
        return r.json()

    def _report(self, job_id: str) -> str:
        r = self.client.get(f"{self.base_url}/api/report/{job_id}")
        r.raise_for_status()
        data = r.json()
        return data.get("report") or data.get("content") or str(data)

    def _create_report(self, job: dict) -> str:
        return job.get("report") or job.get("content") or str(job)

    def close(self):
        self.client.close()
