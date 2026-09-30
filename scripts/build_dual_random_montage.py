#!/usr/bin/env python3
"""
Random two-up full-frame montage from video folders, soundtrack length = audio track.

Each segment shows two random clips side-by-side (scale+crop fill). Original video
audio is dropped; one audio file is muxed for the full output length.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".MP4", ".MOV"}


def run(cmd: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def probe_duration(path: Path) -> float:
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(out.stdout)
    return float(data["format"]["duration"])


def collect_videos(folders: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            print(f"Warning: missing folder {folder}", file=sys.stderr)
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix in VIDEO_EXT and path.is_file():
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(path)
    return found


def pick_start(duration: float, seg: float, rng: random.Random) -> float:
    if duration <= seg + 0.05:
        return 0.0
    return rng.uniform(0, max(0.0, duration - seg - 0.05))


def render_pair_segment(
    left: Path,
    right: Path,
    dest: Path,
    seg_seconds: float,
    width: int,
    height: int,
    rng: random.Random,
    fps: int,
) -> None:
    half_w = width // 2
    left_d = probe_duration(left)
    right_d = probe_duration(right)
    ss_left = pick_start(left_d, seg_seconds, rng)
    ss_right = pick_start(right_d, seg_seconds, rng)

    # scale+crop each half to fill; loop short clips; trim to seg_seconds
    filter_complex = (
        f"[0:v]trim=start={ss_left:.3f}:duration={seg_seconds},setpts=PTS-STARTPTS,"
        f"scale={half_w}:{height}:force_original_aspect_ratio=increase,"
        f"crop={half_w}:{height},fps={fps},format=yuv420p,setsar=1[left];"
        f"[1:v]trim=start={ss_right:.3f}:duration={seg_seconds},setpts=PTS-STARTPTS,"
        f"scale={half_w}:{height}:force_original_aspect_ratio=increase,"
        f"crop={half_w}:{height},fps={fps},format=yuv420p,setsar=1[right];"
        f"[left][right]hstack=inputs=2[v]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{ss_left:.3f}",
        "-stream_loop",
        "-1",
        "-i",
        str(left),
        "-ss",
        f"{ss_right:.3f}",
        "-stream_loop",
        "-1",
        "-i",
        str(right),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-an",
        "-t",
        f"{seg_seconds:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    run(cmd, quiet=True)


def concat_segments(segments: list[Path], dest: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_path = Path(f.name)
        for seg in segments:
            escaped = str(seg).replace("'", r"'\''")
            f.write(f"file '{escaped}'\n")
    try:
        run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(dest),
            ]
        )
    finally:
        list_path.unlink(missing_ok=True)


def mux_audio(video: Path, audio: Path, dest: Path, audio_duration: float) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{audio_duration:.3f}",
            str(dest),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-up random montage with soundtrack.")
    parser.add_argument(
        "--folder",
        action="append",
        required=True,
        help="Folder containing source videos (repeat for multiple folders).",
    )
    parser.add_argument("--audio", required=True, type=Path, help="Soundtrack file.")
    parser.add_argument("--output", required=True, type=Path, help="Output .mp4 path.")
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=4.0,
        help="Seconds per random pair (default 4).",
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=None, help="Random seed (optional).")
    args = parser.parse_args()

    folders = [Path(p).expanduser() for p in args.folder]
    audio = args.audio.expanduser()
    output = args.output.expanduser()
    if not audio.is_file():
        print(f"Audio not found: {audio}", file=sys.stderr)
        return 1

    videos = collect_videos(folders)
    if len(videos) < 2:
        print(
            f"Need at least 2 videos; found {len(videos)} in {len(folders)} folder(s).",
            file=sys.stderr,
        )
        return 1

    rng = random.Random(args.seed)
    audio_dur = probe_duration(audio)
    seg = max(0.5, float(args.segment_seconds))

    segments: list[Path] = []
    total = 0.0
    index = 0

    with tempfile.TemporaryDirectory(prefix="dual-montage-") as tmp:
        tmp_path = Path(tmp)
        while total < audio_dur:
            left, right = rng.sample(videos, 2)
            seg_path = tmp_path / f"seg_{index:05d}.mp4"
            print(f"Segment {index + 1}: {left.name} | {right.name} ({seg:.1f}s)")
            render_pair_segment(
                left,
                right,
                seg_path,
                seg,
                args.width,
                args.height,
                rng,
                args.fps,
            )
            segments.append(seg_path)
            total += seg
            index += 1

        concat_out = tmp_path / "video_only.mp4"
        concat_segments(segments, concat_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        mux_audio(concat_out, audio, output, audio_dur)

    print(f"Done: {output} ({audio_dur:.1f}s, {len(segments)} segments, {len(videos)} source clips)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
