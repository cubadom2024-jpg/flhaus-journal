#!/usr/bin/env python3
"""Сборка блога FL Haus и RSS-ленты для Дзена.

articles/<папка>/index.md  →  docs/ (сайт для GitHub Pages) + docs/rss.xml (лента для Дзена)

Запуск:  python3 build.py            — собрать
         python3 build.py --check    — только проверить статьи, ничего не писать
"""
import datetime as dt
import html
import re
import shutil
import sys
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from string import Template

import markdown
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent
ART = ROOT / "articles"
OUT = ROOT / "docs"
TPL = ROOT / "templates"
STATIC = ROOT / "static"

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
BASE = CFG["site_url"].rstrip("/")
MIN_IMG_W = 700

# Теги, которые Дзен принимает в content:encoded
FEED_ALLOWED = {
    "p", "a", "b", "i", "u", "s", "h1", "h2", "h3", "h4", "blockquote",
    "ul", "ol", "li", "figure", "figcaption", "img", "video", "source", "iframe", "br",
}
FEED_ATTRS = {"a": {"href"}, "img": {"src"}, "h2": {"id"}, "h3": {"id"}, "h4": {"id"},
              "source": {"src", "type"}, "video": {"poster"}, "iframe": {"src", "width", "height"}}
RENAME = {"strong": "b", "em": "i", "del": "s"}

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
                     "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slugify(text):
    s = "".join(TRANSLIT.get(c, c) for c in text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].rstrip("-")


