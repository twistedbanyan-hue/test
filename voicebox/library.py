from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voicebox import DATA, DEFAULT_CLIP_SECONDS, MAX_CLIP_SECONDS, SAMPLE_RATE

LIBRARY_PATH = DATA / "library.json"
CLIPS_DIR = DATA / "clips"
OUTPUTS_DIR = DATA / "outputs"


def ensure_dirs() -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    if not LIBRARY_PATH.exists():
        LIBRARY_PATH.write_text(
            json.dumps({"voices": []}, indent=2),
            encoding="utf-8",
        )


def load_library() -> dict:
    ensure_dirs()
    return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))


def save_library(library: dict) -> None:
    ensure_dirs()
    tmp = LIBRARY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(library, indent=2), encoding="utf-8")
    tmp.replace(LIBRARY_PATH)


def slug(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "voice"


def get_voice(voice_id: str) -> dict | None:
    library = load_library()
    for voice in library["voices"]:
        if voice["id"] == voice_id:
            return voice
    return None


def duration_seconds(path: Path) -> float:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return round(float(probe.stdout.strip()), 2)


def extract_clip(
    source: Path,
    dest: Path,
    start: float = 0.0,
    duration: float = DEFAULT_CLIP_SECONDS,
) -> Path:
    duration = min(max(float(duration), 1.0), MAX_CLIP_SECONDS)
    start = max(float(start), 0.0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.exists():
        raise RuntimeError(result.stderr[-800:] or "ffmpeg failed to extract audio")
    return dest


def add_voice(
    name: str,
    source: Path,
    start: float = 0.0,
    duration: float = DEFAULT_CLIP_SECONDS,
) -> dict:
    ensure_dirs()
    voice_id = str(uuid.uuid4())[:8]
    clip_path = CLIPS_DIR / f"{slug(name)}-{voice_id}.wav"
    extract_clip(source, clip_path, start=start, duration=duration)
    voice = {
        "id": voice_id,
        "name": name.strip() or "Unnamed",
        "clip": str(clip_path),
        "duration": duration_seconds(clip_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_name": source.name,
        "start": start,
    }
    library = load_library()
    library["voices"].append(voice)
    save_library(library)
    return voice


def rename_voice(voice_id: str, name: str) -> dict:
    library = load_library()
    for voice in library["voices"]:
        if voice["id"] == voice_id:
            voice["name"] = name.strip() or voice["name"]
            save_library(library)
            return voice
    raise KeyError(voice_id)


def delete_voice(voice_id: str) -> None:
    library = load_library()
    kept = []
    found = None
    for voice in library["voices"]:
        if voice["id"] == voice_id:
            found = voice
        else:
            kept.append(voice)
    if not found:
        raise KeyError(voice_id)
    clip = Path(found["clip"])
    if clip.exists():
        clip.unlink()
    library["voices"] = kept
    save_library(library)


def parse_script(script: str) -> list[dict]:
    """Parse 'Name: line' dialogue into speaker/text pairs."""
    lines = []
    for raw in script.splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        if ":" in text:
            speaker, spoken = text.split(":", 1)
            speaker = speaker.strip()
            spoken = spoken.strip()
            if speaker and spoken:
                lines.append({"speaker": speaker, "text": spoken})
                continue
        if lines:
            lines[-1]["text"] += " " + text
    return lines


def match_speaker(speaker: str, voices: list[dict]) -> dict | None:
    want = speaker.strip().lower()
    for voice in voices:
        if voice["name"].strip().lower() == want:
            return voice
    for voice in voices:
        if want in voice["name"].strip().lower():
            return voice
    return None


def concat_wavs(paths: list[Path], dest: Path, pause_ms: int = 350) -> Path:
    if not paths:
        raise ValueError("No audio to mix")
    dest.parent.mkdir(parents=True, exist_ok=True)
    pause = max(int(pause_ms), 0)
    with tempfile.TemporaryDirectory() as tmp:
        concat_file = Path(tmp) / "concat.txt"
        silence = Path(tmp) / "silence.wav"
        if pause > 0:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={SAMPLE_RATE}:cl=mono",
                    "-t",
                    f"{pause / 1000:.3f}",
                    str(silence),
                ],
                check=True,
                capture_output=True,
            )
        parts = []
        for i, path in enumerate(paths):
            parts.append(path)
            if pause > 0 and i < len(paths) - 1:
                parts.append(silence)
        lines = []
        for path in parts:
            escaped = str(path).replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:a",
                "pcm_s16le",
                str(dest),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-800:] or "ffmpeg concat failed")
    return dest
