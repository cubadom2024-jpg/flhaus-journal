#!/usr/bin/env python3
"""Озвучка реплик эпизода.

Каждая реплика синтезируется отдельным файлом (как в оригинале: фраза = отдельный
клип, паузы между клипами вырезаны). Потом голос «доводится» фильтрами ffmpeg до
плотного дикторского звука: срез тишины, ускорение, тёплый низ, присутствие,
компрессия.

Движки:
  rhvoice     — офлайн, apt-пакет rhvoice-russian (по умолчанию: artemiy)
  elevenlabs  — нужен ELEVENLABS_API_KEY и доступ к api.elevenlabs.io
  file        — готовая начитка: voice.files[i] = путь к wav/mp3 на каждую реплику
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

CENSOR_RE = re.compile(r"\{([^}|]*)(?:\|([^}]*))?\}")  # {о****л} или {о****л|охренел}

# Цепочка «дикторского» звука. atempo подставляется отдельно.
POLISH = (
    "highpass=f=70,"
    "equalizer=f=140:t=q:w=1:g=2.5,"      # тёплый низ
    "equalizer=f=3200:t=q:w=1.2:g=3,"     # разборчивость
    "equalizer=f=7500:t=q:w=1:g=-2,"      # убрать шипение синтеза
    "acompressor=threshold=-20dB:ratio=4:attack=5:release=60:makeup=4"
)
TRIM = (
    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,areverse"
)


def spoken_text(line: str) -> str:
    """Текст для синтеза: цензура {x|y} -> y (или пропуск, если y нет)."""
    return CENSOR_RE.sub(lambda m: m.group(2) or " ", line).strip()


def run(cmd, **kw):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)


def duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def synth_rhvoice(text, out_wav, cfg):
    voice = cfg.get("voice", "artemiy")
    args = ["RHVoice-test", "-p", voice, "-o", str(out_wav)]
    if "rhv_rate" in cfg:
        args += ["-r", str(cfg["rhv_rate"])]
    if "rhv_pitch" in cfg:
        args += ["-t", str(cfg["rhv_pitch"])]
    subprocess.run(args, input=text.encode(), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synth_elevenlabs(text, out_wav, cfg):
    key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = cfg["voice"]
    body = json.dumps({
        "text": text,
        "model_id": cfg.get("model", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": cfg.get("stability", 0.35),
            "similarity_boost": cfg.get("similarity", 0.8),
            "style": cfg.get("style", 0.45),
            "use_speaker_boost": True,
        },
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
    mp3 = Path(str(out_wav) + ".mp3")
    with urllib.request.urlopen(req, timeout=120) as r:
        mp3.write_bytes(r.read())
    run(["ffmpeg", "-y", "-i", str(mp3), str(out_wav)])
    mp3.unlink()


def synth_line(text, out_wav, cfg, index):
    engine = cfg.get("engine", "rhvoice")
    raw = Path(str(out_wav) + ".raw.wav")
    if engine == "file":
        run(["ffmpeg", "-y", "-i", cfg["files"][index], str(raw)])
    elif engine == "elevenlabs":
        synth_elevenlabs(text, raw, cfg)
    else:
        synth_rhvoice(text, raw, cfg)
    tempo = float(cfg.get("tempo", 1.0))
    chain = TRIM
    if abs(tempo - 1) > 1e-3:
        chain += f",atempo={tempo}"
    if cfg.get("polish", True):
        chain += "," + POLISH
    run(["ffmpeg", "-y", "-i", str(raw), "-af", chain, "-ar", "44100", "-ac", "1", str(out_wav)])
    raw.unlink()


def build_voice(episode: dict, workdir: Path) -> list:
    """Синтезирует все реплики. Возвращает список {text, wav, dur} в порядке шотов.

    Реплика целиком из цензуры ({...} без замены) озвучивается «пиком»
    длиной beep_sec — его подставляет рендер, здесь только длительность.
    """
    cfg = dict(episode.get("voice", {}))
    vdir = workdir / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    lines = [ln for shot in episode["shots"] for ln in shot.get("lines", [])]
    result = []
    for i, line in enumerate(lines):
        text = spoken_text(line)
        if not re.search(r"[\wА-Яа-яЁё]", text):
            result.append({"text": line, "wav": None, "dur": float(cfg.get("beep_sec", 0.45))})
            continue
        key = hashlib.md5(json.dumps([text, cfg], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
        wav = vdir / f"{i:03d}_{key}.wav"
        if not wav.exists():
            synth_line(text, wav, cfg, i)
        result.append({"text": line, "wav": str(wav), "dur": duration(wav)})
    return result


if __name__ == "__main__":
    import sys
    ep = json.loads(Path(sys.argv[1]).read_text())
    work = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(sys.argv[1]).parent / "build"
    for r in build_voice(ep, work):
        print(f"{r['dur']:5.2f}s  {r['text']}")
