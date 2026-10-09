#!/usr/bin/env python3
"""Подготовка фото из библиотеки photos/ для статьи: кадрирование и сжатие.

  python3 tools/photo.py photos/facade-01.jpg articles/<папка>/cover.jpg          # 1200x675 (16:9)
  python3 tools/photo.py photos/interior-03.jpg articles/<папка>/img2.jpg --keep  # без кадрирования, ширина 1200
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
keep = "--keep" in sys.argv
im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
if keep:
    if im.width > 1200:
        im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
else:
    im = ImageOps.fit(im, (1200, 675), Image.LANCZOS, centering=(0.5, 0.5))
if im.width < 700:
    raise SystemExit(f"фото слишком маленькое: {im.width}px, Дзену нужно от 700")
dst.parent.mkdir(parents=True, exist_ok=True)
im.save(dst, "JPEG", quality=85, optimize=True, progressive=True)
print("ok", dst, im.size)
