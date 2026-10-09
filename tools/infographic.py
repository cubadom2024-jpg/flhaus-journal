#!/usr/bin/env python3
"""Инфографика и обложки для статей: JSON/YAML-описание → PNG 1200 px.

  python3 tools/infographic.py spec.yaml out.png

Типы (поле type):
  stats    — 2–4 крупные цифры:  items: [{value: "5–14 дней", label: "монтаж на участке"}, ...]
  bars     — горизонтальные столбцы: items: [{label: "...", value: 6.0, text: "6%"}], unit: "%"
  steps    — шаги по порядку:   items: ["Выбрать участок", "Подать заявку в банк", ...]
  compare  — две колонки:       left: {title, points: [...]}, right: {title, points: [...]}
  checklist — список с галочками: items: [...]
  cover    — обложка без фото:  title: "...", kicker: "..."
Общие поля: title (заголовок карточки), source (строка «Источник: ...», обязательно для цифр).
"""
import html
import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

W = 1200
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:__W__px;font-family:Inter,system-ui,sans-serif;background:#faf8f4;color:#1e2320}
.card{padding:64px 72px 56px}
.kick{font-size:22px;font-weight:700;color:#a8744a;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px}
h1{font-size:46px;line-height:1.15;letter-spacing:-.02em;font-weight:800;margin-bottom:40px;max-width:1000px}
.src{margin-top:40px;font-size:18px;color:#7b817c;border-top:1px solid #e6e1d8;padding-top:16px;display:flex;justify-content:space-between}
.brand{font-weight:800;color:#1e2320}
.stats{display:grid;gap:24px}
.stat{background:#fff;border:1px solid #e6e1d8;border-radius:18px;padding:32px}
.stat .v{font-size:56px;font-weight:800;letter-spacing:-.02em;color:#7d5333;line-height:1.05}
.stat .l{font-size:24px;color:#4a504c;margin-top:12px;line-height:1.35}
.bar{margin-bottom:26px}
.bar .t{display:flex;justify-content:space-between;font-size:26px;margin-bottom:10px}
.bar .t b{font-weight:800}
.track{height:30px;background:#ece6dc;border-radius:15px;overflow:hidden}
.fill{height:100%;background:#a8744a;border-radius:15px}
.fill.hl{background:#1e2320}
.steps{counter-reset:s;display:grid;gap:18px}
.step{display:flex;gap:24px;align-items:center;background:#fff;border:1px solid #e6e1d8;border-radius:18px;padding:22px 28px;font-size:27px;line-height:1.3}
.step:before{counter-increment:s;content:counter(s);flex:0 0 56px;height:56px;border-radius:50%;background:#1e2320;color:#fff;font-weight:800;font-size:26px;display:flex;align-items:center;justify-content:center}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.col{background:#fff;border:1px solid #e6e1d8;border-radius:18px;padding:32px}
.col.b{background:#1e2320;color:#f4efe7;border-color:#1e2320}
.col h2{font-size:30px;margin-bottom:18px}
.col li{font-size:24px;line-height:1.35;margin:0 0 14px 28px}
.chk{display:grid;gap:14px}
.chk div{font-size:27px;line-height:1.35;padding-left:52px;position:relative}
.chk div:before{content:"✓";position:absolute;left:0;top:-2px;width:36px;height:36px;border-radius:9px;background:#a8744a;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:22px}
.cover{height:675px;display:flex;flex-direction:column;justify-content:flex-end;padding:72px;
  background:linear-gradient(135deg,#1e2320 0%,#3a3129 100%);color:#f4efe7}
.cover .kick{color:#d9a878}
.cover h1{font-size:64px;margin-bottom:28px}
.cover .brand{color:#f4efe7;font-size:26px}
""".replace("__W__", str(W))


def esc(x):
    return html.escape(str(x))


def body(spec):
    t = spec.get("type")
    title = f"<h1>{esc(spec['title'])}</h1>" if spec.get("title") else ""
    kick = f"<div class=kick>{esc(spec['kicker'])}</div>" if spec.get("kicker") else ""
    if t == "cover":
        return f"<div class=cover>{kick}<h1>{esc(spec['title'])}</h1><div class=brand>FL Haus</div></div>"
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
            return f"<div class='col {cls}'><h2>{esc(c['title'])}</h2><ul>" + "".join(
                f"<li>{esc(p)}</li>" for p in c["points"]) + "</ul></div>"
        content = f"<div class=cmp>{col(spec['left'], 'a')}{col(spec['right'], 'b')}</div>"
    elif t == "checklist":
        content = "<div class=chk>" + "".join(f"<div>{esc(s)}</div>" for s in spec["items"]) + "</div>"
    else:
        raise SystemExit(f"неизвестный type: {t}")
    src = esc(spec.get("source", ""))
    return f"<div class=card>{kick}{title}{content}<div class=src><span>{('Источник: ' + src) if src else ''}</span><span class=brand>FL Haus</span></div></div>"


def render(spec, out):
    page_html = f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{body(spec)}</body></html>"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": 600}, device_scale_factor=1)
        pg.set_content(page_html)
        pg.wait_for_timeout(200)
        el = pg.query_selector("body > div")
        el.screenshot(path=str(out), type="jpeg" if str(out).lower().endswith((".jpg", ".jpeg")) else "png",
                      **({"quality": 90} if str(out).lower().endswith((".jpg", ".jpeg")) else {}))
        b.close()


if __name__ == "__main__":
    spec = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    render(spec, Path(sys.argv[2]))
    print("ok", sys.argv[2])
