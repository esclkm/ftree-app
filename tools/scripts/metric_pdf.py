#!/usr/bin/env python3
"""PDF для сверки с родными: записи из метрик крупно, что прочитано и кем человек нам приходится (навык metric-search).

Зачем. Маме и бабушке проще посмотреть на распечатку или PDF в телефоне, чем на страницу проверки. Каждая запись —
две страницы А4: что написано простыми словами, кто это для семьи, вопрос к ним; скан — весь кусок и две половины
с увеличением, чёрно-белый, с поднятой контрастностью (выцветшие чернила темнее).

    tools/py tools/scripts/metric_pdf.py <список.json> <выход.pdf>

Список — JSON: title, subtitle, intro (абзацы), tree (одна строка-схема), levels (шкала), items [{key
«дело:разворот:высота», years, title, read, family, level (доказано|вероятно|возможно|маловероятно|не родня), why,
check}]. Родные не вспоминают, а решают по картинке: «check» — что именно сверить, «why» — на чём держится уровень. Тексты пишет сессия сама, по точному чтению и дереву, — не автоподсказка: она
путает людей. Список и PDF — с именами, в git не идут (PDF и так не храним).
"""
import base64
import html
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metric_filter as mf  # noqa: E402
import metric_review as mr  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LEVELS = {"доказано": "✅", "вероятно": "🟢", "возможно": "🟡", "маловероятно": "🟠", "не родня": "⚪"}
ABOVE, BELOW = 140, 320   # пикселей скана выше и ниже найденного слова: оно обычно в начале записи, а запись ≈250 px


def strip(c: dict):
    """Кусок скана записи: колонки с людьми, чёрно-белый, контраст и резкость."""
    import etalon
    import form_template as ft
    from PIL import Image, ImageFilter, ImageOps
    img = Image.open(etalon.scan(ft.book_by_id(c["book"]), c["n"]))
    w, h = img.size
    x0, x1 = mr.columns_x(c["book"], c["n"], w)
    part = img.crop((x0, max(0, int(c["y0"] - ABOVE)), x1, min(h, int(c["y1"] + BELOW)))).convert("L")
    part = ImageOps.autocontrast(part, cutoff=1)
    return part.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))


def halves(img):
    """Две половины с нахлёстом 10 %, чтобы слово на стыке было целиком хотя бы в одной; увеличены вдвое."""
    from PIL import Image
    w, h = img.size
    cut = int(w * 0.55)
    return [p.resize((p.width * 2, p.height * 2), Image.LANCZOS)
            for p in (img.crop((0, 0, cut, h)), img.crop((w - cut, 0, w, h)))]


def data_uri(img) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CSS = """@page{size:A4 portrait;margin:12mm 12mm 12mm 12mm}body{font:13pt/1.4 Georgia,serif;color:#111}
h1{font-size:24pt;margin:0 0 4mm}h2{font-size:17pt;margin:0 0 2mm}.sub{font-size:14pt;color:#444;margin-bottom:8mm}
.page{page-break-after:always}.meta{color:#555;font-size:11pt;margin-bottom:3mm}.box{border-left:4px solid #888;
padding:1mm 0 1mm 4mm;margin:2mm 0 3mm}.fam{border-color:#2a7a3a;background:#f2f8f2}.ask{border-color:#b06000;
background:#fff6ea;font-size:14.5pt}img{max-width:100%;display:block;margin:1mm 0 3mm;border:1px solid #999}
img.all{max-height:55mm}img.left{max-height:105mm}img.right{max-height:160mm}
.lbl{font-size:10.5pt;color:#555;margin-top:2mm}.lvl{border-color:#555;background:#f6f6f6}
.tree{font-size:11.5pt;background:#f4f4f4;padding:3mm;margin-top:4mm}"""


def build(spec: dict) -> str:
    allc = {}
    for f in mf.TEXT.glob("*/metric_candidates.json"):
        for c in json.loads(f.read_text(encoding="utf-8"))["candidates"]:
            allc[mr.key(c)] = c
    pages = [f'<div class="page"><h1>{html.escape(spec["title"])}</h1><div class="sub">{html.escape(spec["subtitle"])}'
             f'</div>' + "".join(f"<p>{html.escape(p)}</p>" for p in spec["intro"])
             + f'<div class="tree"><b>Кто есть кто:</b> {html.escape(spec["tree"])}</div>'
             + (f'<div class="tree">{html.escape(spec["levels"])}</div>' if spec.get("levels") else "")
             + f'<p class="lbl">Записей в этой подборке: {len(spec["items"])}. На каждую — две страницы.</p></div>']
    for i, it in enumerate(spec["items"], 1):
        if re.match(r"\d+\. ", it["title"]):            # номер уже в заголовке (подборка продолжает прошлую)
            i, it = it["title"].split(". ", 1)[0], {**it, "title": it["title"].split(". ", 1)[1]}
        c = allc[it["key"]]
        img = strip(c)
        left, right = halves(img)
        where = f'Книга {c["book"].replace("ф48_оп6_д", "№")} ({it["years"]}), разворот {c["n"]}'
        pages.append(
            f'<div class="page"><h2>{i}. {html.escape(it["title"])}</h2><div class="meta">{where}</div>'
            f'<div class="box"><b>Что написано (проверьте по картинке):</b> {html.escape(it["read"])}</div>'
            f'<div class="box fam"><b>Кто это для нас:</b> {html.escape(it["family"])}</div>'
            f'<div class="lbl">Вся запись:</div><img class="all" src="{data_uri(img)}">'
            f'<div class="lbl">Левая половина крупно:</div><img class="left" src="{data_uri(left)}"></div>'
            f'<div class="page"><h2>{i}. {html.escape(it["title"])} — продолжение</h2>'
            f'<div class="lbl">Правая половина крупно:</div><img class="right" src="{data_uri(right)}">'
            f'<div class="box lvl"><b>Наш ли это человек: {LEVELS[it["level"]]} {it["level"]}.</b> '
            f'{html.escape(it["why"])}</div>'
            f'<div class="box ask"><b>Сверить по картинке — согласны или нет:</b> {html.escape(it["check"])}</div></div>')
    return f'<!doctype html><meta charset="utf-8"><title>{html.escape(spec["title"])}</title><style>{CSS}</style>' \
           + "".join(pages)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2]).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(build(spec), encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", page.as_uri()], check=True, capture_output=True, timeout=300)
    print(f"{out} — {out.stat().st_size // 1024} КБ, записей {len(spec['items'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
