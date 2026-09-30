from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from voicebox import DEFAULT_CLIP_SECONDS, MAX_CLIP_SECONDS, ROOT
from voicebox.conversation import generate_conversation
from voicebox.library import (
    OUTPUTS_DIR,
    add_voice,
    delete_voice,
    get_voice,
    load_library,
    match_speaker,
    parse_script,
    rename_voice,
)
from voicebox.tts import engine_info, speak

STATIC = ROOT / "voicebox" / "static"
app = FastAPI(title="Voice Clone")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SpeakBody(BaseModel):
    text: str
    exaggeration: float = 0.5
    cfg: float = 0.5


class LineBody(BaseModel):
    voice_id: str
    text: str


class ConversationBody(BaseModel):
    lines: list[LineBody]
    pause_ms: int = Field(default=350, ge=0, le=2000)
    exaggeration: float = 0.5
    cfg: float = 0.5


class ScriptBody(BaseModel):
    script: str


class RenameBody(BaseModel):
    name: str


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC / "index.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/status")
def status() -> dict:
    info = engine_info()
    info["voices"] = len(load_library()["voices"])
    info["max_clip_seconds"] = MAX_CLIP_SECONDS
    info["default_clip_seconds"] = DEFAULT_CLIP_SECONDS
    return info


@app.get("/api/voices")
def voices() -> dict:
    return load_library()


@app.post("/api/voices")
async def create_voice(
    name: str = Form(...),
    start: float = Form(0.0),
    duration: float = Form(DEFAULT_CLIP_SECONDS),
    file: UploadFile = File(...),
) -> dict:
    suffix = Path(file.filename or "clip.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        source = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)
    try:
        return add_voice(name, source, start=start, duration=duration)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    finally:
        source.unlink(missing_ok=True)


@app.patch("/api/voices/{voice_id}")
def patch_voice(voice_id: str, body: RenameBody) -> dict:
    try:
        return rename_voice(voice_id, body.name)
    except KeyError as exc:
        raise HTTPException(404, "Voice not found") from exc


@app.delete("/api/voices/{voice_id}")
def remove_voice(voice_id: str) -> dict:
    try:
        delete_voice(voice_id)
    except KeyError as exc:
        raise HTTPException(404, "Voice not found") from exc
    return {"ok": True}


@app.get("/api/voices/{voice_id}/clip")
def voice_clip(voice_id: str) -> FileResponse:
    voice = get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "Voice not found")
    path = Path(voice["clip"])
    if not path.exists():
        raise HTTPException(404, "Clip missing")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.post("/api/voices/{voice_id}/speak")
def speak_one(voice_id: str, body: SpeakBody) -> dict:
    voice = get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "Voice not found")
    try:
        out = speak(
            body.text,
            Path(voice["clip"]),
            exaggeration=body.exaggeration,
            cfg=body.cfg,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    return {"file": out.name, "voice": voice["name"]}


@app.post("/api/script")
def preview_script(body: ScriptBody) -> dict:
    voices = load_library()["voices"]
    parsed = parse_script(body.script)
    lines = []
    missing = []
    for item in parsed:
        voice = match_speaker(item["speaker"], voices)
        if not voice:
            missing.append(item["speaker"])
        lines.append(
            {
                "speaker": item["speaker"],
                "text": item["text"],
                "voice_id": None if not voice else voice["id"],
                "matched": bool(voice),
            }
        )
    return {"lines": lines, "missing": sorted(set(missing))}


@app.post("/api/conversation")
def conversation(body: ConversationBody) -> dict:
    try:
        return generate_conversation(
            [line.model_dump() for line in body.lines],
            pause_ms=body.pause_ms,
            exaggeration=body.exaggeration,
            cfg=body.cfg,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/outputs/{name}")
def output_file(name: str) -> FileResponse:
    path = (OUTPUTS_DIR / Path(name).name).resolve()
    if path.parent != OUTPUTS_DIR.resolve() or not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)
