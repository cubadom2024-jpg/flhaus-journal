#!/usr/bin/env python3
"""Инфографика и обложки в фирменном стиле FL Haus: YAML-описание → картинка 1200 px.

  python3 tools/infographic.py spec.yaml out.png      (или out.jpg)

Фирменный стиль (по соцсетям FL Haus): жёлтый #FFE129, графит #272727, белый;
заголовки — Montserrat ExtraBold/Black капсом на белых и жёлтых плашках, слегка повёрнутых;
второстепенный текст — Manrope.

Типы (поле type):
  photo-cover — обложка: фото + заголовок на плашках
       photo: photos/<файл>.jpg   y: 0.5 (центр кадра по вертикали)   position: top|bottom
       lines: [{text: "СЕМЕЙНАЯ ИПОТЕКА", box: white}, {text: "ДОМ ПОД 6%", box: yellow}, {text: "...", box: none}]
       size: 1200x675 (по умолчанию)
  cover   — обложка без фото: title, kicker
  stats   — 2–4 крупные цифры:  items: [{value: "5–14 дней", label: "монтаж на участке"}, ...]
  bars    — горизонтальные столбцы: items: [{label, value, text, highlight: true}]
  steps   — шаги по порядку: items: ["...", ...]
  compare — две колонки: left: {title, points}, right: {title, points}
  checklist — список с галочками: items: [...]
Общие поля: kicker (жёлтая плашка над заголовком), title, source («Источник: ...» — обязательно для цифр).
"""
import base64
import html
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageEnhance, ImageOps
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "static" / "fonts"
W = 1200
YELLOW, INK = "#FFE129", "#272727"


