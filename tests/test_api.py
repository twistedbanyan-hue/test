from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from voicebox.app import app
from tests.test_library import make_tone


client = TestClient(app)


def test_status_and_conversation_flow(tmp_path, monkeypatch):
    from voicebox import app as appmod
    from voicebox import conversation as conv
    from voicebox import library as lib
    from voicebox import tts as tts_mod

    monkeypatch.setattr(lib, "DATA", tmp_path)
    monkeypatch.setattr(lib, "LIBRARY_PATH", tmp_path / "library.json")
    monkeypatch.setattr(lib, "CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(lib, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(tts_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(conv, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(appmod, "OUTPUTS_DIR", tmp_path / "outputs")
    tts_mod._BACKEND = None
    tts_mod._MODEL = None

    alex = make_tone(tmp_path / "alex-src.wav", 220, 2)
    jordan = make_tone(tmp_path / "jordan-src.wav", 480, 2)

    r1 = client.post(
        "/api/voices",
        data={"name": "Alex", "start": "0", "duration": "2"},
        files={"file": ("alex.wav", alex.read_bytes(), "audio/wav")},
    )
    r2 = client.post(
        "/api/voices",
        data={"name": "Jordan", "start": "0", "duration": "2"},
        files={"file": ("jordan.wav", jordan.read_bytes(), "audio/wav")},
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    alex_id = r1.json()["id"]
    jordan_id = r2.json()["id"]

    parsed = client.post(
        "/api/script",
        json={"script": "Alex: Hello there.\nJordan: Hi Alex."},
    )
    assert parsed.status_code == 200
    assert parsed.json()["lines"][0]["voice_id"] == alex_id

    conv = client.post(
        "/api/conversation",
        json={
            "lines": [
                {"voice_id": alex_id, "text": "Hello there."},
                {"voice_id": jordan_id, "text": "Hi Alex."},
            ],
            "pause_ms": 120,
        },
    )
    assert conv.status_code == 200, conv.text
    name = conv.json()["file"]
    audio = client.get(f"/api/outputs/{name}")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/")
    assert len(audio.content) > 1000
