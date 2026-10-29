#!/usr/bin/env python3
"""Скачивает сгенерированные картинки в папку эпизода и приводит к PNG.

    python3 fetch_images.py multiki/<id> 01=https://...jpeg 02=https://...jpeg
    python3 fetch_images.py multiki/<id> --json urls.json   # {"01": "https://...", ...}

Файл сохраняется как img/<ключ>.png — так, как на него ссылается episode.json.
Ключ с суффиксом _cut (например cat_angel_cut) дополнительно делает светлый
однотонный фон прозрачным — для стикеров типа image.
"""
import json
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image


def knock_out_background(im, tol=28):
    """Заливка от углов: фон, похожий на угловой пиксель, становится прозрачным."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    bg = px[0, 0][:3]
    seen = set()
    stack = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        seen.add((x, y))
        r, g, b, _ = px[x, y]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > tol:
            continue
        px[x, y] = (r, g, b, 0)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return im


def main():
    ep = Path(sys.argv[1])
    pairs = {}
    if len(sys.argv) > 2 and sys.argv[2] == "--json":
        pairs = json.loads(Path(sys.argv[3]).read_text())
    else:
        for a in sys.argv[2:]:
            k, url = a.split("=", 1)
            pairs[k] = url
    out = ep / "img"
    out.mkdir(parents=True, exist_ok=True)
    for key, url in pairs.items():
        with urllib.request.urlopen(url, timeout=60) as r:
            im = Image.open(BytesIO(r.read()))
        name = key
        if key.endswith("_cut"):
            im = knock_out_background(im)
            name = key[:-4]
        else:
            im = im.convert("RGB")
        p = out / f"{name}.png"
        im.save(p)
        print(f"{p}  {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
