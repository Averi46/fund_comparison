"""Launch the FastAPI backend and Streamlit dashboard together."""

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def wait_for_api(url: str, process: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The API process exited during startup")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError(f"The API did not become ready within {timeout:g} seconds")


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def handle_termination(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> int:
    signal.signal(signal.SIGTERM, handle_termination)
    host = os.getenv("FUND_API_HOST", "127.0.0.1")
    port = os.getenv("FUND_API_PORT", "8000")
    api_url = f"http://{host}:{port}"
    environment = {
        **os.environ,
        "FUND_API_URL": api_url,
        # PyArrow's mimalloc pool can segfault on Python 3.14/macOS while
        # Streamlit serializes chart data. The system allocator is stable.
        "ARROW_DEFAULT_MEMORY_POOL": os.getenv(
            "ARROW_DEFAULT_MEMORY_POOL", "system"
        ),
    }

    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            host,
            "--port",
            port,
        ],
        env=environment,
    )
    dashboard: subprocess.Popen | None = None
    try:
        wait_for_api(api_url, api)
        dashboard = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "frontend/dashboard.py",
            ],
            env=environment,
        )
        return dashboard.wait()
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_process(dashboard)
        stop_process(api)


if __name__ == "__main__":
    raise SystemExit(main())
