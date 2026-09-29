from __future__ import annotations

import uuid
from pathlib import Path

from voicebox.library import OUTPUTS_DIR, concat_wavs, get_voice
from voicebox.tts import speak


def generate_conversation(
    lines: list[dict],
    pause_ms: int = 350,
    exaggeration: float = 0.5,
    cfg: float = 0.5,
) -> dict:
    if not lines:
        raise ValueError("Add at least one line")
    parts: list[Path] = []
    used = []
    for i, line in enumerate(lines):
        text = (line.get("text") or "").strip()
        voice_id = line.get("voice_id")
        if not text:
            raise ValueError(f"Line {i + 1} has no text")
        voice = get_voice(voice_id)
        if not voice:
            raise ValueError(f"Line {i + 1}: unknown voice")
        clip = Path(voice["clip"])
        part = speak(text, clip, exaggeration=exaggeration, cfg=cfg)
        parts.append(part)
        used.append(
            {
                "voice_id": voice["id"],
                "name": voice["name"],
                "text": text,
                "file": part.name,
            }
        )
    dest = OUTPUTS_DIR / f"conversation-{uuid.uuid4().hex[:10]}.wav"
    concat_wavs(parts, dest, pause_ms=pause_ms)
    return {"file": dest.name, "path": str(dest), "lines": used}
