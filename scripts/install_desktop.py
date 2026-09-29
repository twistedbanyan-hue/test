#!/usr/bin/env python3
"""Install a desktop launcher that opens Voice Clone."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "icon.png"
PYTHON = Path(sys.executable)


def desktop_dir() -> Path:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "desktop",
        Path(os.environ.get("XDG_DESKTOP_DIR", "")),
    ]
    for path in candidates:
        if path and str(path) not in (".", "") and path.parent.exists():
            path.mkdir(parents=True, exist_ok=True)
            return path
    fallback = home / "Desktop"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def linux_launcher() -> Path:
    python = PYTHON
    exec_line = f'"{python}" -m voicebox'
    desktop_text = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=Voice Clone
Comment=Clone voices from video and mix conversations
Exec=env PYTHONPATH={ROOT} {exec_line}
Path={ROOT}
Icon={ICON}
Terminal=false
Categories=AudioVideo;Audio;
StartupNotify=true
"""
    desktop = desktop_dir() / "Voice Clone.desktop"
    desktop.write_text(desktop_text, encoding="utf-8")
    desktop.chmod(desktop.stat().st_mode | stat.S_IEXEC)
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop, apps / "voice-clone.desktop")
    try:
        checksum = subprocess.check_output(["sha256sum", str(desktop)], text=True).split()[0]
        subprocess.run(
            [
                "gio",
                "set",
                "-t",
                "string",
                str(desktop),
                "metadata::xfce-exe-checksum",
                checksum,
            ],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["gio", "set", str(desktop), "metadata::trusted", "true"],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass
    return desktop


def mac_launcher() -> Path:
    command = desktop_dir() / "Voice Clone.command"
    command.write_text(
        f"""#!/bin/bash
cd "{ROOT}"
export PYTHONPATH="{ROOT}"
"{PYTHON}" -m voicebox
""",
        encoding="utf-8",
    )
    command.chmod(command.stat().st_mode | stat.S_IEXEC)
    return command


def windows_launcher() -> Path:
    bat = desktop_dir() / "Voice Clone.bat"
    bat.write_text(
        f"""@echo off
cd /d "{ROOT}"
set PYTHONPATH={ROOT}
"{PYTHON}" -m voicebox
""",
        encoding="utf-8",
    )
    return bat


def main() -> None:
    if sys.platform == "darwin":
        path = mac_launcher()
    elif sys.platform.startswith("win"):
        path = windows_launcher()
    else:
        path = linux_launcher()
    print(f"Desktop icon installed:\n{path}")


if __name__ == "__main__":
    main()
