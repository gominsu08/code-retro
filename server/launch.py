"""Run HTTP and queue processes in one container; stop both if either fails."""
import os
import signal
import subprocess
import sys
import threading

from alembic import command
from alembic.config import Config

from .app.config import ROOT, get_settings


def main():
    os.chdir(ROOT)
    settings = get_settings()
    if settings.app_env == "production" and settings.database_url.startswith("sqlite"):
        raise RuntimeError("Production requires a persistent PostgreSQL database.")
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    port = os.environ.get("PORT", "8000")
    processes = []
    failed = False
    try:
        host = "0.0.0.0" if settings.app_env == "production" else "127.0.0.1"
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app.main:app", "--host", host, "--port", port, "--no-access-log"]))
        processes.append(subprocess.Popen([sys.executable, "-m", "server.worker"]))
        while not stop.wait(1):
            if any(p.poll() is not None for p in processes):
                failed = True
                break
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
