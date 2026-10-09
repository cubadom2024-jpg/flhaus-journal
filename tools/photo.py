#!/usr/bin/env python3
"""Подготовка фото из библиотеки photos/ для статьи: кадрирование и сжатие.

  python3 tools/photo.py photos/facade-01.jpg articles/<папка>/cover.jpg          # 1200x675 (16:9)
  python3 tools/photo.py photos/interior-03.jpg articles/<папка>/img2.jpg --keep  # без кадрирования, ширина 1200
  --raw     — без фирменной цветокоррекции
  --y 0.4   — где центр кадра по вертикали при кадрировании (0 — верх, 1 — низ), см. cover_y в photos/catalog.yaml
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from infographic import grade  # noqa: E402  фирменная обработка

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
keep = "--keep" in sys.argv
y = float(sys.argv[sys.argv.index("--y") + 1]) if "--y" in sys.argv else 0.5
im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
if keep:
    if im.width > 1200:
        im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
else:
    im = ImageOps.fit(im, (1200, 675), Image.LANCZOS, centering=(0.5, y))
if "--raw" not in sys.argv:
    im = grade(im)
if im.width < 700:
    raise SystemExit(f"фото слишком маленькое: {im.width}px, Дзену нужно от 700")
dst.parent.mkdir(parents=True, exist_ok=True)
im.save(dst, "JPEG", quality=85, optimize=True, progressive=True)
print("ok", dst, im.size)
