from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from voicebox import DATA, SAMPLE_RATE
from voicebox.library import OUTPUTS_DIR, ensure_dirs

_MODEL = None
_BACKEND = None


def _save_array(audio, sr: int, dest: Path) -> Path:
    import numpy as np
    import soundfile as sf

    dest.parent.mkdir(parents=True, exist_ok=True)
    arr = audio
    if hasattr(arr, "detach"):
        arr = arr.detach()
    if hasattr(arr, "cpu"):
        arr = arr.cpu()
    if hasattr(arr, "numpy"):
        arr = arr.numpy()
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr.squeeze(0) if arr.shape[0] <= 2 else arr.squeeze(-1)
        if arr.ndim == 2:
            arr = arr[0]
    sf.write(str(dest), arr, sr)
    return dest


def _try_chatterbox_mlx():
    from chatterbox_mlx import ChatterboxTTSMLX

    model = ChatterboxTTSMLX.from_pretrained(device="hybrid-mlx")
    sr = getattr(model, "sr", SAMPLE_RATE)

    def speak(text: str, clip: Path, exaggeration: float, cfg: float) -> Path:
        wav = model.generate(
            text,
            audio_prompt_path=str(clip),
            exaggeration=exaggeration,
            cfg_weight=cfg,
        )
        dest = OUTPUTS_DIR / f"line-{uuid.uuid4().hex[:10]}.wav"
        return _save_array(wav, sr, dest)

    return "Chatterbox MLX (local clone)", speak


def _try_chatterbox():
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)
    sr = getattr(model, "sr", SAMPLE_RATE)

    def speak(text: str, clip: Path, exaggeration: float, cfg: float) -> Path:
        wav = model.generate(
            text,
            audio_prompt_path=str(clip),
            exaggeration=exaggeration,
            cfg_weight=cfg,
        )
        dest = OUTPUTS_DIR / f"line-{uuid.uuid4().hex[:10]}.wav"
        return _save_array(wav, sr, dest)

    label = f"Chatterbox ({device})"
    return label, speak


def _espeak_bin() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def _voice_color(clip: Path, voice_id: str) -> tuple[int, int, str]:
    """Stable per-voice espeak pitch/speed/variant so speakers differ."""
    digest = hashlib.sha256(f"{voice_id}:{clip}".encode()).digest()
    pitch = 35 + digest[0] % 50
    speed = 140 + digest[1] % 50
    variants = ["en-us", "en-gb", "en+m2", "en+m3", "en+f2", "en+f3"]
    variant = variants[digest[2] % len(variants)]
    return pitch, speed, variant


def _try_espeak():
    binary = _espeak_bin()
    if not binary:
        raise RuntimeError("espeak-ng is not installed")

    def speak(text: str, clip: Path, exaggeration: float, cfg: float) -> Path:
        voice_id = clip.stem
        pitch, speed, variant = _voice_color(clip, voice_id)
        pitch = int(pitch + (exaggeration - 0.5) * 40)
        speed = int(speed + (cfg - 0.5) * 40)
        dest = OUTPUTS_DIR / f"line-{uuid.uuid4().hex[:10]}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            raw = Path(tmp.name)
        try:
            result = subprocess.run(
                [
                    binary,
                    "-v",
                    variant,
                    "-p",
                    str(max(1, min(pitch, 99))),
                    "-s",
                    str(max(80, min(speed, 250))),
                    "-w",
                    str(raw),
                    text,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not raw.exists():
                raise RuntimeError(result.stderr or "espeak failed")
            resample = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(raw),
                    "-ac",
                    "1",
                    "-ar",
                    str(SAMPLE_RATE),
                    str(dest),
                ],
                capture_output=True,
                text=True,
            )
            if resample.returncode != 0:
                raise RuntimeError(resample.stderr[-400:] or "resample failed")
        finally:
            raw.unlink(missing_ok=True)
        return dest

    return "eSpeak fallback (not a clone — install Chatterbox on the M4)", speak


def load_engine() -> tuple[str, object]:
    global _MODEL, _BACKEND
    if _BACKEND is not None:
        return _MODEL, _BACKEND
    ensure_dirs()
    errors = []
    for factory in (_try_chatterbox_mlx, _try_chatterbox, _try_espeak):
        try:
            label, speak = factory()
            _MODEL, _BACKEND = label, speak
            return _MODEL, _BACKEND
        except Exception as exc:  # noqa: BLE001 — try next backend
            errors.append(f"{factory.__name__}: {exc}")
    raise RuntimeError("No TTS backend available:\n" + "\n".join(errors))


def engine_info() -> dict:
    try:
        label, _ = load_engine()
        cloning = label.lower().startswith("chatterbox")
        return {
            "ok": True,
            "engine": label,
            "cloning": cloning,
            "data_dir": str(DATA),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": None, "cloning": False, "error": str(exc)}


def speak(text: str, clip: Path, exaggeration: float = 0.5, cfg: float = 0.5) -> Path:
    _, backend = load_engine()
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Text is empty")
    if not clip.exists():
        raise FileNotFoundError(clip)
    return backend(cleaned, clip, float(exaggeration), float(cfg))
