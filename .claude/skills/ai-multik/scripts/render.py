#!/usr/bin/env python3
"""Сборка мультика «Что если ты...» из episode.json.

    python3 render.py путь/к/episode.json [--preview] [--out файл.mp4]

Что делает:
  1. озвучивает реплики (voice.py), считает тайминг шотов от длины голоса;
  2. рисует кадры 1080x1920@30: картинка шота с движением камеры, пылинки,
     шапка серии, HUD-счётчики, стикеры/плашки с pop-анимацией, субтитры
     по 2–3 слова с жёлтой подсветкой текущего слова, титул и CTA;
  3. сводит звук: голос + звуковые эффекты (+ музыка, если задана), громкость -14 LUFS;
  4. отдаёт build/<id>.mp4 и build/cover.png.

--preview — 540x960, 15 к/с: быстро проверить тайминг.
Формат episode.json — references/episode-format.md.
"""
import argparse
import json
import math
import random
import re
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FONTS = SKILL / "assets" / "fonts"
SFX_DIR = SKILL / "assets" / "sfx"
sys.path.insert(0, str(HERE))
import voice as voice_mod  # noqa: E402

SR = 44100
W0, H0 = 1080, 1920

# --- палитра оригинала ---
YELLOW = (255, 214, 10)
YELLOW_BOX = (255, 217, 59)
WHITE = (255, 255, 255)
BLACK = (17, 17, 17)
RED = (226, 38, 38)
ORANGE = (245, 140, 30)
DARK = (28, 28, 32)
GREEN_D = (22, 70, 40)
GREEN = (60, 190, 100)
SEPIA_BG = (236, 222, 190)
SEPIA_FG = (110, 72, 40)
INK = (30, 40, 110)

FONT_FILES = {
    "black": "Montserrat_900Black.ttf",
    "xbold": "Montserrat_800ExtraBold.ttf",
    "bold": "Montserrat_700Bold.ttf",
    "hand": "Caveat_700Bold.ttf",
    "mono": "JetBrainsMono_800ExtraBold.ttf",
}

DEFAULT_SFX = {
    "stamp": "stamp", "label": "pop", "big": "whoosh", "bubble": "bubble_pop", "thought": "bubble_pop",
    "list": "paper_flip", "polaroid": "polaroid", "calendar": "calendar_flip", "check": "success",
    "clipboard": "pencil_scribble", "image": "pop", "box": "pop",
}
TRANSITION_SFX = {"whip": "swoosh_fast", "flash": "whoosh", "zoom": "whoosh"}
LABEL_STYLES = {
    # fill, border, text, rotate
    "stamp_red": (WHITE, RED, RED, -7),
    "orange": (ORANGE, ORANGE, BLACK, 0),
    "white_tag": (WHITE, BLACK, BLACK, -4),
    "sepia": (SEPIA_BG, SEPIA_FG, SEPIA_FG, -5),
    "red_outline": (WHITE, RED, RED, -6),
    "yellow": (YELLOW_BOX, BLACK, BLACK, 0),
    "dark": (DARK, DARK, WHITE, 0),
    "green": (GREEN_D, GREEN, WHITE, 0),
}


class Ctx:
    def __init__(self, preview):
        self.s = 0.5 if preview else 1.0
        self.W, self.H = int(W0 * self.s), int(H0 * self.s)
        self.fps = 15 if preview else 30

    def px(self, v):
        return max(1, int(round(v * self.s)))


@lru_cache(maxsize=256)
def font(kind, size):
    return ImageFont.truetype(str(FONTS / FONT_FILES[kind]), size)


def ease_out_back(x, k=1.70158):
    x = min(max(x, 0.0), 1.0) - 1
    return 1 + (k + 1) * x ** 3 + k * x ** 2


def ease_in_out(x):
    x = min(max(x, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * x)


# ------------------------------------------------------------------ текст

def text_size(fnt, text, stroke=0):
    box = fnt.getbbox(text, stroke_width=stroke)
    return box[2] - box[0], box[3] - box[1], box


def draw_text_center(img, xy, text, fnt, fill, stroke=0, stroke_fill=BLACK):
    d = ImageDraw.Draw(img)
    d.text(xy, text, font=fnt, fill=fill, anchor="mm", stroke_width=stroke, stroke_fill=stroke_fill)


def rich_runs(text):
    """'С *БЫВШЕЙ*' -> [('С ', False), ('БЫВШЕЙ', True)]."""
    out = []
    for i, part in enumerate(re.split(r"\*", text)):
        if part:
            out.append((part, i % 2 == 1))
    return out


def draw_rich_line(img, cx, cy, text, fnt, base=WHITE, hl=YELLOW, stroke=0):
    d = ImageDraw.Draw(img)
    runs = rich_runs(text)
    widths = [d.textlength(t, font=fnt) for t, _ in runs]
    x = cx - sum(widths) / 2
    for (t, h), w in zip(runs, widths):
        d.text((x, cy), t, font=fnt, fill=hl if h else base, anchor="lm", stroke_width=stroke, stroke_fill=BLACK)
        x += w


def wrap_words(words, fnt, max_w):
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and fnt.getlength(test) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------ стикеры

def rounded_box(size, fill, border=None, bw=0, radius=12, shadow=True, s=1.0):
    w, h = size
    pad = int(14 * s) if shadow else 0
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((pad + 4 * s, pad + 6 * s, pad + w + 4 * s, pad + h + 6 * s), radius, fill=(0, 0, 0, 90))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(5 * s)))
    ImageDraw.Draw(img).rounded_rectangle((pad, pad, pad + w, pad + h), radius, fill=fill,
                                          outline=border if bw else None, width=bw)
    return img, pad


