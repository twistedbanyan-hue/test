from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from voicebox import HOST, PORT, ROOT, URL


def port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((HOST, PORT)) == 0


def start_server() -> None:
    if port_open():
        return
    log_dir = Path.home() / ".local" / "share" / "voicebox"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    handle = log_file.open("a", encoding="utf-8")
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "voicebox.app:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )
    for _ in range(50):
        if port_open():
            return
        time.sleep(0.15)
    raise RuntimeError(f"Server did not start. See {log_file}")


def main() -> None:
    start_server()
    webbrowser.open(URL)


if __name__ == "__main__":
    main()
