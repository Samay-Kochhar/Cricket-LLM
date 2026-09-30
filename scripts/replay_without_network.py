"""Run the saved-capture replay with every network connection disabled.

Any attempt to open a socket (for example a Gemini request) raises, so a
successful run proves the replay is fully offline. Usage mirrors
``scripts.replay_planner_capture``:

    PYTHONPATH=. python -m scripts.replay_without_network --benchmark ... --capture ... --output ... --summary ...
"""

from __future__ import annotations

import os
import runpy
import socket
import sys


class NetworkDisabledError(RuntimeError):
    pass


def _blocked(*args: object, **kwargs: object) -> None:
    raise NetworkDisabledError(f"network access is disabled during offline replay: {args!r}")


def main() -> None:
    os.environ["GEMINI_API_KEY"] = ""
    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]
    sys.argv = ["scripts.replay_planner_capture", *sys.argv[1:]]
    runpy.run_module("scripts.replay_planner_capture", run_name="__main__")


if __name__ == "__main__":
    main()
