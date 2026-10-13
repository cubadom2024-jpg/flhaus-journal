#!/usr/bin/env python3
"""Обложки и инфографика по дизайн-системе FL Haus (v1.1): YAML-описание → картинка 1200 px.

  python3 tools/infographic.py spec.yaml out.png      (или out.jpg)

Дизайн-система: жёлтый fl-yellow #FFDD29, графит #292929, graphite-deep #1D1D1D, paper #F2F2F2;
шрифт Futura PT → бесплатная замена Jost (static/fonts/Jost.ttf); заголовки ExtraBold;
без курсива, градиентов и третьего яркого цвета; жёлтый текст только на графите;
на жёлтом — только graphite-deep. Фото — только настоящие дома FL Haus.

Типы (поле type):
  cover     — обложка 1200×675: слева графит с заголовком ЗАГЛАВНЫМИ, справа фото дома.
              photo: photos/<файл>.jpg, y: 0.5, title: "СЕМЕЙНАЯ ИПОТЕКА НА [ДОМ — 6%]"
              (часть в [квадратных скобках] — жёлтым, одна на обложку), kicker: "Ипотека"
  facts     — жёлтая панель FactBlock: groups: [{emoji: "⏰", q: "Когда?", rows: [["Дата", "21–23 марта"]]}]
  price     — PriceCard: model, rows: [["Площадь", "43 м²"]], price: "4 950 000 ₽", note: "*Цена до 25.10.2026…"
  stats     — 2–4 крупные цифры на графите: items: [{value, label}]
  bars      — столбцы: items: [{label, value, text, highlight: true}]
  steps     — шаги по порядку: items: ["...", ...]
  compare   — две колонки: left: {title, points}, right: {title, points}
  checklist — список фактов с галочками: items: [...]
Общие поля: kicker (жёлтая метка над заголовком), title, source («Источник: …» — обязательно для цифр).
"""
import base64
import html
import re
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageEnhance, ImageOps
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "static" / "fonts"
LOGO = ROOT / "static" / "img" / "fl-haus-logo-yellow.jpg"
W = 1200