def st_label(c, sp):
    style = sp.get("style", "white_tag")
    fill, border, tcol, rot = LABEL_STYLES[style]
    rot = sp.get("rotate", rot)
    lines = sp["text"].split("\n")
    kicker = sp.get("kicker")
    fsz = c.px(sp.get("size", 62))
    fb = font("black", fsz)
    fk = font("xbold", int(fsz * 0.5))
    widths = [fb.getlength(t.replace("*", "")) for t in lines]
    lh = int(fsz * 1.12)
    kh = int(fsz * 0.65) if kicker else 0
    padx, pady = c.px(34), c.px(18)
    w = int(max(widths + ([fk.getlength(kicker)] if kicker else [])) + 2 * padx)
    h = int(len(lines) * lh + kh + 2 * pady)
    bw = c.px(7 if style in ("stamp_red", "red_outline") else 5)
    img, pad = rounded_box((w, h), fill + (255,), border + (255,), bw, c.px(14), s=c.s)
    y = pad + pady
    if kicker:
        draw_text_center(img, (pad + w / 2, y + kh / 2), kicker, fk, tcol)
        y += kh
    for t in lines:
        draw_rich_line(img, pad + w / 2, y + lh / 2, t, fb, base=tcol, hl=YELLOW if fill != YELLOW_BOX else RED)
        y += lh
    return img.rotate(rot, resample=Image.BICUBIC, expand=True)


