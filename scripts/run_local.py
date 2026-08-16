from __future__ import annotations

import argparse
import importlib.util
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DATABASE = ROOT / "data" / "odi_analytics.duckdb"
CONDA_ENV = "odi-analyst-workbench"


def _backend_command() -> list[str]:
    if importlib.util.find_spec("uvicorn") is not None:
        return [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"]
    conda_executable = shutil.which("conda")
    if conda_executable:
        conda_root = Path(conda_executable).resolve().parents[1]
        environment_root = conda_root / "envs" / CONDA_ENV
        environment_python = environment_root / ("python.exe" if sys.platform == "win32" else "bin/python")
        if environment_python.exists():
            return [
                str(environment_python),
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ]
    if conda_executable:
        return [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            CONDA_ENV,
            "python",
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
    raise RuntimeError(
        "Uvicorn is unavailable. Activate the odi-analyst-workbench Conda environment "
        "or install the dependencies from environment.local.yml."
    )


def _frontend_command() -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is unavailable. Install Node.js or activate the project Conda environment.")
    if not (FRONTEND / "node_modules").exists():
        raise RuntimeError("Frontend dependencies are missing. Run npm install in frontend/ first.")
    return [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"]


def _terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()


def run(*, backend_only: bool, frontend_only: bool) -> int:
    if not frontend_only and not DATABASE.exists():
        raise RuntimeError(
            f"Database not found at {DATABASE}. Run ingestion/app/load_odi_csv.py before starting CricAtlas."
        )

    commands: list[tuple[list[str], Path]] = []
    if not frontend_only:
        commands.append((_backend_command(), ROOT))
    if not backend_only:
        commands.append((_frontend_command(), FRONTEND))

    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_handlers = {
        signal_number: signal.signal(signal_number, stop)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for command, cwd in commands:
            processes.append(subprocess.Popen(command, cwd=cwd))
        while not stopping:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            time.sleep(0.2)
        return 0
    finally:
        _terminate(processes)
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CricAtlas local development services.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backend-only", action="store_true")
    mode.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    try:
        return run(backend_only=args.backend_only, frontend_only=args.frontend_only)
    except RuntimeError as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
