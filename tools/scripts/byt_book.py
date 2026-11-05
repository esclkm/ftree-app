#!/usr/bin/env python3
"""Книжка о быте предков: .md → HTML (картинки base64) → PDF через headless Chrome.

Запуск: tools/py tools/scripts/byt_book.py <книга.md> <выход.pdf> "<Заголовок>"
Источники книг — 4_outputs/<папка выдачи>/быт_предков/*.md; PDF не коммитим (собираем по просьбе).

Синтаксис картинки (одна строка):  @img файл.jpg | подпись | источник
Файл ищется по имени в 1_sources/found/photos_places и уменьшается до 1100 px.
Две строки @img подряд — встают парой. Блок «> » — заметка. «::toc» — оглавление.
"""
import base64, html, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import PHOTOS_PLACES

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP = tempfile.mkdtemp(prefix="byt_book_")
_INDEX = {}


def find_image(name):
    if not _INDEX:
        for p in PHOTOS_PLACES.rglob("*.jpg"):
            _INDEX.setdefault(p.name, p)
    p = _INDEX.get(name)
    if p is None:
        sys.exit("нет картинки в photos_places: " + name)
    small = os.path.join(TMP, name)
    if not os.path.exists(small):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", "1100",
                        str(p), "--out", small], check=True, capture_output=True)
        trim_black(small)
    return small


def trim_black(path, dark=40):
    """Срезать чёрные поля скана по краям (у вырезок из книг бывают)."""
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    def row_dark(y): return sum(px[x, y] for x in range(0, w, 4)) / len(range(0, w, 4)) < dark
    def col_dark(x): return sum(px[x, y] for y in range(0, h, 4)) / len(range(0, h, 4)) < dark
    top, bottom, left, right = 0, h, 0, w
    while top < bottom - 1 and row_dark(top): top += 1
    while bottom - 1 > top and row_dark(bottom - 1): bottom -= 1
    while left < right - 1 and col_dark(left): left += 1
    while right - 1 > left and col_dark(right - 1): right -= 1
    if (top, bottom, left, right) != (0, h, 0, w):
        Image.open(path).crop((left, top, right, bottom)).save(path, quality=80)

CSS = """
@page { size: A4; margin: 17mm 16mm 17mm 16mm; }
body { font-family: 'PT Serif', Georgia, serif; font-size: 11.5pt; line-height: 1.55; color: #222; }
h1 { font-size: 26pt; margin: 18mm 0 6pt; line-height: 1.15; }
.cover-sub { color: #555; font-size: 12.5pt; margin-bottom: 20pt; }
h2 { font-size: 17pt; margin: 0 0 8pt; border-bottom: 1.5px solid #b08850; padding-bottom: 3pt; break-before: page; break-after: avoid; }
h3 { font-size: 13pt; margin: 14pt 0 4pt; color: #6b4a1e; break-after: avoid; }
p { margin: 0 0 7pt; text-align: justify; hyphens: auto; }
ul { margin: 0 0 8pt; padding-left: 17pt; } li { margin-bottom: 3pt; }
blockquote { background: #f6f0e4; border-left: 3px solid #b08850; padding: 7pt 10pt; margin: 8pt 0 10pt; font-size: 10.5pt; }
blockquote p { margin: 0 0 4pt; text-align: left; }
figure { margin: 8pt 0 12pt; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 95mm; border-radius: 3px; }
.pair { display: flex; gap: 8pt; break-inside: avoid; }
.pair figure { flex: 1; margin: 6pt 0 10pt; }
.pair figure img { max-height: 64mm; }
figcaption { font-size: 9.5pt; color: #444; margin-top: 3pt; text-align: left; }
.src { display: block; color: #888; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; margin: 6pt 0 10pt; }
tr { break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 4pt 5pt; vertical-align: top; text-align: left; }
th { background: #f1e8d6; }
.toc { list-style: none; padding-left: 0; columns: 2; column-gap: 14pt; font-size: 10.5pt; } .toc li { margin-bottom: 2pt; break-inside: avoid; }
"""

def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<i>\1</i>", s)
    return s

def figure(line):
    parts = [p.strip() for p in line[4:].split("|")]
    name, cap, src = (parts + ["", ""])[:3]
    p = find_image(name)
    d = base64.b64encode(open(p, "rb").read()).decode()
    return (f'<figure><img src="data:image/jpeg;base64,{d}"><figcaption>{inline(cap)}'
            f'<span class="src">{inline(src)}</span></figcaption></figure>')

def convert(md):
    lines = md.split("\n"); out = []; i = 0; toc = []
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("@img "):
            if i + 1 < len(lines) and lines[i + 1].startswith("@img "):
                out.append('<div class="pair">' + figure(ln) + figure(lines[i + 1]) + "</div>"); i += 2
            else:
                out.append(figure(ln)); i += 1
            continue
        if ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.startswith("## "):
            toc.append(ln[3:]); out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("### "):
            out.append(f"<h3>{inline(ln[4:])}</h3>")
        elif ln.startswith("::sub "):
            out.append(f'<div class="cover-sub">{inline(ln[6:])}</div>')
        elif ln.strip() == "::toc":
            out.append("@@TOC@@")
        elif ln.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip()); i += 1
            paras = "\n".join(buf).split("\n\n")
            out.append("<blockquote>" + "".join(f"<p>{inline(p)}</p>" for p in paras) + "</blockquote>"); continue
        elif ln.startswith("- "):
            buf = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  ")):
                if lines[i].startswith("- "): buf.append(lines[i][2:])
                else: buf[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in buf) + "</ul>"); continue
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s\-:|]+\|$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            h = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(f"<table><tr>{h}</tr>{b}</table>"); continue
        elif ln.strip():
            buf = [ln]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|- |> |\||@img|::)", lines[i + 1]):
                i += 1; buf.append(lines[i])
            out.append(f"<p>{inline(' '.join(buf))}</p>")
        i += 1
    body = "\n".join(out)
    toc_html = '<h3>Что в книге</h3><ul class="toc">' + "".join(f"<li>{inline(t)}</li>" for t in toc) + "</ul>"
    return body.replace("@@TOC@@", toc_html)

if __name__ == "__main__":
    src, pdf, title = sys.argv[1], sys.argv[2], sys.argv[3]
    body = convert(open(src, encoding="utf-8").read())
    page = os.path.join(TMP, "book.html")
    open(page, "w", encoding="utf-8").write(
        f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f"<style>{CSS}</style></head><body>{body}</body></html>")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={os.path.abspath(pdf)}", "file://" + page], capture_output=True)
    if not os.path.exists(pdf):
        sys.exit("PDF не записан — Chrome не отработал")
    print("PDF:", pdf)
