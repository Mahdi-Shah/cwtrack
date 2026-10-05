#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a Persian deliverable (Markdown or HTML) to PDF with headless Chromium.

Zero third-party dependencies. Verified on Windows with Chrome + Edge + Python 3.14.

    python render.py draft.md                        -> draft.pdf  (+ draft.html kept)
    python render.py draft.md -o "گزارش نهایی.pdf"
    python render.py draft.md --title "..." --subtitle "..." --footer "..."
    python render.py draft.md --html-only            # preview only, no browser needed
    python render.py draft.md --digits latin         # keep ASCII digits

Markdown support is the subset this skill emits: ATX headings, paragraphs, fenced
code, blockquotes, pipe tables, nested bullet/ordered lists, hr, and inline
emphasis / code / links / images / $math$. If the `markdown` package happens to be
installed it is used instead, and that widens the accepted syntax.

Exit codes: 0 ok, 1 usage or environment error, 2 render failure.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# bundled font
# --------------------------------------------------------------------------

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_WEIGHTS = {"Regular": 400, "Medium": 500, "Bold": 700}
_font_cache: dict[int, str] | None = None


def font_face_css() -> str:
    """Embed the bundled Vazirmatn faces as data URIs.

    Persian text rendered in a fallback face (Tahoma, Segoe UI) is the weakest
    link in this pipeline: those fonts were not designed for Arabic script and
    the kerning and baseline sit wrong. Embedding removes the dependency on what
    the student happens to have installed, and costs ~330 KB of base64.
    """
    global _font_cache
    if _font_cache is not None:
        return _font_cache
    rules: list[str] = []
    if FONT_DIR.is_dir():
        for name, weight in FONT_WEIGHTS.items():
            path = FONT_DIR / "Vazirmatn-{}.ttf".format(name)
            if not path.is_file():
                continue
            blob = base64.b64encode(path.read_bytes()).decode("ascii")
            rules.append(
                "@font-face{{font-family:'Vazirmatn';font-style:normal;"
                "font-weight:{};font-display:block;src:url(data:font/ttf;base64,{}) "
                "format('truetype');}}".format(weight, blob)
            )
    _font_cache = "\n".join(rules)
    return _font_cache

# --------------------------------------------------------------------------
# digits
# --------------------------------------------------------------------------

_ASCII_DIGITS = "0123456789"
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_TABLE = str.maketrans(_ASCII_DIGITS, _FA_DIGITS)

# A number that is not glued to a word character. \w is unicode-aware, so a digit
# touching a Persian letter is left alone too; that keeps mixed text readable.
# '@' is excluded so npm@10.2.1 and user@host style tokens stay untouched.
_FA_NUM_RE = re.compile(r"(?<![\w.@])[0-9]+(?:[.,/][0-9]+)*%?(?!\w)")


def _to_fa_numbers(text: str) -> str:
    """Convert standalone ASCII numbers to Persian digits.

    Deliberately skips ``COVID-19`` / ``ISO-8601`` / ``GPT-4`` / ``3.14.7``: an
    identifier whose digits hang off a Latin word, or a dotted version, stays
    Latin, because half-Persianising a product name reads worse than leaving it.
    """

    def repl(m: re.Match) -> str:
        body = m.group(0)
        if body.count(".") >= 2:  # semver / dotted version
            return body
        i = m.start()
        if i >= 2 and text[i - 1] == "-" and text[i - 2].isascii() and text[i - 2].isalpha():
            return body
        out = body.translate(_DIGIT_TABLE)
        if out.endswith("%"):
            out = out[:-1] + "٪"
        return out

    return _FA_NUM_RE.sub(repl, text)


# --------------------------------------------------------------------------
# inline markdown
# --------------------------------------------------------------------------

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