class Sanitizer(HTMLParser):
    """Оставляет только разрешённые Дзеном теги и атрибуты."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []

    def handle_starttag(self, tag, attrs):
        tag = RENAME.get(tag, tag)
        if tag not in FEED_ALLOWED:
            return
        keep = FEED_ATTRS.get(tag, set())
        a = "".join(f' {k}="{html.escape(v or "", quote=True)}"' for k, v in attrs if k in keep)
        self.out.append(f"<{tag}{a}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = RENAME.get(tag, tag)
        if tag in FEED_ALLOWED and tag not in ("img", "br", "source"):
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def sanitize(h):
    p = Sanitizer()
    p.feed(h)
    p.close()
    return "".join(p.out)


def parse_article(folder):
    raw = (folder / "index.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError("нет блока --- с параметрами в начале файла")
    meta = yaml.safe_load(m.group(1)) or {}
    meta["body_md"] = m.group(2).strip()
    meta["folder"] = folder
    meta.setdefault("slug", slugify(meta.get("title", folder.name)))
    meta.setdefault("status", "ready")
    d = meta.get("date")
    if isinstance(d, str):
        d = dt.datetime.fromisoformat(d)
    if isinstance(d, dt.date) and not isinstance(d, dt.datetime):
        d = dt.datetime.combine(d, dt.time(10, 0))
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=3)))
    meta["date"] = d
    return meta


def render_body(a):
    """Markdown → HTML. Одиночная картинка в абзаце становится <figure> с подписью."""
    h = markdown.markdown(a["body_md"], extensions=["sane_lists", "attr_list"], output_format="html")
    url = f"{BASE}/blog/{a['slug']}/"

    def fig(m):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        src = attrs.get("src", "")
        cap = attrs.get("alt", "")
        absrc = src if src.startswith("http") else url + src
        a.setdefault("_images", []).append(src)
        c = f"<figcaption>{cap}</figcaption>" if cap else ""
        return f'<figure><img src="{absrc}" alt="{cap}" loading="lazy">{c}</figure>'

    h = re.sub(r"<p>\s*<img ([^>]*?)/?>\s*</p>", fig, h)
    n = 0

    def hid(m):
        nonlocal n
        n += 1
        return f'<{m.group(1)} id="part-{n}">'

    h = re.sub(r"<(h[234])>", hid, h)
    return h


def plain_len(h):
    return len(re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip())


def validate(a, body_html):
    errs, warns = [], []
    t = a.get("title", "")
    if not t:
        errs.append("нет title")
    if len(t) > 200:
        errs.append(f"title длиннее 200 знаков ({len(t)})")
    elif len(t) > 80:
        warns.append(f"title длиннее рекомендуемых 80 знаков ({len(t)})")
    if t.endswith("."):
        errs.append("title заканчивается точкой")
    if t and t.upper() == t and re.search("[А-ЯA-Z]", t):
        errs.append("title написан капслоком")
    if not a.get("description"):
        errs.append("нет description")
    if not a.get("date"):
        errs.append("нет date")
    if not a.get("cover"):
        errs.append("нет cover")
    n = plain_len(body_html)
    if n < 3000:
        warns.append(f"текст короткий: {n} знаков (для статьи Дзена лучше 4000+)")
    if "<table" in body_html:
        errs.append("таблицы Дзен не поддерживает — переделайте в список или инфографику")
    for src in a.get("_images", []) + ([a["cover"]] if a.get("cover") else []):
        if src.startswith("http"):
            continue
        p = a["folder"] / src
        if not p.exists():
            errs.append(f"нет файла картинки {src}")
            continue
        try:
            with Image.open(p) as im:
                if im.width < MIN_IMG_W:
                    errs.append(f"{src}: ширина {im.width}px < {MIN_IMG_W}px")
                if im.format not in ("JPEG", "PNG", "GIF"):
                    errs.append(f"{src}: формат {im.format}, нужен JPEG/PNG/GIF")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{src}: не открывается ({e})")
    return errs, warns


def tpl(name):
    return Template((TPL / name).read_text(encoding="utf-8"))


def ru_date(d):
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def main():
    check_only = "--check" in sys.argv
    articles, problems = [], 0
    for folder in sorted(p for p in ART.iterdir() if p.is_dir() and (p / "index.md").exists()):
        try:
            a = parse_article(folder)
        except Exception as e:  # noqa: BLE001
            print(f"✗ {folder.name}: {e}")
            problems += 1
            continue
        if a["status"] == "hold":
            print(f"· {folder.name}: status=hold, пропущена")
            continue
        a["body_html"] = render_body(a)
        errs, warns = validate(a, a["body_html"])
        for w in warns:
            print(f"! {folder.name}: {w}")
        if errs:
            problems += 1
            for e in errs:
                print(f"✗ {folder.name}: {e}")
            continue
        articles.append(a)

    slugs = [a["slug"] for a in articles]
    dup = {s for s in slugs if slugs.count(s) > 1}
    if dup:
        print(f"✗ повторяющиеся slug: {', '.join(dup)}")
        problems += 1

    print(f"Статей готово: {len(articles)}, с ошибками: {problems}")
    if problems:
        sys.exit(1)
    if check_only:
        return

    articles.sort(key=lambda a: a["date"], reverse=True)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "blog").mkdir(parents=True)
    if STATIC.exists():
        shutil.copytree(STATIC, OUT / "static")

    page_t, index_t, card_t = tpl("article.html"), tpl("index.html"), tpl("card.html")
    cta = CFG.get("site_cta", {})
    common = dict(site_title=html.escape(CFG["site_title"]), site_url=BASE,
                  main_site_url=CFG["main_site_url"], year=dt.date.today().year,
                  dzen_url=CFG.get("dzen_channel_url") or CFG["main_site_url"])

    cards = []
    for a in articles:
        d = OUT / "blog" / a["slug"]
        d.mkdir(parents=True)
        for f in a["folder"].iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                shutil.copy2(f, d / f.name)
        url = f"{BASE}/blog/{a['slug']}/"
        cover = a["cover"] if a["cover"].startswith("http") else url + a["cover"]
        a["url"], a["cover_url"] = url, cover
        (d / "index.html").write_text(page_t.substitute(
            common, title=html.escape(a["title"]), description=html.escape(a["description"]),
            url=url, cover=cover, date_iso=a["date"].isoformat(), date_ru=ru_date(a["date"]),
            rubric=html.escape(a.get("rubric", "Статьи")), body=a["body_html"],
            cta_title=html.escape(cta.get("title", "")), cta_text=html.escape(cta.get("text", "")),
            cta_button=html.escape(cta.get("button", "")),
        ), encoding="utf-8")
        cards.append(card_t.substitute(url=url, cover=cover, title=html.escape(a["title"]),
                                       description=html.escape(a["description"]),
                                       date_ru=ru_date(a["date"]),
                                       rubric=html.escape(a.get("rubric", "Статьи"))))

    (OUT / "index.html").write_text(index_t.substitute(
        common, site_description=html.escape(CFG["site_description"]), cards="\n".join(cards)),
        encoding="utf-8")

    # RSS для Дзена
    cats_common = ["format-article", "index", CFG.get("dzen_comments", "comment-all")]
    if CFG.get("dzen_mode") == "draft":
        cats_common.insert(0, "native-draft")
    items = []
    for a in articles[: CFG.get("feed_items", 30)]:
        feed_html = sanitize(a["body_html"])
        cats = "".join(f"<category>{c}</category>" for c in cats_common)
        items.append(f"""    <item>
      <title>{html.escape(a['title'])}</title>
      <link>{a['url']}</link>
      <guid isPermaLink="true">{a['url']}</guid>
      <pubDate>{format_datetime(a['date'])}</pubDate>
      <description>{html.escape(a['description'])}</description>
      <media:rating scheme="urn:simple">nonadult</media:rating>
      {cats}
      <enclosure url="{cover_enc(a)}" type="{mime(a['cover_url'])}"/>
      <content:encoded><![CDATA[{feed_html}]]></content:encoded>
    </item>""")
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:georss="http://www.georss.org/georss">
  <channel>
    <title>{html.escape(CFG['site_title'])}</title>
    <link>{BASE}/</link>
    <description>{html.escape(CFG['site_description'])}</description>
    <language>{CFG.get('language', 'ru')}</language>
    <atom:link href="{BASE}/rss.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (OUT / "rss.xml").write_text(rss, encoding="utf-8")

    sm = "\n".join(f"  <url><loc>{a['url']}</loc><lastmod>{a['date'].date().isoformat()}</lastmod></url>"
                   for a in articles)
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{BASE}/</loc></url>\n{sm}\n</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    host = re.sub(r"^https?://", "", BASE)
    if not host.endswith("example.ru") and not host.endswith("github.io"):
        (OUT / "CNAME").write_text(host + "\n", encoding="utf-8")
    for extra in ROOT.glob("verify/*"):  # файлы подтверждения прав (Дзен, Вебмастер)
        shutil.copy2(extra, OUT / extra.name)
    print(f"Собрано: {len(articles)} статей → docs/, лента: {BASE}/rss.xml ({min(len(articles), CFG.get('feed_items', 30))} шт.)")


def cover_enc(a):
    return a["cover_url"]


def mime(u):
    u = u.lower()
    return "image/png" if u.endswith(".png") else "image/gif" if u.endswith(".gif") else "image/jpeg"


if __name__ == "__main__":
    main()
