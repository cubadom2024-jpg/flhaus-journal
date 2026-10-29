#!/usr/bin/env bash
# Подготовка среды для мультиков: голос, ffmpeg, python-зависимости, звуки.
# Идемпотентно, ~1 минута. Шрифты уже лежат в assets/fonts.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

need_apt=()
command -v ffmpeg >/dev/null || need_apt+=(ffmpeg)
command -v RHVoice-test >/dev/null || need_apt+=(rhvoice rhvoice-russian)
if [ ${#need_apt[@]} -gt 0 ]; then
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq "${need_apt[@]}" >/dev/null
fi

python3 -c "import numpy, PIL" 2>/dev/null || pip install -q numpy pillow

if [ ! -f "$DIR/assets/sfx/whoosh.wav" ]; then
  python3 "$DIR/scripts/sfx_gen.py" "$DIR/assets/sfx"
fi

echo "OK: ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3), RHVoice $(ls /usr/share/RHVoice/voices 2>/dev/null | tr '\n' ' ')"
echo "OK: $(ls "$DIR/assets/sfx" | wc -l) звуков в assets/sfx"
