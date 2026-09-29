"""Voice Clone — local library and conversation studio."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("VOICEBOX_DATA", Path.home() / ".local" / "share" / "voicebox"))
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
SAMPLE_RATE = 24000
MAX_CLIP_SECONDS = 40
DEFAULT_CLIP_SECONDS = 15
