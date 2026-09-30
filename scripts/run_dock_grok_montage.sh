#!/usr/bin/env bash
# Edit BASE to where your Mac folders live, then: bash scripts/run_dock_grok_montage.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${MONTAGE_BASE:-$HOME/Movies}"

F1="$BASE/dock test 22"
F2="$BASE/test all grok videos a"
F3="${MONTAGE_EXTRA_FOLDER:-$BASE/a}"

AUDIO=""
for candidate in \
  "$BASE/abs1-all three.mp3" \
  "$BASE/abs1-all three.m4a" \
  "$BASE/abs1-all three.wav" \
  "$BASE/abs1-all three.mp4" \
  "$HOME/Desktop/abs1-all three.mp3" \
  "$HOME/Downloads/abs1-all three.mp3"
do
  if [[ -f "$candidate" ]]; then
    AUDIO="$candidate"
    break
  fi
done

if [[ -z "$AUDIO" ]]; then
  echo "Set AUDIO path: export MONTAGE_AUDIO=/path/to/abs1-all three.mp3" >&2
  exit 1
fi

OUT="${MONTAGE_OUTPUT:-$HOME/Desktop/dual_random_montage.mp4}"

python3 "$ROOT/scripts/build_dual_random_montage.py" \
  --folder "$F1" \
  --folder "$F2" \
  --folder "$F3" \
  --audio "$AUDIO" \
  --output "$OUT" \
  --segment-seconds "${MONTAGE_SEGMENT_SECONDS:-4}" \
  ${MONTAGE_SEED:+--seed "$MONTAGE_SEED"}

echo "Wrote $OUT"
