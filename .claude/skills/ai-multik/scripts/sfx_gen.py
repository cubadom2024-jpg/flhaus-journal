#!/usr/bin/env python3
"""Процедурная библиотека звуковых эффектов для мультиков «Что если ты...».

Все звуки синтезируются с нуля (numpy), поэтому они свободны от прав (CC0):
их можно использовать в коммерческих роликах без указания авторства.

Запуск:  python3 sfx_gen.py [папка]   (по умолчанию ../assets/sfx)
"""
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
rng = np.random.default_rng(7)


def t(dur):
    return np.arange(int(SR * dur)) / SR


def env(n, a=0.005, r=0.1, curve=4.0):
    """Атака + экспоненциальный спад."""
    x = np.ones(n)
    na = max(1, int(SR * a))
    x[:na] = np.linspace(0, 1, na)
    tail = np.arange(n - na) / SR
    x[na:] = np.exp(-tail * curve / max(r, 1e-3))
    return x


def noise(n):
    return rng.uniform(-1, 1, n)


def lowpass(x, cutoff):
    """Однополюсный ФНЧ; cutoff может быть массивом (развёртка)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def bandpass(x, lo, hi):
    return lowpass(x, hi) - lowpass(x, lo)


def sweep(f0, f1, dur, shape="exp"):
    tt = t(dur)
    if shape == "exp":
        f = f0 * (f1 / f0) ** (tt / dur)
    else:
        f = np.linspace(f0, f1, len(tt))
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def norm(x, peak=0.89):
    m = np.max(np.abs(x)) or 1
    return x / m * peak


def fade(x, ms=8):
    n = int(SR * ms / 1000)
    x = x.copy()
    x[:n] *= np.linspace(0, 1, n)
    x[-n:] *= np.linspace(1, 0, n)
    return x


# ---------- переходы ----------

def whoosh(dur=0.45, lo=300, hi=4000):
    n = int(SR * dur)
    tt = np.linspace(0, 1, n)
    shape = np.sin(np.pi * tt) ** 2
    cut = lo + (hi - lo) * np.sin(np.pi * tt)
    return fade(norm(lowpass(noise(n), cut) * shape))


def swoosh_fast():
    return whoosh(0.22, 600, 6000)


def whoosh_down():
    n = int(SR * 0.5)
    tt = np.linspace(0, 1, n)
    cut = 5000 * (1 - tt) + 200
    return fade(norm(lowpass(noise(n), cut) * np.sin(np.pi * tt) ** 1.5))


def riser(dur=1.2):
    n = int(SR * dur)
    tt = np.linspace(0, 1, n)
    x = lowpass(noise(n), 200 + 6000 * tt ** 2) * tt ** 2
    x += 0.3 * sweep(200, 1200, dur) * tt ** 2
    return fade(norm(x))


# ---------- появление стикеров / плашек ----------

def pop():
    tt = t(0.09)
    f = 900 * np.exp(-tt * 40) + 300
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), 0.001, 0.05)
    return fade(norm(x), 2)


def bubble_pop():
    tt = t(0.14)
    f = 400 + 1600 * tt / 0.14
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), 0.002, 0.08)
    return fade(norm(x), 2)


def stamp():
    """Глухой удар печати — для плашек вроде «БЫВШАЯ»."""
    n = int(SR * 0.25)
    body = np.sin(2 * np.pi * np.cumsum(120 * np.exp(-t(0.25) * 12) + 50) / SR)
    x = body * env(n, 0.001, 0.12) + 0.6 * lowpass(noise(n), 2500) * env(n, 0.001, 0.03)
    return fade(norm(x), 2)


def thud():
    n = int(SR * 0.3)
    x = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t(0.3) * 8) + 40) / SR) * env(n, 0.001, 0.15)
    return fade(norm(x + 0.2 * lowpass(noise(n), 800) * env(n, 0.001, 0.05)), 2)


def click():
    n = int(SR * 0.03)
    return fade(norm(bandpass(noise(n), 1500, 6000) * env(n, 0.0005, 0.01)), 1)


def ding():
    tt = t(1.2)
    x = sum(a * np.sin(2 * np.pi * f * tt) for f, a in [(1318, 1), (2637, 0.4), (3951, 0.15)])
    return fade(norm(x * env(len(tt), 0.002, 0.6)))


def success():
    """Галочка / «одобрено»: два восходящих тона."""
    a = ding()[: int(SR * 0.18)] * 0.8
    tt = t(0.6)
    b = sum(k * np.sin(2 * np.pi * f * tt) for f, k in [(1760, 1), (3520, 0.3)]) * env(len(tt), 0.002, 0.35)
    return fade(norm(np.concatenate([a, b])))


def error_buzz():
    tt = t(0.35)
    x = np.sign(np.sin(2 * np.pi * 110 * tt)) * 0.5 + np.sign(np.sin(2 * np.pi * 116 * tt)) * 0.5
    return fade(norm(lowpass(x, 2000) * env(len(tt), 0.005, 0.3, 2)))


def sparkle():
    out = np.zeros(int(SR * 0.9))
    for i in range(9):
        f = rng.uniform(2500, 6000)
        s = int(rng.uniform(0, 0.6) * SR)
        tt = t(0.25)
        g = np.sin(2 * np.pi * f * tt) * env(len(tt), 0.001, 0.12)
        out[s:s + len(g)] += g[: len(out) - s]
    return fade(norm(out))


# ---------- комедийные ----------

def boing():
    tt = t(0.6)
    f = 180 + 120 * np.sin(2 * np.pi * 9 * tt) * np.exp(-tt * 4)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(tt), 0.002, 0.4, 3)
    return fade(norm(x))


def record_scratch():
    n = int(SR * 0.45)
    tt = np.linspace(0, 1, n)
    rate = np.sin(np.pi * tt * 2.5) * 0.9
    ph = np.cumsum(np.abs(rate)) * 0.6
    idx = (ph * 200).astype(int) % 4096
    grain = lowpass(noise(4096), 3500)
    x = grain[idx] * (0.4 + np.abs(rate)) * np.sin(np.pi * tt)
    return fade(norm(x))


def censor_beep(dur=0.45, f=1000):
    tt = t(dur)
    return fade(norm(np.sin(2 * np.pi * f * tt)) * 0.7, 5)


def censor_duck(dur=0.4):
    """Двухтональный «пик-пик», как в разборе (~1.5 и ~2.3 кГц)."""
    tt = t(dur)
    x = np.sin(2 * np.pi * 1500 * tt) + 0.7 * np.sin(2 * np.pi * 2300 * tt)
    return fade(norm(x) * 0.6, 5)


def splat():
    """Шлепок (грязь/краска об стену)."""
    n = int(SR * 0.35)
    x = lowpass(noise(n), 1200) * env(n, 0.001, 0.12, 5)
    x += 0.7 * np.sin(2 * np.pi * np.cumsum(220 * np.exp(-t(0.35) * 18) + 60) / SR) * env(n, 0.001, 0.08)
    wet = lowpass(noise(n), 400) * env(n, 0.03, 0.25) * 0.4
    return fade(norm(x + wet), 2)


def squish():
    n = int(SR * 0.4)
    tt = np.linspace(0, 1, n)
    x = bandpass(noise(n), 200, 900 + 1500 * np.sin(np.pi * tt * 3) ** 2) * np.sin(np.pi * tt)
    return fade(norm(x))


def slide_whistle_down():
    return fade(norm(sweep(1800, 300, 0.7, "lin") * env(int(SR * 0.7), 0.01, 0.7, 1.5)))


def slide_whistle_up():
    return fade(norm(sweep(300, 1800, 0.6, "lin") * np.linspace(0.6, 1, int(SR * 0.6))))


def cartoon_run():
    """Быстрые шажки (погоня с топором)."""
    out = np.zeros(int(SR * 1.2))
    for i in range(14):
        s = int(i * 0.085 * SR)
        g = thud()[: int(SR * 0.06)] * (0.5 + 0.5 * (i % 2))
        out[s:s + len(g)] += g
    return fade(norm(out))


def gasp_whoosh():
    """«Вздох» — мягкий шумовой выдох."""
    n = int(SR * 0.8)
    tt = np.linspace(0, 1, n)
    x = bandpass(noise(n), 400, 2500) * np.sin(np.pi * tt) ** 2 * (1 - 0.5 * tt)
    return fade(norm(x) * 0.7)


def crickets():
    out = np.zeros(int(SR * 2.0))
    for k in range(6):
        s = int((0.1 + k * 0.3) * SR)
        tt = t(0.12)
        g = np.sin(2 * np.pi * 4500 * tt) * (np.sin(2 * np.pi * 60 * tt) > 0) * env(len(tt), 0.005, 0.1, 1)
        out[s:s + len(g)] += g
    return fade(norm(out) * 0.6)


def dun_dun():
    """Драматический удар «дан-дан-дааан»."""
    parts = []
    for f, d in [(98, 0.25), (92, 0.25), (82, 1.1)]:
        tt = t(d)
        x = sum(a * np.sin(2 * np.pi * f * h * tt) for h, a in [(1, 1), (2, 0.5), (3, 0.3), (4, 0.2)])
        parts.append(x * env(len(tt), 0.005, d, 2))
    return fade(norm(np.concatenate(parts)))


def sad_trombone():
    parts = []
    for f, d in [(392, 0.35), (370, 0.35), (349, 0.35), (330, 1.0)]:
        tt = t(d)
        vib = 1 + (0.012 * np.sin(2 * np.pi * 6 * tt) if d > 0.5 else 0)
        ph = np.cumsum(f * vib) / SR
        x = sum(a * np.sin(2 * np.pi * h * ph) for h, a in [(1, 1), (2, 0.6), (3, 0.4), (4, 0.25)])
        parts.append(lowpass(x, 2500) * env(len(tt), 0.02, d, 1.5))
    return fade(norm(np.concatenate(parts)))


# ---------- предметы и интерьер ----------

def clock_tick(n_ticks=4, interval=0.5):
    out = np.zeros(int(SR * n_ticks * interval))
    for i in range(n_ticks):
        g = bandpass(noise(int(SR * 0.02)), 2500, 7000) * env(int(SR * 0.02), 0.0005, 0.006)
        if i % 2:
            g *= 0.7
        s = int(i * interval * SR)
        out[s:s + len(g)] += g
    return fade(norm(out), 2)


def clock_fast():
    """Ускоренные часы — «прошло время»."""
    return clock_tick(16, 0.07)


def camera_shutter():
    a = click()
    gap = np.zeros(int(SR * 0.06))
    b = bandpass(noise(int(SR * 0.05)), 800, 5000) * env(int(SR * 0.05), 0.001, 0.02)
    return fade(norm(np.concatenate([a, gap, b])), 1)


def polaroid():
    """Щелчок + выезд снимка."""
    shut = camera_shutter()
    n = int(SR * 0.6)
    motor = (np.sign(np.sin(2 * np.pi * 85 * t(0.6))) * 0.3 + bandpass(noise(n), 300, 1500) * 0.5) * np.sin(np.pi * np.linspace(0, 1, n))
    return fade(norm(np.concatenate([shut, lowpass(motor, 1800)])))


def pencil_scribble(dur=1.0):
    n = int(SR * dur)
    tt = np.arange(n) / SR
    strokes = (np.sin(2 * np.pi * 7 * tt + 2 * np.sin(2 * np.pi * 1.3 * tt)) > -0.2).astype(float)
    x = bandpass(noise(n), 2000, 8000) * lowpass(strokes, 60)
    return fade(norm(x) * 0.8)


def marker_squeak():
    tt = t(0.35)
    f = 2200 + 400 * np.sin(2 * np.pi * 3 * tt)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.3 + bandpass(noise(len(tt)), 2000, 6000)
    return fade(norm(x * np.sin(np.pi * np.linspace(0, 1, len(tt)))))


def paper_flip():
    n = int(SR * 0.18)
    x = bandpass(noise(n), 1000, 7000) * np.sin(np.pi * np.linspace(0, 1, n)) ** 0.5
    return fade(norm(x), 2)


def calendar_flip():
    out = np.concatenate([paper_flip(), np.zeros(int(SR * 0.05)), paper_flip() * 0.7])
    return norm(out)


def door_creak():
    tt = t(1.0)
    f = 300 + 150 * np.sin(2 * np.pi * 0.7 * tt)
    pulses = (np.sin(2 * np.pi * np.cumsum(f) / SR) > 0.95).astype(float)
    x = lowpass(pulses, 3000) + 0.2 * bandpass(noise(len(tt)), 400, 2000)
    return fade(norm(x * np.sin(np.pi * np.linspace(0, 1, len(tt)))))


def snowball_hit():
    n = int(SR * 0.3)
    x = lowpass(noise(n), 3000) * env(n, 0.001, 0.08, 5)
    x += 0.5 * lowpass(noise(n), 600) * env(n, 0.02, 0.2)
    return fade(norm(x), 2)


def shovel_dig():
    out = np.zeros(int(SR * 1.2))
    for i in range(3):
        s = int(i * 0.38 * SR)
        g = np.concatenate([bandpass(noise(int(SR * 0.12)), 500, 4000) * env(int(SR * 0.12), 0.002, 0.08), snowball_hit()[: int(SR * 0.15)] * 0.6])
        out[s:s + len(g)] += g
    return fade(norm(out))


def heartbeat():
    out = np.zeros(int(SR * 1.6))
    for s0 in (0.0, 0.25, 0.8, 1.05):
        g = thud()[: int(SR * 0.18)] * (1 if s0 in (0.0, 0.8) else 0.7)
        s = int(s0 * SR)
        out[s:s + len(g)] += g
    return fade(norm(lowpass(out, 400)))


def angel_choir():
    tt = t(2.0)
    x = np.zeros(len(tt))
    for f in (523.25, 659.25, 783.99, 1046.5):
        for d in (-1.5, 0, 1.5):
            x += np.sin(2 * np.pi * (f + d) * tt)
    a = np.minimum(tt / 0.4, 1) * np.minimum((2.0 - tt) / 0.8, 1)
    return fade(norm(lowpass(x, 3000) * a) * 0.8)


def tv_glitch():
    n = int(SR * 0.3)
    x = np.repeat(noise(n // 200 + 1), 200)[:n] * 0.6 + bandpass(noise(n), 1000, 8000) * 0.4
    return fade(norm(x), 2)


def notification():
    a = np.sin(2 * np.pi * 988 * t(0.09)) * env(int(SR * 0.09), 0.002, 0.08)
    b = np.sin(2 * np.pi * 1319 * t(0.25)) * env(int(SR * 0.25), 0.002, 0.2)
    return fade(norm(np.concatenate([a, b])), 2)


def typewriter(n_keys=8):
    out = np.zeros(int(SR * (n_keys * 0.09 + 0.1)))
    for i in range(n_keys):
        g = click() * rng.uniform(0.6, 1)
        s = int((i * 0.09 + rng.uniform(0, 0.02)) * SR)
        out[s:s + len(g)] += g
    return norm(out)


def outro_jingle():
    parts = []
    for f in (523.25, 659.25, 783.99, 1046.5):
        tt = t(0.14)
        parts.append(np.sin(2 * np.pi * f * tt) * env(len(tt), 0.002, 0.13))
    tt = t(0.8)
    parts.append(sum(np.sin(2 * np.pi * f * tt) for f in (523.25, 659.25, 783.99)) * env(len(tt), 0.002, 0.6))
    return fade(norm(np.concatenate(parts)))


LIBRARY = {
    # переходы
    "whoosh": whoosh, "swoosh_fast": swoosh_fast, "whoosh_down": whoosh_down, "riser": riser,
    # появление элементов
    "pop": pop, "bubble_pop": bubble_pop, "stamp": stamp, "thud": thud, "click": click,
    "ding": ding, "success": success, "error_buzz": error_buzz, "sparkle": sparkle,
    # комедия
    "boing": boing, "record_scratch": record_scratch, "censor_beep": censor_beep, "censor_duck": censor_duck,
    "splat": splat, "squish": squish, "slide_whistle_down": slide_whistle_down,
    "slide_whistle_up": slide_whistle_up, "cartoon_run": cartoon_run, "gasp": gasp_whoosh,
    "crickets": crickets, "dun_dun": dun_dun, "sad_trombone": sad_trombone,
    # предметы
    "clock_tick": clock_tick, "clock_fast": clock_fast, "camera_shutter": camera_shutter,
    "polaroid": polaroid, "pencil_scribble": pencil_scribble, "marker_squeak": marker_squeak,
    "paper_flip": paper_flip, "calendar_flip": calendar_flip, "door_creak": door_creak,
    "snowball_hit": snowball_hit, "shovel_dig": shovel_dig, "heartbeat": heartbeat,
    "angel_choir": angel_choir, "tv_glitch": tv_glitch, "notification": notification,
    "typewriter": typewriter, "outro_jingle": outro_jingle,
}


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    pcm = (x * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "assets" / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in LIBRARY.items():
        write_wav(out / f"{name}.wav", fn())
    print(f"{len(LIBRARY)} SFX -> {out}")


if __name__ == "__main__":
    main()