def st_big(c, sp):
    lines = sp["text"].split("\n")
    fsz = c.px(sp.get("size", 150))
    f = font("black", fsz)
    st = max(3, fsz // 14)
    lh = int(fsz * 0.95)
    w = int(max(f.getlength(t) for t in lines) + 4 * st + c.px(20))
    h = lh * len(lines) + 4 * st + c.px(20)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for i, t in enumerate(lines):
        draw_text_center(img, (w / 2 + st, h / 2 - (len(lines) - 1) * lh / 2 + i * lh + st), t, f, (0, 0, 0, 140), st, (0, 0, 0, 140))
        draw_text_center(img, (w / 2, h / 2 - (len(lines) - 1) * lh / 2 + i * lh), t, f, tuple(sp.get("color", YELLOW)), st, BLACK)
    return img.rotate(sp.get("rotate", 0), resample=Image.BICUBIC, expand=True)


def st_bubble(c, sp, thought=False):
    text = sp.get("text", "")
    fsz = c.px(sp.get("size", 70))
    f = font("black", fsz)
    tw = f.getlength(text) if text else 0
    inner = None
    if sp.get("image"):
        inner = load_rgba(sp["image"], c.px(sp.get("image_w", 380)))
    w = int(max(tw + c.px(110), (inner.width + c.px(120)) if inner else 0, c.px(200)))
    h = int(max(fsz * 1.9, (inner.height + c.px(110)) if inner else 0))
    tail = c.px(90)
    img = Image.new("RGBA", (w + c.px(20), h + tail + c.px(20)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw = c.px(6)
    o = c.px(10)
    if thought:
        d.ellipse((o, o, o + w, o + h), fill=WHITE, outline=(220, 220, 225), width=bw // 2)
        for k, r in enumerate((c.px(26), c.px(16))):
            cx = o + w * 0.4 - k * c.px(30)
            cy = o + h + c.px(18) + k * c.px(40)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE, outline=(220, 220, 225), width=bw // 2)
    else:
        side = sp.get("tail", "left")
        bx = o + w * (0.3 if side == "left" else 0.7)
        tip = (bx - c.px(50) if side == "left" else bx + c.px(50), o + h + tail - c.px(20))
        d.polygon([(bx - c.px(30), o + h - c.px(20)), (bx + c.px(30), o + h - c.px(20)), tip], fill=WHITE, outline=BLACK)
        d.line([(bx - c.px(30), o + h - c.px(25)), tip, (bx + c.px(30), o + h - c.px(25))], fill=BLACK, width=bw)
        d.ellipse((o, o, o + w, o + h), fill=WHITE, outline=BLACK, width=bw)
    if inner:
        img.alpha_composite(inner, (int(o + (w - inner.width) / 2), int(o + (h - inner.height) / 2)))
    if text:
        draw_text_center(img, (o + w / 2, o + h / 2), text, f, BLACK)
        if sp.get("strike"):
            d.line([(o + w / 2 - tw / 2 - c.px(10), o + h / 2 + c.px(4)), (o + w / 2 + tw / 2 + c.px(10), o + h / 2 - c.px(4))], fill=RED, width=c.px(9))
    return img.rotate(sp.get("rotate", 0), resample=Image.BICUBIC, expand=True)


def st_list(c, sp, n_items):
    items = sp["items"][:n_items]
    title = sp.get("title", "")
    fw = c.px(sp.get("width", 300))
    fh_item = c.px(64)
    h = c.px(110) + fh_item * max(len(sp["items"]), 1) + c.px(40)
    img = Image.new("RGBA", (fw + c.px(30), h + c.px(30)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    paper = (248, 236, 210)
    d.rectangle((c.px(15), c.px(30), fw + c.px(15), h), fill=paper, outline=(200, 180, 140), width=c.px(3))
    for y in (c.px(18), h - c.px(4)):
        d.rounded_rectangle((c.px(5), y, fw + c.px(25), y + c.px(26)), c.px(12), fill=(225, 205, 160), outline=(180, 150, 100), width=c.px(3))
    draw_text_center(img, (fw / 2 + c.px(15), c.px(85)), title, font("black", c.px(44)), RED)
    for i, it in enumerate(items):
        draw_text_center(img, (fw / 2 + c.px(15), c.px(150) + i * fh_item), it, font("hand", c.px(54)), (60, 50, 50))
    return img.rotate(sp.get("rotate", 0), resample=Image.BICUBIC, expand=True)


def st_polaroid(c, sp):
    pw = c.px(sp.get("width", 520))
    photo = load_rgba(sp["image"], pw - c.px(50)) if sp.get("image") else Image.new("RGBA", (pw - c.px(50), pw - c.px(50)), (200, 200, 200, 255))
    ph = photo.height + c.px(170)
    card, pad = rounded_box((pw, ph), (252, 252, 250, 255), (225, 225, 220, 255), c.px(2), c.px(6), s=c.s)
    card.alpha_composite(photo, (pad + c.px(25), pad + c.px(25)))
    if sp.get("caption"):
        draw_text_center(card, (pad + pw / 2, pad + photo.height + c.px(95)), sp["caption"], font("hand", c.px(80)), INK)
    if sp.get("name"):
        draw_text_center(card, (pad + pw / 2, pad + photo.height + c.px(75)), sp["name"], font("black", c.px(48)), BLACK)
    out = card
    if sp.get("note"):
        note = st_label(c, {"text": sp["note"], "style": "white_tag", "size": 34, "rotate": 0})
        out = Image.new("RGBA", (max(card.width, note.width), card.height + note.height // 2), (0, 0, 0, 0))
        out.alpha_composite(card, ((out.width - card.width) // 2, 0))
        out.alpha_composite(note, ((out.width - note.width) // 2, card.height - note.height // 2))
    return out.rotate(sp.get("rotate", -4), resample=Image.BICUBIC, expand=True)


def st_calendar(c, sp, value):
    w, h = c.px(250), c.px(270)
    img, pad = rounded_box((w, h), (250, 250, 250, 255), (210, 210, 210, 255), c.px(2), c.px(16), s=c.s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + w, pad + c.px(70)), c.px(16), fill=RED)
    d.rectangle((pad, pad + c.px(40), pad + w, pad + c.px(70)), fill=RED)
    draw_text_center(img, (pad + w / 2, pad + c.px(36)), sp.get("header", "ДЕНЬ"), font("black", c.px(38)), WHITE)
    draw_text_center(img, (pad + w / 2, pad + c.px(170)), str(value), font("black", c.px(150)), BLACK)
    for x in (w * 0.3, w * 0.7):
        d.ellipse((pad + x - c.px(10), pad - c.px(10), pad + x + c.px(10), pad + c.px(10)), fill=(120, 120, 120))
    return img.rotate(sp.get("rotate", -3), resample=Image.BICUBIC, expand=True)


def st_check(c, sp):
    r = c.px(sp.get("size", 70))
    img = Image.new("RGBA", (2 * r + 8, 2 * r + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 4 + 2 * r, 4 + 2 * r), fill=WHITE, outline=GREEN, width=max(3, r // 7))
    d.line([(r * 0.55 + 4, r * 1.05 + 4), (r * 0.9 + 4, r * 1.4 + 4), (r * 1.5 + 4, r * 0.65 + 4)], fill=GREEN, width=max(4, r // 4), joint="curve")
    return img


def st_clipboard(c, sp, n_chars):
    w, h = c.px(sp.get("width", 760)), c.px(sp.get("height", 900))
    img = Image.new("RGBA", (w + c.px(30), h + c.px(60)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((c.px(15), c.px(40), w + c.px(15), h + c.px(40)), c.px(30), fill=(70, 130, 210), outline=(40, 90, 170), width=c.px(5))
    d.rectangle((c.px(55), c.px(90), w - c.px(25), h), fill=(250, 250, 252))
    for y in range(c.px(230), h - c.px(20), c.px(62)):
        d.line([(c.px(75), y), (w - c.px(45), y)], fill=(170, 190, 220), width=c.px(2))
    d.rounded_rectangle((w / 2 - c.px(110), c.px(15), w / 2 + c.px(140), c.px(85)), c.px(14), fill=(190, 195, 205), outline=(120, 125, 135), width=c.px(4))
    draw_text_center(img, (w / 2 + c.px(15), c.px(150)), sp.get("title", "НАБЛЮДЕНИЕ"), font("xbold", c.px(36)), (90, 100, 120))
    text = sp["text"][:n_chars]
    fh = font("hand", c.px(72))
    y = c.px(195)
    for ln in wrap_words(text.split(" "), fh, w - c.px(160)):
        d.text((c.px(90), y), " ".join(ln), font=fh, fill=INK)
        y += c.px(62)
    return img.rotate(sp.get("rotate", 0), resample=Image.BICUBIC, expand=True)


def load_rgba(path, width):
    if not Path(path).exists():  # черновик: картинки ещё нет
        im = Image.new("RGBA", (400, 400), (205, 200, 190, 255))
        ImageDraw.Draw(im).text((200, 200), Path(path).name, font=font("bold", 40), fill=(110, 100, 90), anchor="mm")
    else:
        im = Image.open(path).convert("RGBA")
    return im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)


# ------------------------------------------------------------------ сцена

class Episode:
    def __init__(self, path, preview):
        self.path = Path(path)
        self.root = self.path.parent
        self.ep = json.loads(self.path.read_text())
        self.c = Ctx(preview)
        self.work = self.root / "build"
        self.work.mkdir(exist_ok=True)
        self.particles = [(random.Random(i).random(), random.Random(i * 7 + 1).random(), random.Random(i * 13 + 2).uniform(2, 6),
                           random.Random(i * 17 + 3).uniform(0.15, 0.45)) for i in range(26)]

    # ---------- тайминг
    def layout(self):
        voice = voice_mod.build_voice(self.ep, self.work)
        gap = float(self.ep.get("voice", {}).get("gap", 0.06))
        t = 0.0
        vi = 0
        self.timeline = []
        self.voice_clips = []
        self.captions = []
        self.beeps = []
        for si, shot in enumerate(self.ep["shots"]):
            start = t
            lt = t + float(shot.get("lead", 0.0))
            for line in shot.get("lines", []):
                v = voice[vi]
                vi += 1
                if v["wav"]:
                    self.voice_clips.append((lt, v["wav"]))
                self.add_captions(line, lt, v["dur"])
                lt += v["dur"] + gap
            end = max(lt - gap + float(shot.get("tail", 0.12)), start + float(shot.get("dur", 0)))
            if not shot.get("lines") and not shot.get("dur"):
                end = start + 1.5
            self.timeline.append((start, end, shot))
            t = end
        self.total = t

    def add_captions(self, line, t0, dur):
        """Режет реплику на куски по 2–3 слова и раздаёт слова по времени."""
        tokens = []
        for raw in line.split():
            m = voice_mod.CENSOR_RE.search(raw)
            if m:
                disp = voice_mod.CENSOR_RE.sub(m.group(1), raw)
                spoken = m.group(2) or "бииип"
                tokens.append((disp, spoken, True))
            else:
                tokens.append((raw, raw, False))
        weights = [len(sp) + 2 for _, sp, _ in tokens]
        total = sum(weights) or 1
        times, acc = [], t0
        for wgt in weights:
            d = dur * wgt / total
            times.append((acc, acc + d))
            acc += d
        for (disp, _, cens), (a, b) in zip(tokens, times):
            if cens:
                self.beeps.append((a, b - a))
        maxw = int(self.ep.get("caption_words", 3))
        chunks, cur = [], []
        for i, tok in enumerate(tokens):
            cur.append(i)
            nxt = tokens[i + 1][0] if i + 1 < len(tokens) else ""
            full = len(cur) >= maxw or sum(len(tokens[j][0]) for j in cur) > 20
            if tok[0][-1] in ".,!?:;—»" or (full and nxt and not (len(tok[0]) <= 2 and tok[0].isalpha())):
                chunks.append(cur)
                cur = []
            elif full and len(cur) > 1 and len(tok[0]) <= 2:  # не оставляем предлог в конце куска
                chunks.append(cur[:-1])
                cur = cur[-1:]
        if cur:
            chunks.append(cur)
        for ch in chunks:
            words = [tokens[j][0].upper() for j in ch]
            wt = [times[j] for j in ch]
            self.captions.append((wt[0][0], wt[-1][1], words, wt))

    # ---------- картинка шота
    @lru_cache(maxsize=8)
    def base_image(self, si):
        shot = self.ep["shots"][si]
        W, H = self.c.W, self.c.H
        over = 1.3
        p = shot.get("image")
        if p and (self.root / p).exists():
            im = Image.open(self.root / p).convert("RGB")
        else:
            im = placeholder(si, shot, W, H)
        im = ImageOps.fit(im, (int(W * over), int(H * over)), Image.LANCZOS)
        for fx in shot.get("fx", []):
            im = apply_fx(im, fx)
        return im

    def camera(self, si, shot, lt, dur):
        """Возвращает кадр шота в момент lt (сек от начала шота)."""
        W, H = self.c.W, self.c.H
        src = self.base_image(si)
        sw, sh = src.size
        motion = shot.get("motion", "zoom_in")
        fx, fy = shot.get("focus", [0.5, 0.5])
        p = ease_in_out(lt / max(dur, 0.01))
        z0, z1 = {"zoom_in": (1.0, 1.12), "zoom_out": (1.14, 1.0), "static": (1.03, 1.04),
                  "pan_left": (1.12, 1.12), "pan_right": (1.12, 1.12), "pan_up": (1.12, 1.12), "pan_down": (1.12, 1.12),
                  "punch": (1.0, 1.3), "shake": (1.06, 1.08), "bounce": (1.04, 1.06)}.get(motion, (1.0, 1.1))
        if motion == "punch":
            z = z0 + (z1 - z0) * ease_out_back(lt / 0.22, 1.2) if lt < 0.22 else z1 + 0.04 * p
        else:
            z = z0 + (z1 - z0) * p
        z *= float(shot.get("zoom", 1.0))
        vw, vh = sw / 1.3 / z, sh / 1.3 / z  # размер окна в координатах исходника
        cx = fx * sw
        cy = fy * sh
        if motion.startswith("pan_"):
            span = 0.12 * sw
            off = (p - 0.5) * span
            if motion == "pan_left":
                cx -= off
            elif motion == "pan_right":
                cx += off
            elif motion == "pan_up":
                cy -= off * sh / sw
            else:
                cy += off * sh / sw
        if motion == "shake" and lt < 0.5:
            a = (0.5 - lt) * 0.03 * sw
            cx += math.sin(lt * 90) * a
            cy += math.cos(lt * 70) * a
        if motion == "bounce":
            cy += math.sin(lt * 12) * 0.004 * sh * max(0, 1 - lt)
        cx = min(max(cx, vw / 2), sw - vw / 2)
        cy = min(max(cy, vh / 2), sh - vh / 2)
        x0, y0 = cx - vw / 2, cy - vh / 2
        return src.transform((W, H), Image.EXTENT, (x0, y0, x0 + vw, y0 + vh), Image.BILINEAR)

    # ---------- слои
    def draw_particles(self, img, t):
        d = ImageDraw.Draw(img, "RGBA")
        for (px, py, r, sp) in self.particles:
            x = (px * self.c.W + math.sin(t * sp * 2 + py * 9) * 30 * self.c.s) % self.c.W
            y = (py * self.c.H - t * sp * 40 * self.c.s) % self.c.H
            rr = r * self.c.s
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(255, 255, 255, 70))

    def draw_header(self, img, t):
        c = self.c
        d = ImageDraw.Draw(img, "RGBA")
        f = font("xbold", c.px(30))
        txt = f"{self.ep.get('series', 'ЧТО ЕСЛИ ТЫ...')} · {self.ep.get('episode', '')}".upper()
        x, y = c.px(44), c.px(62)
        a = int(160 + 95 * (0.5 + 0.5 * math.sin(t * 5)))
        d.ellipse((x, y - c.px(7), x + c.px(14), y + c.px(7)), fill=(230, 40, 40, a))
        d.text((x + c.px(26) + 2, y + 2), txt, font=f, fill=(0, 0, 0, 120), anchor="lm")
        d.text((x + c.px(26), y), txt, font=f, fill=WHITE, anchor="lm")

    def hud_state(self, t):
        hud = [dict(h) for h in self.ep.get("hud", [])]
        changed_at = {}
        for start, _, shot in self.timeline:
            if start > t:
                break
            for k, v in (shot.get("hud") or {}).items():
                for h in hud:
                    if h["label"] == k and h["value"] != str(v):
                        h["value"] = str(v)
                        changed_at[k] = start
        return hud, changed_at

    def draw_hud(self, img, t):
        hud, changed = self.hud_state(t)
        if not hud:
            return
        c = self.c
        f = font("mono", c.px(30))
        lines = [(f"{h['label']}:" if len(hud) > 1 and i else f"{h['label']}", h["value"]) for i, h in enumerate(hud)]
        lw = max(f.getlength(l + "  " + v) for l, v in lines)
        pad = c.px(18)
        lh = c.px(40)
        w, h = int(lw + 2 * pad), int(len(lines) * lh + 2 * pad - c.px(6))
        x1, y0 = c.W - c.px(40), c.px(100)
        x0 = x1 - w
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle((x0, y0, x1, y0 + h), c.px(12), fill=(25, 25, 30, 225))
        for i, (l, v) in enumerate(lines):
            yy = y0 + pad + lh * i + lh / 2 - c.px(3)
            vw = f.getlength(v)
            d.text((x1 - pad - vw - c.px(10), yy), l, font=f, fill=WHITE, anchor="rm")
            ago = t - changed.get(hud[i]["label"], -9)
            col = YELLOW
            if 0 <= ago < 0.5:
                col = RED if int(ago * 10) % 2 == 0 else YELLOW
            d.text((x1 - pad, yy), v, font=f, fill=col, anchor="rm")

    def draw_caption(self, img, t):
        cur = None
        for cap in self.captions:
            if cap[0] - 0.02 <= t < cap[1] + 0.02:
                cur = cap
        if not cur:
            return
        _, _, words, wt = cur
        active = max([i for i, (a, _) in enumerate(wt) if a <= t] or [0])
        c = self.c
        f = font("black", c.px(66))
        st = c.px(6)
        lines = [[int(i) for i in ln] for ln in wrap_words([str(i) for i in range(len(words))], _IdxFont(f, words), c.W * 0.84)]
        lh = c.px(78)
        y = c.H * float(self.ep.get("caption_y", 0.835)) - (len(lines) - 1) * lh / 2
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        top = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ds, dt = ImageDraw.Draw(shadow), ImageDraw.Draw(top)
        for ln in lines:
            txt = [words[i] for i in ln]
            ws = [f.getlength(w) for w in txt]
            space = f.getlength(" ")
            x = c.W / 2 - (sum(ws) + space * (len(ws) - 1)) / 2
            for i, wd, wv in zip(ln, txt, ws):
                ds.text((x + c.px(4), y + c.px(6)), wd, font=f, fill=(0, 0, 0, 150), anchor="lm", stroke_width=st, stroke_fill=(0, 0, 0, 150))
                dt.text((x, y), wd, font=f, fill=YELLOW if i == active else WHITE, anchor="lm", stroke_width=st, stroke_fill=BLACK)
                x += wv + space
            y += lh
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(c.px(4))))
        img.alpha_composite(top)

    def draw_title(self, img, t):
        tc = self.ep.get("title_card")
        if not tc:
            return
        until = float(tc.get("until", self.timeline[0][1]))
        if t >= until:
            return
        c = self.c
        k = 1.0 if t < until - 0.15 else max(0.0, (until - t) / 0.15)
        fk, fb, fs = font("xbold", c.px(42)), font("black", c.px(104)), font("xbold", c.px(46))
        lines = tc.get("lines", [])
        bw = max([fb.getlength(l.replace("*", "")) for l in lines] + [c.px(600)]) + c.px(110)
        bh = c.px(120) + len(lines) * c.px(118) + (c.px(70) if tc.get("sub") else 0)
        box, pad = rounded_box((int(bw), int(bh)), (24, 22, 28, 235), (230, 170, 190, 255), c.px(3), c.px(28), s=c.s)
        y = pad + c.px(70)
        draw_text_center(box, (pad + bw / 2, y), tc.get("kicker", ""), fk, WHITE)
        y += c.px(100)
        for l in lines:
            draw_rich_line(box, pad + bw / 2, y, l, fb)
            y += c.px(118)
        if tc.get("sub"):
            draw_text_center(box, (pad + bw / 2, y - c.px(20)), tc["sub"], fs, WHITE)
        if k < 1:
            box.putalpha(box.getchannel("A").point(lambda a: int(a * k)))
        img.alpha_composite(box, (int(c.W / 2 - box.width / 2), int(c.H * 0.47 - box.height / 2)))

    def draw_cta(self, img, t):
        cta = self.ep.get("cta")
        if not cta:
            return
        start = self.timeline[-1][0] if not isinstance(cta, dict) else self.total - float(cta.get("dur", self.total - self.timeline[-1][0]))
        text = cta if isinstance(cta, str) else cta["text"]
        if t < start:
            return
        c = self.c
        f = font("black", c.px(58))
        ln = wrap_words(text.upper().split(), f, c.W * 0.72)
        w = int(max(f.getlength(" ".join(l)) for l in ln) + c.px(90))
        h = int(len(ln) * c.px(70) + c.px(70))
        box, pad = rounded_box((w, h), YELLOW_BOX + (255,), BLACK + (255,), c.px(5), c.px(16), s=c.s)
        for i, l in enumerate(ln):
            draw_text_center(box, (pad + w / 2, pad + c.px(35) + c.px(70) * i + c.px(35)), " ".join(l), f, BLACK)
        sc = 0.3 + 0.7 * ease_out_back((t - start) / 0.3)
        b = box.resize((max(1, int(box.width * sc)), max(1, int(box.height * sc))), Image.BICUBIC)
        img.alpha_composite(b, (int(c.W / 2 - b.width / 2), int(c.H * 0.62 - b.height / 2)))
        tag = self.ep.get("tag")
        if tag and t > start + 0.8:
            ft = font("xbold", c.px(36))
            tw = ft.getlength(tag) + c.px(50)
            d = ImageDraw.Draw(img, "RGBA")
            y = c.H * 0.835
            d.rounded_rectangle((c.W / 2 - tw / 2, y - c.px(30), c.W / 2 + tw / 2, y + c.px(30)), c.px(14), fill=(30, 28, 32, 235))
            d.text((c.W / 2, y), tag, font=ft, fill=WHITE, anchor="mm")

    def draw_ai_label(self, img):
        if self.ep.get("ai_label", True):
            ImageDraw.Draw(img, "RGBA").text((self.c.px(26), self.c.H - self.c.px(40)), "AI-generated", font=font("bold", self.c.px(26)), fill=(255, 255, 255, 170), anchor="lm")

    # ---------- стикеры
    @lru_cache(maxsize=512)
    def sticker_img(self, si, k, state):
        sp = self.ep["shots"][si]["stickers"][k]
        c = self.c
        tp = sp["type"]
        if tp in ("label", "stamp", "box"):
            if tp == "stamp":
                sp = {"style": "stamp_red", **sp}
            return st_label(c, sp)
        if tp == "big":
            return st_big(c, sp)
        if tp in ("bubble", "thought"):
            sp = dict(sp)
            if sp.get("image"):
                sp["image"] = str(self.root / sp["image"])
            return st_bubble(c, sp, thought=tp == "thought")
        if tp == "list":
            return st_list(c, sp, state)
        if tp == "polaroid":
            sp = dict(sp)
            if sp.get("image"):
                sp["image"] = str(self.root / sp["image"])
            return st_polaroid(c, sp)
        if tp == "calendar":
            return st_calendar(c, sp, state)
        if tp == "check":
            return st_check(c, sp)
        if tp == "clipboard":
            return st_clipboard(c, sp, state)
        if tp == "image":
            im = load_rgba(self.root / sp["image"], c.px(sp.get("width", 300)))
            return im.rotate(sp.get("rotate", 0), resample=Image.BICUBIC, expand=True)
        raise ValueError(f"неизвестный стикер {tp}")

    def sticker_at(self, sp, shot_start):
        """Момент появления стикера (сек от начала ролика)."""
        if "at_word" in sp:
            caps = [cp for cp in self.captions if cp[0] >= shot_start - 1e-6]
            words = [w for cp in caps for w in cp[3]]
            i = min(int(sp["at_word"]), len(words) - 1)
            return words[i][0] if words else shot_start
        return shot_start + float(sp.get("at", 0.0))

    def draw_stickers(self, img, si, shot, start, end, t):
        c = self.c
        for k, sp in enumerate(shot.get("stickers", [])):
            a = self.sticker_at(sp, start)
            b = a + float(sp["dur"]) if "dur" in sp else end
            if not (a <= t < b):
                continue
            lt = t - a
            tp = sp["type"]
            state = 0
            if tp == "list":
                step = float(sp.get("step", 0.35))
                state = min(len(sp["items"]), 1 + int(lt / step)) if sp.get("reveal", True) else len(sp["items"])
            elif tp == "calendar":
                state = sp.get("to", sp.get("value", 1)) if lt >= float(sp.get("flip_at", 0.5)) else sp.get("from", sp.get("value", 1))
            elif tp == "clipboard":
                cps = float(sp.get("cps", 14))
                state = min(len(sp["text"]), int(lt * cps))
            im = self.sticker_img(si, k, state)
            anim = sp.get("anim", "pop")
            sc, rot, alpha = 1.0, 0.0, 1.0
            if anim == "pop":
                sc = ease_out_back(lt / 0.28, 2.2)
            elif anim == "slam":
                sc = 2.2 - 1.2 * min(1, lt / 0.14)
            elif anim == "fade":
                alpha = min(1, lt / 0.25)
            elif anim == "drop":
                pass
            if sp.get("wobble"):
                rot = math.sin(lt * 6) * 3
            if tp == "calendar":
                fa = float(sp.get("flip_at", 0.5))
                if 0 <= lt - fa < 0.18:
                    sc *= 1 - 0.25 * math.sin(math.pi * (lt - fa) / 0.18)
            if sc <= 0.02:
                continue
            if sc != 1 or rot:
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR)
                if rot:
                    im = im.rotate(rot, resample=Image.BILINEAR, expand=True)
            if alpha < 1:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
            px, py = sp.get("pos", [0.5, 0.3])
            dy = 0
            if anim == "drop":
                dy = -(1 - ease_out_back(lt / 0.35, 1.5)) * c.H * 0.3
            m = c.px(24)
            x = min(max(int(px * c.W - im.width / 2), m), c.W - im.width - m) if im.width < c.W - 2 * m else int(px * c.W - im.width / 2)
            y = min(max(int(py * c.H - im.height / 2), c.px(150)), c.H - im.height - m) + int(dy)
            img.alpha_composite(im, (x, y))

    # ---------- кадр
    def frame(self, t):
        c = self.c
        si = max(i for i, (s, _, _) in enumerate(self.timeline) if s <= t + 1e-9)
        start, end, shot = self.timeline[si]
        lt = t - start
        img = self.camera(si, shot, lt, end - start).convert("RGBA")
        tr = shot.get("transition", "cut")
        if si > 0 and tr == "whip" and lt < 0.16:
            ps, pe, pshot = self.timeline[si - 1]
            prev = self.camera(si - 1, pshot, pe - ps, pe - ps).convert("RGBA")
            k = ease_in_out(lt / 0.16)
            canvas = Image.new("RGBA", img.size)
            canvas.paste(prev, (int(-k * c.W), 0))
            canvas.paste(img, (int((1 - k) * c.W), 0))
            img = canvas.filter(ImageFilter.BoxBlur(c.px(18)))
        if not shot.get("no_particles"):
            self.draw_particles(img, t)
        self.draw_stickers(img, si, shot, start, end, t)
        if not shot.get("clean"):
            self.draw_header(img, t)
            self.draw_hud(img, t)
        self.draw_title(img, t)
        self.draw_cta(img, t)
        if not (self.ep.get("cta") and t >= self.timeline[-1][0]):
            self.draw_caption(img, t)
        self.draw_ai_label(img)
        if si > 0 and tr == "flash" and lt < 0.12:
            wh = Image.new("RGBA", img.size, (255, 255, 255, int(255 * (1 - lt / 0.12))))
            img.alpha_composite(wh)
        return img.convert("RGB")

    # ---------- звук
    def sfx_events(self):
        ev = []
        for si, (start, end, shot) in enumerate(self.timeline):
            tr = shot.get("transition", "cut")
            if si > 0 and tr in TRANSITION_SFX and shot.get("transition_sfx", True):
                ev.append((start - 0.05, TRANSITION_SFX[tr], 0.5))
            for sp in shot.get("stickers", []):
                name = sp.get("sfx", DEFAULT_SFX.get(sp["type"]))
                if name:
                    a = self.sticker_at(sp, start)
                    if sp["type"] == "calendar":
                        a += float(sp.get("flip_at", 0.5)) - 0.05
                    ev.append((a, name, float(sp.get("sfx_vol", 0.55))))
            for s in shot.get("sfx", []):
                ev.append((start + float(s.get("at", 0)), s["name"], float(s.get("vol", 0.6))))
            if shot.get("hud"):
                ev.append((start, "click", 0.4))
        if self.ep.get("cta"):
            ev.append((self.timeline[-1][0], "pop", 0.6))
        return ev

    def mix_audio(self, out_wav):
        n = int((self.total + 0.3) * SR)
        voice = np.zeros(n)
        fx = np.zeros(n)
        for t0, path in self.voice_clips:
            x = read_wav(path)
            s = int(t0 * SR)
            voice[s:s + len(x)] += x[: n - s]
        vol_v = float(self.ep.get("mix", {}).get("voice", 1.0))
        for a, dur in self.beeps:
            s, e = int(a * SR), int((a + dur) * SR)
            voice[s:e] = 0
            tt = np.arange(e - s) / SR
            beep = (np.sin(2 * np.pi * 1500 * tt) + 0.7 * np.sin(2 * np.pi * 2300 * tt)) * 0.18
            fx[s:e] += beep[: n - s]
        for at, name, vol in self.sfx_events():
            p = SFX_DIR / f"{name}.wav"
            if not p.exists():
                p = self.root / name
            if not p.exists():
                print(f"  ! нет звука {name}", file=sys.stderr)
                continue
            x = read_wav(p) * vol * float(self.ep.get("mix", {}).get("sfx", 1.0))
            s = max(0, int(at * SR))
            fx[s:s + len(x)] += x[: n - s]
        mix = voice * vol_v + fx
        music = self.ep.get("music")
        if music:
            mp = self.root / music["file"]
            tmp = self.work / "music.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(mp), "-t", str(self.total + 0.3),
                            "-ac", "1", "-ar", str(SR), str(tmp)], check=True)
            m = read_wav(tmp)[:n]
            env = np.convolve(np.abs(voice), np.ones(4410) / 4410, mode="same")
            duck = np.where(env > 0.01, float(music.get("duck", 0.35)), 1.0)
            duck = np.convolve(duck, np.ones(8820) / 8820, mode="same")
            mix[: len(m)] += m * float(music.get("vol", 0.12)) * duck[: len(m)]
        write_wav(out_wav, mix)

    # ---------- сборка
    def render(self, out):
        self.layout()
        print(f"длительность {self.total:.1f} c, шотов {len(self.timeline)}, кусков субтитров {len(self.captions)}")
        wav = self.work / "mix.wav"
        self.mix_audio(wav)
        c = self.c
        nframes = int(math.ceil(self.total * c.fps))
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{c.W}x{c.H}", "-r", str(c.fps),
            "-i", "-", "-i", str(wav),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=9",
            "-c:v", "libx264", "-preset", "veryfast" if c.s < 1 else "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE)
        for i in range(nframes):
            fr = self.frame(i / c.fps)
            if i == 0:
                fr.save(self.work / "cover.png")
            proc.stdin.write(fr.tobytes())
            if i % (c.fps * 5) == 0:
                print(f"  кадр {i}/{nframes}", flush=True)
        proc.stdin.close()
        proc.wait()
        print(f"готово: {out}")


class _IdxFont:
    """Позволяет wrap_words работать со списком индексов слов."""

    def __init__(self, f, words):
        self.f, self.words = f, words

    def getlength(self, s):
        return self.f.getlength(" ".join(self.words[int(i)] for i in s.split()))


def placeholder(si, shot, W, H):
    rnd = random.Random(si)
    base = [(232, 222, 200), (205, 228, 220), (226, 206, 214), (210, 220, 236)][si % 4]
    im = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(im)
    d.rectangle((0, int(H * 0.68), W, H), fill=tuple(int(v * 0.85) for v in base))
    for _ in range(3):
        x = rnd.randint(0, W)
        d.ellipse((x - 120, H * 0.2, x + 120, H * 0.2 + 240), fill=tuple(int(v * 0.93) for v in base))
    f = font("black", max(20, W // 14))
    d.text((W / 2, H * 0.42), f"ШОТ {si + 1}", font=f, fill=(120, 110, 100), anchor="mm")
    desc = (shot.get("prompt") or "")[:140]
    fs = font("bold", max(12, W // 36))
    y = H * 0.5
    for ln in wrap_words(desc.split(), fs, W * 0.8):
        d.text((W / 2, y), " ".join(ln), font=fs, fill=(120, 110, 100), anchor="mm")
        y += W // 30
    return im


def apply_fx(im, fx):
    if fx == "sepia":
        g = ImageOps.grayscale(im)
        im = Image.merge("RGB", [g.point(lambda v: min(255, int(v * 1.07 + 18))), g.point(lambda v: int(v * 0.95 + 8)), g.point(lambda v: int(v * 0.75))])
        fx = "vignette"
    if fx == "vignette":
        W, H = im.size
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).ellipse((-W * 0.15, -H * 0.1, W * 1.15, H * 1.1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(W * 0.12))
        dark = Image.new("RGB", im.size, (40, 25, 10))
        return Image.composite(im, dark, mask)
    if fx == "desat":
        return Image.blend(im, ImageOps.grayscale(im).convert("RGB"), 0.6)
    if fx == "warm":
        r, g, b = im.split()
        return Image.merge("RGB", [r.point(lambda v: min(255, v + 12)), g, b.point(lambda v: max(0, v - 12))])
    if fx == "bright":
        return Image.blend(im, Image.new("RGB", im.size, (255, 250, 235)), 0.35)
    return im


def read_wav(path):
    with wave.open(str(path)) as w:
        ch, sw, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16 if sw == 2 else np.int32).astype(np.float64)
    x /= 32768.0 if sw == 2 else 2147483648.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    if sr != SR:
        x = np.interp(np.arange(0, len(x), sr / SR), np.arange(len(x)), x)
    return x


def write_wav(path, x):
    peak = np.max(np.abs(x)) or 1
    if peak > 0.98:
        x = x / peak * 0.98
    pcm = (x * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--still", type=float, nargs="*", help="сохранить кадры в эти секунды и выйти")
    a = ap.parse_args()
    ep = Episode(a.episode, a.preview)
    if a.still:
        ep.layout()
        for t in a.still:
            p = ep.work / f"still_{t:05.1f}.png"
            ep.frame(t).save(p)
            print(p)
        return
    out = Path(a.out) if a.out else ep.work / (ep.ep.get("id", "episode") + ("_preview" if a.preview else "") + ".mp4")
    ep.render(out)


if __name__ == "__main__":
    main()