def b64(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def font_css():
    return f"@font-face{{font-family:Jost;src:url({b64(FONTS / 'Jost.ttf', 'font/ttf')});font-weight:100 900}}"


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--y:#FFDD29;--g:#292929;--gd:#1D1D1D;--paper:#F2F2F2;--muted:#5C5C5C;--mod:#B3B3B3;--fg:#474A51}
body{width:__W__px;font-family:"Futura PT",Jost,"Century Gothic",sans-serif;background:var(--paper);color:var(--gd)}
.card{padding:76px 80px 60px;background:var(--paper)}
.kick{display:inline-block;background:var(--y);color:var(--gd);font-weight:700;font-size:26px;line-height:1;padding:12px 20px;border-radius:999px;margin-bottom:26px}
h1{font-weight:800;font-size:54px;line-height:1.1;margin-bottom:44px;max-width:1040px}
.src{margin-top:44px;font-size:24px;line-height:1.4;font-weight:500;color:var(--muted);display:flex;justify-content:space-between;align-items:center;gap:24px}
.logo{height:64px;width:64px;border-radius:12px;flex:0 0 64px}
.stats{display:grid;gap:22px}
.stat{background:var(--g);border-radius:18px;padding:34px 34px 30px}
.stat .v{font-weight:800;font-size:68px;line-height:1;color:var(--y);white-space:nowrap}
.stat .l{font-size:28px;line-height:1.3;color:#fff;margin-top:16px;font-weight:400}
.bar{margin-bottom:26px}
.bar .t{display:flex;justify-content:space-between;align-items:baseline;font-size:30px;font-weight:400;margin-bottom:10px;gap:20px}
.bar .t b{font-weight:800;font-size:34px}
.track{height:34px;background:#E1E1DE;border-radius:17px;overflow:hidden}
.fill{height:100%;background:var(--fg);border-radius:17px}
.fill.hl{background:var(--y)}
.steps{counter-reset:s;display:grid;gap:16px}
.step{display:flex;gap:26px;align-items:center;background:#fff;border-radius:18px;padding:22px 28px;font-size:30px;line-height:1.3}
.step:before{counter-increment:s;content:counter(s);flex:0 0 62px;height:62px;border-radius:50%;background:var(--y);color:var(--gd);font-weight:800;font-size:32px;display:flex;align-items:center;justify-content:center}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.col{border-radius:24px;padding:36px;background:#fff}
.col.b{background:var(--g);color:#fff}
.col h2{font-weight:800;font-size:34px;line-height:1.15;margin-bottom:22px}
.col.b h2{color:var(--y)}
.col li{font-size:28px;line-height:1.35;margin:0 0 14px 30px}
.chk{display:grid;gap:18px}
.chk div{font-size:31px;line-height:1.35;padding-left:62px;position:relative}
.chk div:before{content:"✓";position:absolute;left:0;top:-1px;width:44px;height:44px;border-radius:12px;background:var(--y);color:var(--gd);font-weight:800;display:flex;align-items:center;justify-content:center;font-size:26px}
.facts{background:var(--y);color:var(--gd);border-radius:52px 0 0 0;padding:70px}
.facts .grp+.grp{margin-top:52px}
.facts .q{font-weight:800;font-size:52px;line-height:1.1;margin-bottom:18px}
.facts .row{font-size:36px;line-height:1.45}
.facts .row b{font-weight:700}
.price{background:var(--g);color:#fff;border-radius:52px;padding:70px}
.price .m{font-weight:800;font-size:52px;line-height:1.1}
.price .row{font-size:34px;line-height:1.45;margin-top:10px}
.price .row b{font-weight:700}
.price .v{font-weight:800;font-size:96px;line-height:1;color:var(--y);margin:30px 0 26px;white-space:nowrap}
.price .n{font-size:26px;line-height:1.4;color:var(--mod);font-weight:500}
.cover{position:relative;width:1200px;height:675px;background:var(--g);overflow:hidden}
.cover .ph{position:absolute;right:0;top:0;bottom:0;width:560px;background-size:cover;background-position:center;border-radius:52px 0 0 52px}
.cover .tx{position:absolute;left:72px;top:64px;bottom:64px;width:530px;display:flex;flex-direction:column;justify-content:center}
.cover .kick{align-self:flex-start;margin-bottom:30px}
.cover h1{color:#fff;font-size:64px;line-height:1.02;text-transform:uppercase;margin:0;max-width:none;letter-spacing:.005em}
.cover h1 em{font-style:normal;color:var(--y)}
.cover .lg{position:absolute;left:72px;bottom:56px;height:72px;width:72px;border-radius:14px}
"""


def esc(x):
    return html.escape(str(x))


def grade(im):
    """Фирменная обработка фото по LUT FL_Haus_warm_v1: теплее (R +3,5%, B −6%),
    мягкая S-кривая, чёрная точка 2%, белая 98%, насыщенность −8%."""
    lut = []
    for v in range(256):
        x = v / 255
        x = 0.02 + x * 0.96                       # чёрная 2%, белая 98%
        x = x + 0.06 * (x - 0.5) * (1 - abs(2 * x - 1))  # мягкая S-кривая
        lut.append(max(0, min(255, round(x * 255))))
    im = im.point(lut * 3)
    r, g, b = im.split()
    r = r.point(lambda v: min(255, round(v * 1.035)))
    b = b.point(lambda v: round(v * 0.94))
    im = Image.merge("RGB", (r, g, b))
    return ImageEnhance.Color(im).enhance(0.92)


def photo_data(spec, size):
    w, h = size
    im = ImageOps.exif_transpose(Image.open(ROOT / spec["photo"])).convert("RGB")
    im = ImageOps.fit(im, (w * 2 // 2, h), Image.LANCZOS, centering=(float(spec.get("x", 0.5)), float(spec.get("y", 0.5))))
    if spec.get("grade", True):
        im = grade(im)
    tmp = Path("/tmp") / f"_cover_{abs(hash(spec['photo']))}.jpg"
    im.save(tmp, "JPEG", quality=92)
    return b64(tmp, "image/jpeg")


def accent(s):
    """[часть] → жёлтое слово на обложке."""
    return re.sub(r"\[(.+?)\]", r"<em>\1</em>", esc(s))


def body(spec):
    t = spec.get("type")
    logo = f"<img class=logo src='{b64(LOGO, 'image/jpeg')}'>"
    kick = f"<div><span class=kick>{esc(spec['kicker'])}</span></div>" if spec.get("kicker") else ""
    if t == "cover":
        k = f"<span class=kick>{esc(spec['kicker'])}</span>" if spec.get("kicker") else ""
        return (f"<div class=cover><div class=ph style=\"background-image:url({photo_data(spec, (560, 675))})\"></div>"
                f"<div class=tx>{k}<h1>{accent(spec['title'])}</h1></div>"
                f"<img class=lg src='{b64(LOGO, 'image/jpeg')}'></div>")
    title = f"<h1>{esc(spec['title'])}</h1>" if spec.get("title") else ""
    if t == "stats":
        items = spec["items"]
        cols = 2 if len(items) == 4 else len(items)
        content = f"<div class=stats style='grid-template-columns:repeat({cols},1fr)'>" + "".join(
            f"<div class=stat><div class=v>{esc(i['value'])}</div><div class=l>{esc(i['label'])}</div></div>"
            for i in items) + "</div>"
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
            return f"<div class='col {cls}'><h2>{esc(c['title'])}</h2><ul>" + "".join(
                f"<li>{esc(p)}</li>" for p in c["points"]) + "</ul></div>"
        content = f"<div class=cmp>{col(spec['left'], 'a')}{col(spec['right'], 'b')}</div>"
    elif t == "checklist":
        content = "<div class=chk>" + "".join(f"<div>{esc(s)}</div>" for s in spec["items"]) + "</div>"
    elif t == "facts":
        content = "<div class=facts>" + "".join(
            f"<div class=grp><div class=q>{esc(g.get('emoji', ''))} {esc(g['q'])}</div>" + "".join(
                f"<div class=row><b>{esc(r[0])}:</b> {esc(r[1])}</div>" for r in g["rows"]) + "</div>"
            for g in spec["groups"]) + "</div>"
    elif t == "price":
        content = (f"<div class=price><div class=m>{esc(spec['model'])}</div>"
                   + "".join(f"<div class=row><b>{esc(r[0])}:</b> {esc(r[1])}</div>" for r in spec.get("rows", []))
                   + f"<div class=v>{esc(spec['price'])}</div><div class=n>{esc(spec['note'])}</div></div>")
    else:
        raise SystemExit(f"неизвестный type: {t}")
    src = esc(spec.get("source", ""))
    return f"<div class=card>{kick}{title}{content}<div class=src><span>{('Источник: ' + src) if src else ''}</span>{logo}</div></div>"


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