_FA_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_FA_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_FA_MATH_RE = re.compile(r"(\$\$.+?\$\$|\\\(.+?\\\)|(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$))", re.S)
_FA_STRONG_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_FA_EM_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_FA_UNDERLINE_EM_RE = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_FA_DEL_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fa_inline(text: str, digits: str = "fa") -> str:
    """Render inline markdown to HTML.

    Code spans, math, links and images are lifted into placeholders before any
    other rule runs, so emphasis, escaping and digit conversion never reach
    inside a URL, an equation or a code literal.
    """
    stash: list[str] = []

    def keep(html: str) -> str:
        stash.append(html)
        return _PLACEHOLDER.format(len(stash) - 1)

    def on_code(m: re.Match) -> str:
        body = m.group(0)
        ticks = body[: len(body) - len(body.lstrip("`"))]
        inner = body.strip("`")
        if inner.startswith(" ") and inner.endswith(" "):
            inner = inner[1:-1]
        return keep("<code>{}</code>".format(_escape(inner)))

    def on_math(m: re.Match) -> str:
        # Strip the delimiters and keep the body isolated left-to-right. There is no
        # TeX engine here, so the source is printed verbatim; writing it Unicode-first
        # (see references/persian-output.md) is what keeps it readable in the PDF.
        body = m.group(0)
        for open_d, close_d in (("$$", "$$"), ("\\(", "\\)"), ("$", "$")):
            if body.startswith(open_d) and body.endswith(close_d) and len(body) > len(open_d) + len(close_d) - 1:
                body = body[len(open_d) : len(body) - len(close_d)]
                break
        return keep('<span class="math">{}</span>'.format(_escape(body.strip())))

    def on_image(m: re.Match) -> str:
        return keep(
            '<img src="{}" alt="{}">'.format(_escape(m.group(2)), _escape(m.group(1)))
        )

    def on_link(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        body = _fa_inline(label, digits) if label else href
        return keep('<a href="{}">{}</a>'.format(_escape(href), body))

    text = re.sub(r"(`+)(?:(?!\1).)*?\1", on_code, text, flags=re.S)
    text = _FA_MATH_RE.sub(on_math, text)
    text = _FA_IMAGE_RE.sub(on_image, text)
    text = _FA_LINK_RE.sub(on_link, text)

    text = _escape(text)
    if digits == "fa":
        text = _to_fa_numbers(text)

    text = _FA_STRONG_RE.sub(r"<strong>\1</strong>", text)
    text = _FA_EM_RE.sub(r"<em>\1</em>", text)
    text = _FA_UNDERLINE_EM_RE.sub(r"<em>\1</em>", text)
    text = _FA_DEL_RE.sub(r"<del>\1</del>", text)

    text = re.sub(r"(?<![\w*])__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", text, flags=re.S)

    def restore(m: re.Match) -> str:
        return stash[int(m.group(1))]

    return _PLACEHOLDER_RE.sub(restore, text)


# --------------------------------------------------------------------------
# block markdown
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([^\s`]*)\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, buf, esc = [], [], False
    for ch in line:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\":
            buf.append(ch)
            esc = True
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _render_blocks(lines: list[str], digits: str) -> str:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            marker, lang = fence.group(1), fence.group(2)
            close = re.compile(r"^\s*{}\s*$".format(re.escape(marker[0] * len(marker))))
            body, i = [], i + 1
            while i < n and not close.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            cls = ' class="lang-{}"'.format(_escape(lang)) if lang else ""
            out.append(
                "<pre><code{}>{}\n</code></pre>".format(cls, _escape("\n".join(body)))
            )
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            out.append("<h{0}>{1}</h{0}>".format(level, _fa_inline(heading.group(2), digits)))
            i += 1
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if _QUOTE_RE.match(line):
            body = []
            while i < n and (_QUOTE_RE.match(lines[i]) or (body and lines[i].strip())):
                m = _QUOTE_RE.match(lines[i])
                body.append(m.group(1) if m else lines[i].strip())
                i += 1
            out.append("<blockquote>{}</blockquote>".format(_render_blocks(body, digits)))
            continue

        if line.strip().startswith("|") and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            aligns = []
            for cell in _split_row(lines[i + 1]):
                left, right = cell.startswith(":"), cell.endswith(":")
                aligns.append("center" if left and right else "left" if left else "right" if right else "")
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            head_html = "".join(
                '<th style="text-align:{}">{}</th>'.format(a or "right", _fa_inline(c, digits))
                for c, a in zip(header, aligns + [""] * len(header))
            )
            body_html = "".join(
                "<tr>{}</tr>".format(
                    "".join(
                        '<td style="text-align:{}">{}</td>'.format(
                            (aligns[j] if j < len(aligns) else "") or "right",
                            _fa_inline(row[j] if j < len(row) else "", digits),
                        )
                        for j in range(len(header))
                    )
                )
                for row in rows
            )
            out.append(
                "<table><thead><tr>{}</tr></thead><tbody>{}</tbody></table>".format(
                    head_html, body_html
                )
            )
            continue

        if _LIST_ITEM_RE.match(line):
            html, i = _render_list(lines, i, digits)
            out.append(html)
            continue

        body = []
        while i < n and lines[i].strip():
            if body and (
                _HEADING_RE.match(lines[i])
                or _HR_RE.match(lines[i])
                or _FENCE_RE.match(lines[i])
                or _LIST_ITEM_RE.match(lines[i])
                or _QUOTE_RE.match(lines[i])
            ):
                break
            body.append(lines[i].strip())
            i += 1
        if body:
            out.append("<p>{}</p>".format(_fa_inline(" ".join(body), digits)))
    return "\n".join(out)


def _collect_item(lines: list[str], i: int, marker_indent: int) -> tuple[list[str], int]:
    first = _LIST_ITEM_RE.match(lines[i]).group(3)
    content = [first]
    i += 1
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _indent_of(lines[j]) > marker_indent:
                content.append("")
                i += 1
                continue
            break
        ind = _indent_of(line)
        is_item = bool(_LIST_ITEM_RE.match(line))
        if ind > marker_indent or (is_item and ind == marker_indent):
            if is_item and ind == marker_indent:
                break
            content.append(line[marker_indent + 1 :] if len(line) > marker_indent + 1 else line.lstrip())
            i += 1
            continue
        break
    return content, i


def _render_list(lines: list[str], i: int, digits: str) -> tuple[str, int]:
    marker_indent = len(_LIST_ITEM_RE.match(lines[i]).group(1))
    tag = "ol" if _LIST_ITEM_RE.match(lines[i]).group(2)[0].isdigit() else "ul"
    out = ["<{}>".format(tag)]
    while i < len(lines):
        m = _LIST_ITEM_RE.match(lines[i])
        if not m or len(m.group(1)) < marker_indent:
            break
        content, i = _collect_item(lines, i, marker_indent)
        out.append("<li>{}</li>".format(_render_blocks(content, digits)))
    out.append("</{}>".format(tag))
    return "\n".join(out), i


def markdown_to_html(md: str, digits: str = "fa") -> str:
    try:
        import markdown  # type: ignore

        text = markdown.markdown(
            md,
            extensions=["extra", "sane_lists", "tables", "fenced_code"],
            output_format="html5",
        )
        if digits == "fa":
            return text
        return text
    except ImportError:
        pass
    normalised = md.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return _render_blocks(normalised.split("\n"), digits)


# --------------------------------------------------------------------------
# HTML shell
# --------------------------------------------------------------------------

CSS = """
:root { --ink:#1a1a1a; --muted:#6b6b6b; --rule:#d8d4cc; --accent:#1f4e79; --tint:#f6f4ef; }
@page { size: A4; margin: 20mm 18mm 18mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  direction: rtl; text-align: right; color: var(--ink);
  font-family: "Vazirmatn", "IRANSans", "IRANYekan", "Sahel", "Segoe UI", Tahoma, sans-serif;
  font-size: 11.5pt; line-height: 2.0; margin: 0; hyphens: none;
}
h1,h2,h3,h4,h5,h6 { line-height: 1.6; font-weight: 700; margin: 1.5em 0 .6em; break-after: avoid; }
h1 { font-size: 1.7em; }
h2 { font-size: 1.35em; color: var(--accent); border-bottom: 1px solid var(--rule); padding-bottom: .25em; }
h3 { font-size: 1.15em; }
h4, h5, h6 { font-size: 1em; }
h1:first-child, h2:first-child { margin-top: 0; }
p { margin: 0 0 .85em; text-align: justify; }
a { color: var(--accent); }
hr { border: 0; border-top: 1px solid var(--rule); margin: 1.6em 0; }
blockquote {
  margin: 1em 0; padding: .5em 1em; border-right: 3px solid var(--accent);
  background: var(--tint); color: #333; border-radius: 3px;
}
blockquote p:last-child { margin-bottom: 0; }
code {
  font-family: Consolas, "Cascadia Mono", monospace; font-size: .9em;
  direction: ltr; unicode-bidi: embed; background: var(--tint);
  padding: .1em .3em; border-radius: 3px;
}
pre {
  direction: ltr; text-align: left; background: var(--tint); border: 1px solid var(--rule);
  border-radius: 4px; padding: .8em 1em; overflow: hidden; white-space: pre-wrap;
  word-break: break-word; font-size: 9.5pt; line-height: 1.55;
}
pre code { background: none; padding: 0; }
.math { direction: ltr; unicode-bidi: isolate; font-family: "Cambria Math", "Times New Roman", serif; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: .95em; break-inside: avoid; }
th, td { border: 1px solid var(--rule); padding: .45em .6em; vertical-align: top; }
th { background: var(--tint); font-weight: 700; }
tbody tr:nth-child(even) { background: #fbfaf7; }
img { max-width: 100%; break-inside: avoid; }
ul, ol { margin: 0 0 .9em; padding-right: 1.6em; }
li { margin-bottom: .3em; }
li > p:last-child { margin-bottom: 0; }
li > ul, li > ol { margin-top: .3em; margin-bottom: .3em; }
.doc-head { border-bottom: 2px solid var(--accent); margin-bottom: 1.4em; padding-bottom: .7em; }
.doc-head .t { font-size: 1.5em; font-weight: 700; color: var(--accent); margin: 0 0 .2em; }
.doc-head .s { font-size: 1em; color: var(--muted); margin: 0; }
.doc-foot { margin-top: 2em; padding-top: .5em; border-top: 1px solid var(--rule); color: var(--muted); font-size: .85em; }
"""


def build_html(body: str, title: str, subtitle: str, footer: str, embed_font: bool = True) -> str:
    head = []
    if title:
        head.append('<p class="t">{}</p>'.format(_escape(title)))
    if subtitle:
        head.append('<p class="s">{}</p>'.format(_escape(subtitle)))
    header = '<div class="doc-head">{}</div>'.format("".join(head)) if head else ""
    foot = '<div class="doc-foot">{}</div>'.format(_escape(footer)) if footer else ""
    safe_title = _escape(title or "assignment")
    css = (font_face_css() + "\n" + CSS) if embed_font else CSS
    return (
        "<!doctype html>\n"
        '<html lang="fa" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>{}</title>\n<style>{}</style>\n</head>\n<body>\n{}\n{}\n{}\n</body>\n</html>\n"
    ).format(safe_title, css, header, body, foot)


# --------------------------------------------------------------------------
# browser
# --------------------------------------------------------------------------

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> str | None:
    for path in BROWSERS:
        if os.path.isfile(path):
            return path
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def print_pdf(browser: str, html_path: Path, pdf_path: Path) -> None:
    url = html_path.resolve().as_uri()
    base = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=20000",
        "--font-render-hinting=none",
        "--print-to-pdf={}".format(str(pdf_path.resolve())),
        url,
    ]
    attempts = [base, [base[0], "--headless"] + base[2:]]
    last = ""
    for cmd in attempts:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            last = "timed out after 180s"
            continue
        last = (proc.stderr or proc.stdout or "").strip()[-500:]
        if pdf_path.exists() and pdf_path.stat().st_size > 1024:
            return
        if pdf_path.exists():
            pdf_path.unlink()
    raise RuntimeError(
        "headless print failed{}\ncommand: {}\n{}".format(
            "\nbrowser stderr: " + last if last else "", " ".join(base[:2] + ["..."]), browser
        )
    )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render.py",
        description="Render a Persian Markdown/HTML deliverable to PDF via headless Chromium.",
    )
    ap.add_argument("source", help="input .md or .html file")
    ap.add_argument("-o", "--out", help="output PDF path (default: source stem + .pdf)")
    ap.add_argument("--html", dest="html_out", help="also write the intermediate HTML here")
    ap.add_argument("--title", default="", help="document title shown in the header block")
    ap.add_argument("--subtitle", default="", help="line under the title")
    ap.add_argument("--footer", default="", help="footer note, e.g. a date or course name")
    ap.add_argument("--page", default="A4", help="A4 | Letter (default A4)")
    ap.add_argument("--margin", default="20mm", help="page margin, CSS length (default 20mm)")
    ap.add_argument(
        "--digits",
        choices=["fa", "latin"],
        default="fa",
        help="convert standalone numbers to Persian digits (default fa)",
    )
    ap.add_argument("--html-only", action="store_true", help="stop after writing the HTML")
    ap.add_argument(
        "--font",
        choices=["embed", "system"],
        default="embed",
        help="embed the bundled Vazirmatn faces (default) or use installed system fonts",
    )
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.is_file():
        print("error: no such file: {}".format(src), file=sys.stderr)
        return 1
    if src.suffix.lower() not in (".md", ".markdown", ".html", ".htm"):
        print("error: expected a .md or .html source, got {}".format(src.suffix), file=sys.stderr)
        return 1

    raw = src.read_text(encoding="utf-8")

    if src.suffix.lower() in (".html", ".htm"):
        body = raw
    else:
        body = markdown_to_html(raw, args.digits)

    page_size = args.page.strip().upper()
    if page_size not in ("A4", "LETTER", "LEGAL"):
        page_size = "A4"
    extra_css = "\n@page {{ size: {}; margin: {} {} {}; }}\n".format(
        page_size, args.margin, args.margin, args.margin
    )
    html = build_html(
        body, args.title, args.subtitle, args.footer, embed_font=(args.font == "embed")
    ).replace("</style>", extra_css + "</style>")

    workdir = Path(args.html_out).parent if args.html_out else src.parent
    workdir.mkdir(parents=True, exist_ok=True)
    html_path = Path(args.html_out) if args.html_out else src.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print("html  -> {}".format(html_path))

    if args.html_only:
        return 0

    pdf_path = Path(args.out) if args.out else src.with_suffix(".pdf")
    if pdf_path.suffix.lower() != ".pdf":
        pdf_path = pdf_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    browser = find_browser()
    if not browser:
        print(
            "error: no Chromium browser found. Install Chrome or Edge, or pass\n"
            "       --html-only and print the generated HTML by hand.",
            file=sys.stderr,
        )
        return 1
    print("browser -> {}".format(browser))

    try:
        print_pdf(browser, html_path, pdf_path)
    except RuntimeError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2

    size = pdf_path.stat().st_size
    if size <= 1024:
        print("error: pdf looks empty ({} bytes)".format(size), file=sys.stderr)
        return 2
    print("pdf   -> {}  ({:.1f} KB)".format(pdf_path, size / 1024))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - top level guard for CLI use
        print("error: {}".format(exc), file=sys.stderr)
        sys.exit(1)
