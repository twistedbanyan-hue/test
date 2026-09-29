from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from voicebox.library import add_voice, concat_wavs, match_speaker, parse_script


def make_tone(path: Path, freq: int = 440, seconds: float = 1.0) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
            "-ac",
            "1",
            "-ar",
            "24000",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_parse_script_and_match():
    script = """
Alex: Did you hear that?
Jordan: Yeah. Say it again.
Alex: We keep the voices.
"""
    lines = parse_script(script)
    assert [item["speaker"] for item in lines] == ["Alex", "Jordan", "Alex"]
    voices = [{"id": "1", "name": "Alex"}, {"id": "2", "name": "Jordan Lee"}]
    assert match_speaker("Alex", voices)["id"] == "1"
    assert match_speaker("Jordan", voices)["id"] == "2"


def test_add_voice_from_video_length_clip(tmp_path, monkeypatch):
    from voicebox import library as lib

    monkeypatch.setattr(lib, "DATA", tmp_path)
    monkeypatch.setattr(lib, "LIBRARY_PATH", tmp_path / "library.json")
    monkeypatch.setattr(lib, "CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(lib, "OUTPUTS_DIR", tmp_path / "outputs")

    source = tmp_path / "take.wav"
    make_tone(source, seconds=8)
    voice = add_voice("Alex", source, start=1, duration=3)
    assert voice["name"] == "Alex"
    assert Path(voice["clip"]).exists()
    assert 2.5 <= voice["duration"] <= 3.2


def test_concat_conversation_wavs(tmp_path):
    a = make_tone(tmp_path / "a.wav", 330, 0.4)
    b = make_tone(tmp_path / "b.wav", 550, 0.4)
    out = tmp_path / "mix.wav"
    concat_wavs([a, b], out, pause_ms=200)
    assert out.exists()
    assert out.stat().st_size > a.stat().st_size