def b64(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def font_css():
    return (f"@font-face{{font-family:Montserrat;src:url({b64(FONTS / 'Montserrat.ttf', 'font/ttf')});font-weight:100 900}}"
            f"@font-face{{font-family:Manrope;src:url({b64(FONTS / 'Manrope.ttf', 'font/ttf')});font-weight:200 800}}")


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:__W__px;font-family:Manrope,Inter,sans-serif;background:#fff;color:#272727}
.card{padding:64px 72px 52px;background:#fff}
.mk{display:inline-block;font-family:Montserrat;font-weight:800;text-transform:uppercase;letter-spacing:.02em;line-height:1.05;padding:8px 16px 6px}
.mk.y{background:#FFE129;color:#272727}
.mk.w{background:#fff;color:#272727}
.mk.k{background:#272727;color:#fff}
.kick{font-size:24px;transform:rotate(-1.2deg);margin-bottom:22px}
h1{font-family:Montserrat;font-weight:800;font-size:46px;line-height:1.12;letter-spacing:-.01em;margin-bottom:40px;max-width:1040px;text-transform:uppercase}
.src{margin-top:40px;font-size:19px;color:#777;border-top:2px solid #272727;padding-top:16px;display:flex;justify-content:space-between;align-items:center}
.brand{font-family:Montserrat;font-weight:900;color:#272727;font-size:22px;letter-spacing:.02em}
.brand b{background:#FFE129;padding:2px 8px;margin-left:4px}
.stats{display:grid;gap:22px}
.stat{border:2px solid #272727;padding:30px 30px 26px}
.stat .v{font-family:Montserrat;font-weight:900;font-size:56px;letter-spacing:-.02em;line-height:1;display:inline-block;background:linear-gradient(transparent 58%,#FFE129 58%);padding:0 4px}
.stat .l{font-size:25px;color:#444;margin-top:16px;line-height:1.3;font-weight:500}
.bar{margin-bottom:24px}
.bar .t{display:flex;justify-content:space-between;align-items:baseline;font-size:26px;font-weight:600;margin-bottom:10px}
.bar .t b{font-family:Montserrat;font-weight:900;font-size:30px}
.track{height:32px;background:#EFEFEC}
.fill{height:100%;background:#BDBDB8}
.fill.hl{background:#FFE129;box-shadow:inset 0 0 0 2px #272727}
.steps{counter-reset:s;display:grid;gap:16px}
.step{display:flex;gap:24px;align-items:center;border:2px solid #272727;padding:20px 26px;font-size:27px;line-height:1.3;font-weight:600}
.step:before{counter-increment:s;content:counter(s);flex:0 0 58px;height:58px;background:#FFE129;font-family:Montserrat;font-weight:900;font-size:30px;display:flex;align-items:center;justify-content:center}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.col{border:2px solid #272727;padding:30px}
.col.b{background:#272727;color:#fff}
.col h2{font-family:Montserrat;font-weight:800;text-transform:uppercase;font-size:28px;margin-bottom:20px}
.col.b h2 span{background:#FFE129;color:#272727;padding:2px 10px}
.col li{font-size:24px;line-height:1.35;margin:0 0 14px 28px;font-weight:500}
.chk{display:grid;gap:16px}
.chk div{font-size:28px;line-height:1.35;padding-left:58px;position:relative;font-weight:600}
.chk div:before{content:"✓";position:absolute;left:0;top:-1px;width:40px;height:40px;background:#FFE129;color:#272727;font-weight:900;display:flex;align-items:center;justify-content:center;font-size:24px}
.cover{height:675px;display:flex;flex-direction:column;justify-content:flex-end;padding:72px;background:#272727;color:#fff}
.cover h1{font-size:62px;color:#fff;margin-bottom:28px}
.cover .brand{color:#fff}
.pc{position:relative;overflow:hidden;background-size:cover;background-position:center}
.pc .lines{position:absolute;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:0}
.pc .lines.top{top:9%}
.pc .lines.bottom{bottom:9%}
.pc .mk{font-size:60px;padding:10px 22px 6px;box-shadow:0 6px 24px rgba(0,0,0,.18)}
.pc .mk.n{background:none;color:#fff;box-shadow:none;text-shadow:0 2px 18px rgba(0,0,0,.45)}
.pc .mk:nth-child(odd){transform:rotate(-1.3deg)}
.pc .mk:nth-child(even){transform:rotate(.8deg);margin-top:-4px}
.pc .logo{position:absolute;right:28px;bottom:22px;font-family:Montserrat;font-weight:900;font-size:22px;color:#fff;text-shadow:0 1px 10px rgba(0,0,0,.5)}
"""


def esc(x):
    return html.escape(str(x))


def grade(im):
    """Фирменная обработка фото: чуть теплее, контрастнее и насыщеннее."""
    im = ImageEnhance.Contrast(im).enhance(1.07)
    im = ImageEnhance.Color(im).enhance(1.12)
    r, g, b = im.split()
    r = r.point(lambda v: min(255, int(v * 1.03)))
    b = b.point(lambda v: int(v * 0.97))
    return Image.merge("RGB", (r, g, b))


def photo_data(spec, size):
    w, h = size
    im = ImageOps.exif_transpose(Image.open(ROOT / spec["photo"])).convert("RGB")
    im = ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, float(spec.get("y", 0.5))))
    if spec.get("grade", True):
        im = grade(im)
    tmp = Path("/tmp") / f"_cover_{abs(hash(spec['photo']))}.jpg"
    im.save(tmp, "JPEG", quality=92)
    return b64(tmp, "image/jpeg")


def body(spec):
    t = spec.get("type")
    title = f"<h1>{esc(spec['title'])}</h1>" if spec.get("title") else ""
    kick = f"<div><span class='mk y kick'>{esc(spec['kicker'])}</span></div>" if spec.get("kicker") else ""
    brand = "<span class=brand>FL<b>HAUS</b></span>"
    if t == "photo-cover":
        w, h = (int(x) for x in str(spec.get("size", "1200x675")).split("x"))
        cls = {"white": "w", "yellow": "y", "black": "k", "none": "n"}
        lines = "".join(f"<span class='mk {cls.get(l.get('box', 'white'), 'w')}'>{esc(l['text'])}</span>"
                        for l in spec["lines"])
        return (f"<div class=pc style='width:{w}px;height:{h}px;background-image:url({photo_data(spec, (w, h))})'>"
                f"<div class='lines {spec.get('position', 'top')}'>{lines}</div><div class=logo>FL HAUS</div></div>")
    if t == "cover":
        return f"<div class=cover>{kick}<h1>{esc(spec['title'])}</h1>{brand}</div>"
    if t == "stats":
        items = spec["items"]
        cols = 2 if len(items) == 4 else len(items)
        inner = "".join(f"<div class=stat><div class=v>{esc(i['value'])}</div><div class=l>{esc(i['label'])}</div></div>"
                        for i in items)
        content = f"<div class=stats style='grid-template-columns:repeat({cols},1fr)'>{inner}</div>"
    elif t == "bars":
        mx = max(float(i["value"]) for i in spec["items"]) or 1
        content = "".join(
            f"<div class=bar><div class=t><span>{esc(i['label'])}</span><b>{esc(i.get('text', i['value']))}</b></div>"
            f"<div class=track><div class='fill{' hl' if i.get('highlight') else ''}' style='width:{float(i['value']) / mx * 100:.1f}%'></div></div></div>"
            for i in spec["items"])
    elif t == "steps":
        content = "<div class=steps>" + "".join(f"<div class=step>{esc(s)}</div>" for s in spec["items"]) + "</div>"
    elif t == "compare":
        def col(c, cls):
            return f"<div class='col {cls}'><h2><span>{esc(c['title'])}</span></h2><ul>" + "".join(
                f"<li>{esc(p)}</li>" for p in c["points"]) + "</ul></div>"
        content = f"<div class=cmp>{col(spec['left'], 'a')}{col(spec['right'], 'b')}</div>"
    elif t == "checklist":
        content = "<div class=chk>" + "".join(f"<div>{esc(s)}</div>" for s in spec["items"]) + "</div>"
    else:
        raise SystemExit(f"неизвестный type: {t}")
    src = esc(spec.get("source", ""))
    return f"<div class=card>{kick}{title}{content}<div class=src><span>{('Источник: ' + src) if src else ''}</span>{brand}</div></div>"


def render(spec, out):
    css = font_css() + CSS.replace("__W__", str(W))
    page_html = f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>{body(spec)}</body></html>"
    jpg = str(out).lower().endswith((".jpg", ".jpeg"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": 700}, device_scale_factor=1)
        pg.set_content(page_html)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        pg.query_selector("body > div").screenshot(path=str(out), type="jpeg" if jpg else "png",
                                                  **({"quality": 90} if jpg else {}))
        b.close()


if __name__ == "__main__":
    spec = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    render(spec, Path(sys.argv[2]))
    print("ok", sys.argv[2])
