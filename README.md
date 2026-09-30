# Voice Clone

Local voice library on your machine. Each person is a WAV you keep. Mix those voices into a conversation.

Paid cloud clones are not used: you cannot download those voices. This app stores clips under `~/.local/share/voicebox/` (or `%APPDATA%\voicebox` if you change `VOICEBOX_DATA`).

## Desktop icon

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/install_desktop.py
```

That puts **Voice Clone** on your Desktop. Double-click it. The app opens in the browser at http://127.0.0.1:8765

On macOS the icon is `Voice Clone.command`. On Linux it is `Voice Clone.desktop`.

## M4 Mac mini (real cloning)

This machine will use **Chatterbox MLX** when installed:

```bash
pip install chatterbox-mlx
python scripts/install_desktop.py
```

Use Python 3.11 or 3.12. First run downloads model weights (~4 GB).

Without Chatterbox the app still runs (eSpeak) so you can test the library and conversation mixer. Speakers will sound different, but that is **not** a clone. Install Chatterbox on the M4 for actual cloning.

## Use

1. Save a voice: pick a video/audio file, set start + length (10–20s of one speaker, max 40s), name them.
2. Play the clip. If it is messy, cut a cleaner slice and save again.
3. Conversation: add lines, pick a speaker per line, generate.
4. Or paste a script:

```
Alex: Did you hear that?
Jordan: Yeah. Say it again.
```

Names must match the library labels.

Tweaks: exaggeration slider, pause between speakers. A closer match comes from a cleaner clip, not from dumping more minutes into Chatterbox.

## Dual random montage (dock / grok folders)

Build a **two-up full-frame** video: random pairs side-by-side from your folders, soundtrack = **abs1-all three**, length = full audio track.

On your Mac (after you put folders and audio where the script can see them):

```bash
export MONTAGE_BASE="$HOME/Movies"   # parent of your folders
export MONTAGE_AUDIO="$HOME/Movies/abs1-all three.mp3"
bash scripts/run_dock_grok_montage.sh
```

Or explicitly:

```bash
python3 scripts/build_dual_random_montage.py \
  --folder "$HOME/Movies/dock test 22" \
  --folder "$HOME/Movies/test all grok videos a" \
  --folder "$HOME/Movies/a" \
  --audio "$HOME/Movies/abs1-all three.mp3" \
  --output "$HOME/Desktop/dual_random_montage.mp4" \
  --segment-seconds 4
```

Uses all `.mp4`/`.mov`/`.mkv` under those folders (recursive). Original clip audio is removed; only the soundtrack is kept.

## 1080 Ti (optional)

If a clip is not close enough, GPT-SoVITS on the Windows 1080 Ti can train on about a minute of audio. Keep using the WAV library this app already saved. Pin PyTorch to the `cu126` wheel on that card.
