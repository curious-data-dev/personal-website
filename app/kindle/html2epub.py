"""HTML → EPUB conversion for Kindle delivery.

Adapted from the standalone `html2epub.py` converter (Conversion Folder/),
trimmed to the single code path the digest pipeline needs: take an in-memory
HTML string and write a Kindle-friendly EPUB with one chapter per <h2> heading.

The original script's folder/URL/image handling is intentionally not carried
over — digest HTML is self-contained and contains no images.
"""

import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

# Tags that never belong in an ebook.
STRIP_TAGS = [
    "script", "style", "iframe", "noscript", "form", "button", "input",
    "select", "textarea", "video", "audio", "canvas", "object", "embed",
    "svg", "link", "meta",
]
# Page "chrome" removed when no <article> is found.
CHROME_TAGS = ["aside", "nav", "header", "footer"]

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U00002190-\U000021FF]+")

BASE_CSS = """
body { line-height: 1.45; }
h1, h2, h3 { line-height: 1.25; }
img { max-width: 100%; height: auto; }
pre, code { font-family: monospace; white-space: pre-wrap; }
table { border-collapse: collapse; }
td, th { border: 1px solid #888; padding: 0.2em 0.4em; }
"""


def _pick_content_root(soup: BeautifulSoup):
    """Find the part of the page that is the actual reading content."""
    for tag in STRIP_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    articles = soup.find_all("article")
    if articles:
        return max(articles, key=lambda a: len(a.get_text()))
    main = soup.find("main") or soup.find(attrs={"role": "main"})
    if main:
        for tag in CHROME_TAGS:
            for el in main.find_all(tag):
                el.decompose()
        return main

    body = soup.body or soup
    for tag in CHROME_TAGS:
        for el in body.find_all(tag):
            el.decompose()
    return body


def _clean(root) -> None:
    # Wrapper <div>s add nothing in an ebook and hide headings from splitting.
    for el in root.find_all(["details", "summary", "div"]):
        el.unwrap()
    for el in root.find_all(True):
        for attr in list(el.attrs):
            if attr not in ("href", "src", "alt", "colspan", "rowspan"):
                del el.attrs[attr]
    for a in root.find_all("a"):
        href = a.get("href", "")
        if not href or href.startswith(("javascript:", "#")):
            a.unwrap()
    # Digest HTML should not contain images; drop any that sneak in.
    for img in root.find_all("img"):
        img.decompose()


def _embed_data_images(root, book) -> None:
    """Embed any data: URI images (there normally are none)."""
    seen: dict[str, str] = {}
    for img in root.find_all("img"):
        src = img.get("src", "")
        if not src.startswith("data:"):
            continue
        try:
            header, b64 = src.split(",", 1)
            mime = header[5:].split(";")[0] or "image/png"
            data = base64.b64decode(b64)
        except Exception:
            img.decompose()
            continue
        key = hashlib.md5(data).hexdigest()
        if key not in seen:
            ext = mimetypes.guess_extension(mime) or ".jpg"
            name = f"images/img_{len(seen):03d}{ext}"
            book.add_item(epub.EpubItem(uid=f"img{len(seen)}", file_name=name,
                                        media_type=mime, content=data))
            seen[key] = name
        img["src"] = seen[key]


def _split_chapters(root, level: str | None, title: str):
    """Return [(chapter_title, html), ...]."""
    if not level:
        return [(title, root.decode_contents())]

    container = root
    chapters, ch_title, buf = [], None, []
    for node in list(container.children):
        if getattr(node, "name", None) == level:
            if "".join(buf).strip():
                chapters.append((ch_title or title, "".join(buf)))
            ch_title, buf = node.get_text(" ", strip=True) or title, [str(node)]
        else:
            buf.append(str(node))
    if "".join(buf).strip():
        chapters.append((ch_title or title, "".join(buf)))

    if not chapters:
        return [(title, root.decode_contents())]
    return chapters


def convert_html_to_epub(
    html: str | bytes,
    out_path: str | Path,
    *,
    title: str | None = None,
    author: str = "Media Hub",
    lang: str = "en",
    split: str = "h2",
    strip_emoji: bool = False,
) -> int:
    """Write an EPUB from an HTML string. Returns the number of chapters."""
    out_path = Path(out_path)
    soup = BeautifulSoup(html, "lxml")

    if not title and soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(strip=True)
    html_lang = (soup.html or {}).get("lang") if soup.html else None
    lang = html_lang or lang

    root = _pick_content_root(soup)
    _clean(root)

    if not title:
        h1 = root.find("h1")
        title = h1.get_text(strip=True) if h1 else out_path.stem
    if strip_emoji:
        title = EMOJI_RE.sub("", title).strip()
        for s in root.find_all(string=True):
            s.replace_with(EMOJI_RE.sub("", s))

    book = epub.EpubBook()
    book.set_identifier(
        "digest-" + hashlib.md5(f"{title}".encode("utf-8")).hexdigest()
    )
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

    _embed_data_images(root, book)

    css = epub.EpubItem(uid="style", file_name="style/main.css",
                        media_type="text/css", content=BASE_CSS)
    book.add_item(css)

    parts = _split_chapters(root, None if split == "none" else split, title)

    # Put the book title at the top of the first chapter if it has none.
    if not root.find("h1"):
        first_title, first_html = parts[0]
        parts[0] = (first_title, f"<h1>{title}</h1>\n{first_html}")

    chapters = []
    for i, (ch_title, ch_html) in enumerate(parts, 1):
        ch = epub.EpubHtml(title=ch_title, file_name=f"chap_{i:03d}.xhtml", lang=lang)
        ch.content = ch_html or "<p></p>"
        ch.add_item(css)
        book.add_item(ch)
        chapters.append(ch)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(out_path), book)
    return len(chapters)
