"""Bounded localhost process helpers for the opt-in PostgreSQL restart test."""

import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Event
from time import monotonic

import httpx


BACKEND = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def remaining(deadline):
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise TimeoutError("Kill/restart test exceeded its shared deadline")
    return seconds


def poll(read, ready, deadline):
    pause = Event()
    while True:
        remaining(deadline)
        value = read()
        if ready(value):
            return value
        pause.wait(min(0.05, remaining(deadline)))


class ReviewServer:
    def __init__(self, tmp_path, database_url, port):
        self.root, self.port = tmp_path, port
        self.env = {
            **os.environ,
            "PROVIDER": "fake", "REVIEW_ENGINE": "fake", "APP_ENV": "test",
            "REVIEW_FAKE_DELAY_MS": "700", "REVIEW_LEASE_SECONDS": "3",
            "REVIEW_HEARTBEAT_SECONDS": "1", "REVIEW_RECOVER_INTERVAL_SECONDS": "1",
            "APP_STORAGE_BACKEND": "postgres", "DATABASE_URL": database_url,
            "VECTOR_BACKEND": "memory", "EMBEDDING_BACKEND": "hash",
            "APP_DATA_DIR": str(tmp_path / "documents"),
            "RUNS_DIR": str(tmp_path / "outputs"),
            "VECTOR_INDEX_PATH": str(tmp_path / "vectors"),
            "LOCAL_AUTH_ADMIN_EMAIL": "", "LOCAL_AUTH_ADMIN_PASSWORD": "",
            "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.process = None
        self.generation = 0
        self.log_path = None

    def start(self, client, deadline):
        assert self.process is None or self.process.poll() is not None
        self.generation += 1
        self.log_path = self.root / f"uvicorn-{self.generation}.log"
        with self.log_path.open("wb") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", str(self.port), "--no-access-log"],
                cwd=BACKEND, env=self.env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

        def health():
            self.check_alive()
            try:
                response = client.get("/api/health", timeout=min(1, remaining(deadline)))
                return response.status_code == 200 and response.json().get("ok") is True
            except httpx.TransportError:
                return False

        poll(health, bool, deadline)

    def check_alive(self):
        if self.process.poll() is not None:
            raise AssertionError(
                f"uvicorn exited with {self.process.returncode}: "
                + self.log_path.read_text(encoding="utf-8", errors="replace")
            )

    def kill(self):
        # No reload or multiple workers: the Popen process is the server itself.
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)

    def request(self, client, method, path, deadline, *, status=200, **kwargs):
        remaining(deadline)
        self.check_alive()
        response = client.request(method, path, timeout=min(2, remaining(deadline)), **kwargs)
        assert response.status_code == status, response.text
        return response.json()
