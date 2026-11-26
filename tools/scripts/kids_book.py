#!/usr/bin/env python3
"""Детская книжка-сказка → PDF: обложка, развороты (слева текст, справа картинка), последняя страница.

Навык kids-story. Папка книги (в данных дерева) устроена так:
  СКАЗКА_текст.md   — «## Обложка» (1-я строка — название, 2-я — подзаголовок, 3-я — откуда книга, мельче), «## Разворот N. …», «## Последняя
                      страница. …»; абзацы — текст страницы; строки «*Картинка: …*» — что на картинке (в книгу не идут);
                      «## Для взрослых. …» (en «For adults», es «Para adultos») — страницы без картинки в конце
                      книги: справка для взрослых (где места тогда и сейчас); «**Имя** — …» в начале абзаца — жирным;
                      абзац «![подпись](pages/book/схема.png)» — схема на всю ширину («![подпись|50%](…)» — уже, по центру); абзац в «*…*» — мелкая сноска
                      «на чём основано»;
                      всё после «## По каким правилам» / «## Откуда факты» в книгу не идёт.
                      «### Страница 1» / «### Страница 2» внутри разворота — две страницы «полстраницы»: картинка
                      4:3 на всю ширину и короткий текст; на левой картинка сверху, на правой снизу; картинки —
                      sNNa и sNNb. «## Карта. …» — разворот с картинкой map (её рисует kids_map.py); без абзацев —
                      одна страница: текст нарисован в самой карте.
                      Другой язык — свой файл (--text): «## Cover / Spread N / Last page» (английский),
                      «## Portada / Desplegable N / Última página» (испанский), «## Okładka / Rozkładówka N / Ostatnia strona» (польский); картинки те же.
  pages/book/<id>.png|jpg|jpeg — картинки: cover, s01…sNN, last (для другого языка сначала ищется <id>_<язык>, напр. map_pl). Нет картинки — на её месте рамка с описанием,
                      так картинки можно вставлять по одной и пересобирать книгу.
Поля, которые генератор рисует сам (ровная полоса по краю), срезаются; горизонтальная картинка вписывается целиком.

Запуск:  tools/py tools/scripts/kids_book.py <папка книги> [--text STORY_text_en.md] [--out имя.pdf] [--page 1792]
         [--web имя]  — ещё и страница-лента для сайта: каждая страница отдельной картинкой одна под другой, без
                        оформления сайта; кладётся в выгрузку сайта books/<имя>/ (с PDF рядом), список книг — books/.
                        Пароль сайта на /books/ не спрашивается (functions/_middleware.js). Ширину для ленты хватает 1024.
"""
import argparse
import html
import re
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

SERIF = "/System/Library/Fonts/Supplemental/PTSerif.ttc"  # macOS; другой шрифт с кириллицей — --font
PAPER, INK, ACCENT, FRAME = (247, 240, 226), (58, 46, 38), (150, 62, 40), (200, 188, 168)
STOP = ("## По каким правилам", "## Откуда факты", "## How it was written", "## Sources", "## Cómo se escribió",
        "## Fuentes", "## Skąd fakty", "## Jak powstała")
SPREAD = r"(?:Разворот|Spread|Desplegable|Rozkładówka) (\d+)"
COVER = ("Обложка", "Cover", "Portada", "Okładka")
ADULTS = ("Для взрослых", "For adults", "Para adultos", "Dla dorosłych")
MAP = ("Карта", "Map", "Mapa")
PIC = ("*Картинка", "*Picture", "*Imagen", "*Obrazek")
PLACEHOLDER = {"ru": "Здесь будет картинка", "en": "Picture goes here", "es": "Aquí irá la imagen", "pl": "Tu będzie obrazek"}


class Book:
    def __init__(self, folder: Path, page_w: int, font_path: str, text_file: str = "СКАЗКА_текст.md"):
        self.dir, self.font_path, self.text_file = folder, font_path, text_file
        self.lang = "ru"
        self.K = page_w / 768  # все размеры заданы для страницы 768 px и масштабируются
        self.W, self.H, self.M = page_w, round(page_w * 4 / 3) - 1, round(70 * self.K)

    def font(self, size, bold=False, italic=False):
        try:
            return ImageFont.truetype(self.font_path, round(size * self.K), index=3 if bold else 1 if italic else 0)
        except OSError:
            return ImageFont.truetype(self.font_path, round(size * self.K))

    # --- текст -------------------------------------------------------------------------------------------------
    def parse(self):
        text = (self.dir / self.text_file).read_text()
        self.lang = "en" if "\n## Cover" in text else "es" if "\n## Portada" in text else "pl" if "\n## Okładka" in text else "ru"
        for stop in STOP:
            text = text.split(stop)[0]
        out = []
        for block in re.split(r"\n## ", text)[1:]:
            head, *body = block.strip().splitlines()
            m = re.match(SPREAD, head)
            pid = (f"s{int(m.group(1)):02d}" if m else "cover" if head.startswith(COVER)
                   else "adults" if head.startswith(ADULTS) else "map" if head.startswith(MAP) else "last")
            chunks = [[]]  # «### Страница 1/2» делит разворот на две страницы: картинка + текст на каждой
            for ln in body:
                if ln.startswith("### "):
                    chunks.append([])
                else:
                    chunks[-1].append(ln)
            halves = [self.chunk(c) for c in chunks[1:3]] if len(chunks) > 2 else None
            paras, desc = self.chunk(chunks[0]) if not halves else ([], "")
            out.append((pid, head.split(". ", 1)[-1], paras, desc, halves))
        return out

    @staticmethod
    def chunk(lines):
        """Строки одной страницы → (абзацы текста, описание картинки)."""
        paras, buf, desc, in_pic = [], [], [], False
        for ln in lines + [""]:
            s = ln.strip()
            if s.startswith(PIC):
                in_pic = not s.endswith("*") or s in PIC
                desc.append(s.strip("*"))
                continue
            if in_pic:
                in_pic = not s.endswith("*")
                desc.append(s.strip("*"))
                continue
            if s in ("", "---"):
                if buf:
                    paras.append(" ".join(buf))
                    buf = []
                continue
            buf.append(s)
        return paras, " ".join(desc)

    @staticmethod
    def wrap(d, text, f, width):
        lines, line = [], ""
        for word in text.split():
            test = f"{line} {word}".strip()
            if d.textlength(test, font=f) <= width:
                line = test
            else:
                lines.append(line)
                line = word
        return lines + [line] if line else lines

    # --- картинка ----------------------------------------------------------------------------------------------
    @staticmethod
    def trim(im):
        bg = Image.new("RGB", im.size, im.getpixel((2, 2)))
        box = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 28 else 0).getbbox()
        if box and box != (0, 0, im.width, im.height):
            x0, y0, x1, y1 = box
            return im.crop((x0 + 4, y0 + 4, x1 - 4, y1 - 4))
        return im

    def picture(self, pid, desc, size):
        K = self.K
        names = [f"{pid}_{self.lang}", pid] if self.lang != "ru" else [pid]  # map_pl.png — своя карта для языка
        for p in [self.dir / "pages" / "book" / f"{n}.{e}" for n in names for e in ("png", "jpg", "jpeg")]:
            if p.exists():
                im = self.trim(Image.open(p).convert("RGB"))
                if abs(im.width / im.height - size[0] / size[1]) < 0.12:  # та же форма — на всю страницу
                    r = max(size[0] / im.width, size[1] / im.height)
                    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
                    x, y = (im.width - size[0]) // 2, (im.height - size[1]) // 2
                    return im.crop((x, y, x + size[0], y + size[1])), True
                r = min((size[0] - 60 * K) / im.width, (size[1] - 60 * K) / im.height)  # другая форма — целиком
                im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
                page = Image.new("RGB", size, PAPER)
                page.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
                return page, True
        im = Image.new("RGB", size, (236, 228, 212))
        d = ImageDraw.Draw(im)
        d.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=FRAME, width=round(4 * K))
        f = self.font(26, italic=True)
        lines = [PLACEHOLDER[self.lang], f"({pid})", ""] + self.wrap(d, desc.replace("Картинка", "").strip(" :—"), f,
                                                                    size[0] - 120 * K)
        y = (size[1] - round(38 * K) * len(lines)) // 2
        for ln in lines:
            d.text((size[0] // 2, y), ln, font=f, fill=(120, 105, 90), anchor="ma")
            y += round(38 * K)
        return im, False

    # --- страницы ----------------------------------------------------------------------------------------------
    def text_page(self, paras, num):
        K, W, H, M = self.K, self.W, self.H, self.M
        pg = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(pg)
        size = 28
        while True:  # длинный текст — шрифт мельче
            f = self.font(size)
            step, gap = round(size * 1.4 * K), round(18 * K)
            lines = [ln for p in paras for ln in self.wrap(d, p, f, W - 2 * M) + [None]]
            if sum(step if ln else gap for ln in lines) <= H - 2 * M - 40 * K or size <= 20:
                break
            size -= 1
        y = (H - sum(step if ln else gap for ln in lines)) // 2
        for ln in lines:
            if ln:
                d.text((M, y), ln, font=f, fill=INK)
            y += step if ln else gap
        d.text((W // 2, H - round(50 * K)), str(num), font=self.font(22), fill=INK, anchor="mm")
        return pg

    def half_page(self, pid, paras, desc, num, pic_top):
        """Страница «полстраницы»: картинка 4:3 на всю ширину (сверху или снизу) и короткий текст под/над ней."""
        K, W, H, M = self.K, self.W, self.H, self.M
        ph = round(W * 3 / 4)
        pg = Image.new("RGB", (W, H), PAPER)
        pic, ok = self.picture(pid, desc, (W, ph))
        pg.paste(pic, (0, 0 if pic_top else H - ph))
        d = ImageDraw.Draw(pg)
        top, bottom = (ph + round(30 * K), H - round(70 * K)) if pic_top else (round(50 * K), H - ph - round(30 * K))
        size = 27
        while True:  # длинный текст — шрифт мельче
            f = self.font(size)
            step, gap = round(size * 1.38 * K), round(12 * K)
            lines = [ln for p in paras for ln in self.wrap(d, p, f, W - 2 * M) + [None]][:-1]
            if sum(step if ln else gap for ln in lines) <= bottom - top or size <= 18:
                break
            size -= 1
        if size < 25:  # заметно мельче соседних страниц — сократить текст или перенести абзац
            print(f"⚠️ стр. {num} ({pid}): текст длинный, кегль {size} вместо 27")
        y = top + (bottom - top - sum(step if ln else gap for ln in lines)) // 2
        for ln in lines:
            if ln:
                d.text((M, y), ln, font=f, fill=INK)
            y += step if ln else gap
        ny = H - round(40 * K) if pic_top else round(25 * K)  # номер — в свободном от картинки поле
        d.text((W // 2, ny), str(num), font=self.font(20), fill=INK, anchor="mm",
               stroke_width=round(2 * K), stroke_fill=PAPER)
        return pg, ok

    def info_pages(self, title, paras):
        """Справка для взрослых: заголовок, абзацы мелким шрифтом, сколько страниц понадобится.

        Абзац «![подпись](путь)» — картинка (схема) на всю ширину, путь — от папки книги; абзац целиком в «*…*» —
        сноска ещё мельче курсивом: на чём основано сказанное абзацем выше.
        """
        K, W, H, M = self.K, self.W, self.H, self.M
        f, fb, ft = self.font(21), self.font(21, bold=True), self.font(30, bold=True)
        fs = self.font(15, italic=True)
        step, gap, sstep = round(21 * 1.4 * K), round(16 * K), round(15 * 1.35 * K)
        d = ImageDraw.Draw(Image.new("RGB", (W, H)))
        blocks = [[("title", ln) for ln in self.wrap(d, title, ft, W - 2 * M)]]
        for p in paras:
            im = re.match(r"!\[(.*?)\]\((.+?)\)$", p)
            if im:
                path = self.dir / im.group(2)
                if path.exists():
                    pic = self.trim(Image.open(path).convert("RGB"))
                    wm = re.search(r"\|(\d+)%$", im.group(1))  # «![подпись|50%](…)» — уже на всю ширину
                    r = (W - 2 * M) * (int(wm.group(1)) / 100 if wm else 1) / pic.width
                    blocks.append([("image", pic.resize((round(pic.width * r), round(pic.height * r)), Image.LANCZOS))])
                continue
            if p.startswith("*") and p.endswith("*") and not p.startswith("**"):
                blocks.append([("small", ln) for ln in self.wrap(d, p.strip("*"), fs, W - 2 * M)])
                continue
            m = re.match(r"\*\*(.+?)\*\*(.*)", p)
            head, rest = (m.group(1), m.group(2).strip()) if m else ("", p)
            blk = [("bold", ln) for ln in self.wrap(d, head, fb, W - 2 * M)] if head else []
            blk += [("text", ln) for ln in self.wrap(d, rest, f, W - 2 * M)] if rest else []
            blocks.append(blk)

        def hgt(k, ln):
            return (ln.height + round(10 * K) if k == "image" else round(42 * K) if k == "title"
                    else sstep if k == "small" else step)

        bottom = H - M - 40 * K
        pages, cur, y = [], [], M
        for bi, blk in enumerate(blocks):
            if cur:
                y += round(4 * K) if blk and blk[0][0] == "small" else gap  # сноска — вплотную к своему абзацу
            need = sum(hgt(k, ln) for k, ln in blk)
            if y + need > bottom and cur:
                fit = 0  # сколько строк влезает на эту страницу
                yy = y
                for k, ln in blk:
                    if yy + hgt(k, ln) > bottom:
                        break
                    yy += hgt(k, ln)
                    fit += 1
                heads = sum(1 for k, _ in blk if k in ("title", "bold"))
                # абзац не рвём, если на странице остаётся меньше двух строк текста или на новую уходит одна;
                # картинку не рвём никогда
                if fit - heads < 2 or len(blk) - fit < 2 or blk[0][0] == "image":
                    fit = 0
                for k, ln in blk[:fit]:
                    cur.append((k, ln, y))
                    y += hgt(k, ln)
                pages.append(cur)
                cur, y = [], M
                blk = blk[fit:]
            for k, ln in blk:
                cur.append((k, ln, y))
                y += hgt(k, ln)
        pages.append(cur)
        out = []
        for items_ in pages:
            pg = Image.new("RGB", (W, H), PAPER)
            dd = ImageDraw.Draw(pg)
            for kind, ln, y in items_:
                if kind == "image":
                    pg.paste(ln, ((W - ln.width) // 2, y))
                else:
                    dd.text((M, y), ln, font={"title": ft, "bold": fb, "small": fs}.get(kind, f),
                            fill=ACCENT if kind == "title" else (110, 95, 80) if kind == "small" else INK)
            out.append(pg)
        return out

    def cover(self, title, paras, desc):
        K, W, H, M = self.K, self.W, self.H, self.M
        pic, _ = self.picture("cover", desc, (W, H))
        d = ImageDraw.Draw(pic)
        name = paras[0].strip("*") if paras else title
        sub = paras[1].strip("*") if len(paras) > 1 else ""
        size = 58  # длинное название (испанское) — мельче, чтобы не больше двух строк и не на лицах
        while True:
            f = self.font(size, bold=True)
            lines = self.wrap(d, name, f, W - 2 * M)
            if len(lines) <= 2 or size <= 36:
                break
            size -= 2
        y = round(28 * K)
        for ln in lines:
            d.text((W // 2, y), ln, font=f, fill=ACCENT, anchor="ma", stroke_width=round(3 * K), stroke_fill=PAPER)
            y += round(size * 1.2 * K)
        note = paras[2].strip("*") if len(paras) > 2 else ""  # третья строка — откуда книга, мельче
        if sub:
            d.text((W // 2, H - round(130 if note else 90) * K), sub, font=self.font(28, italic=True), fill=INK,
                   anchor="mm", stroke_width=round(2 * K), stroke_fill=PAPER)
        if note:
            y = H - round(88 * K)
            for ln in self.wrap(d, note, self.font(20, italic=True), W - 2 * M):
                d.text((W // 2, y), ln, font=self.font(20, italic=True), fill=INK, anchor="mm",
                       stroke_width=round(2 * K), stroke_fill=PAPER)
                y += round(28 * K)
        return pic

    @staticmethod
    def singles(pages):
        """Развороты → отдельные страницы (левая, правая); одиночные (обложка) — как есть."""
        out = []
        for pg in pages:
            if pg.width > pg.height * 1.1:
                out += [pg.crop((0, 0, pg.width // 2, pg.height)), pg.crop((pg.width // 2, 0, pg.width, pg.height))]
            else:
                out.append(pg)
        return out

    def build(self, out: Path, web: str = "", single: bool = False):
        pages, have, total = [], 0, 0
        for pid, title, paras, desc, halves in self.parse():
            total += 1
            if halves:
                spread = Image.new("RGB", (self.W * 2, self.H), PAPER)
                for j, (hp, hd) in enumerate(halves):
                    pg, ok = self.half_page(f"{pid}{'ab'[j]}", hp, hd, 2 * len(pages) - 1 + j, pic_top=j == 0)
                    have += ok
                    spread.paste(pg, (self.W * j, 0))
                total += len(halves) - 1
                pages.append(spread)
                continue
            if pid == "cover":
                pages.append(self.cover(title, paras, desc))
                have += any((self.dir / "pages" / "book" / f"cover.{e}").exists() for e in ("png", "jpg", "jpeg"))
                continue
            if pid == "adults":
                info = self.info_pages(title, paras)
                for i in range(0, len(info), 2):
                    spread = Image.new("RGB", (self.W * 2, self.H), PAPER)
                    for j, pg in enumerate(info[i:i + 2]):
                        spread.paste(pg, (self.W * j, 0))
                    pages.append(spread)
                total -= 1
                continue
            if pid == "map" and not paras:  # карта без абзацев: текст нарисован в самой карте — одна страница
                pic, ok = self.picture(pid, desc, (self.W, self.H))
                have += ok
                pages.append(pic)
                continue
            spread = Image.new("RGB", (self.W * 2, self.H), PAPER)
            spread.paste(self.text_page(paras, 1 + 2 * (len(pages) - 1)), (0, 0))
            pic, ok = self.picture(pid, desc, (self.W, self.H))
            have += ok
            spread.paste(pic, (self.W, 0))
            pages.append(spread)
        pdf_pages = self.singles(pages) if single else pages
        pdf_pages[0].save(out, save_all=True, append_images=pdf_pages[1:], resolution=300, quality=92)
        print(f"{out} — страниц/разворотов: {len(pages)}, картинок есть: {have} из {total}")
        if web:
            self.web(pages, out, web)

    def web(self, pages, pdf: Path, slug: str):
        """Лента для телефона: разворот режется на две страницы, страницы — картинками одна под другой."""
        import paths  # noqa: PLC0415 — нужен только для ленты
        books = paths.SITE_EXPORT / "books"
        d = books / slug
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        singles = self.singles(pages)
        imgs = []
        for i, pg in enumerate(singles, 1):
            name = f"{i:02d}.jpg"
            pg.convert("RGB").save(d / name, quality=82, optimize=True)
            imgs.append(f'<img src="{name}" width="{pg.width}" height="{pg.height}" loading="{"eager" if i < 3 else "lazy"}" alt="">')
        shutil.copyfile(pdf, d / "book.pdf")
        title = next((p[0].strip("*") for pid, _, p, _, _ in self.parse() if pid == "cover" and p), slug)
        (d / "title.txt").write_text(title, encoding="utf-8")
        (d / "lang.txt").write_text(self.lang, encoding="utf-8")
        (d / "book.txt").write_text(self.dir.name, encoding="utf-8")  # одна книга на разных языках — рядом в списке
        pdf_word = {"ru": "Скачать PDF", "pl": "Pobierz PDF", "es": "Descargar PDF", "en": "Download PDF"}[self.lang]
        (d / "index.html").write_text(PAGE.format(lang=self.lang, title=html.escape(title), body="\n".join(imgs),
                                                  foot=f'<a href="book.pdf">{pdf_word}</a>'), encoding="utf-8")
        def row(x):
            lang = (x / "lang.txt").read_text(encoding="utf-8") if (x / "lang.txt").exists() else "ru"
            name = html.escape((x / "title.txt").read_text(encoding="utf-8"))
            return (f'<li><a href="{x.name}/">{name}</a> <span class="lang">{LANG_NAME.get(lang, lang)}</span>'
                    f' · <a href="{x.name}/book.pdf">PDF</a></li>')
        def order(x):
            book = (x / "book.txt").read_text(encoding="utf-8") if (x / "book.txt").exists() else x.name
            return book, (x / "lang.txt").exists() and (x / "lang.txt").read_text(encoding="utf-8") != "ru", x.name
        links = [row(x) for x in sorted(books.iterdir(), key=order) if (x / "title.txt").exists()]
        (books / "index.html").write_text(PAGE.format(lang="ru", title="Книжки", body="<ul>" + "".join(links) + "</ul>",
                                                      foot=""), encoding="utf-8")
        print(f"лента: {d} — страниц {len(singles)}; на сайте /books/{slug}/ после выкладки (rodo site all)")


LANG_NAME = {"ru": "русский", "pl": "polski", "es": "español", "en": "English"}  # в списке книг — язык своим словом
PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>
body{{margin:0;background:#f7f0e2;color:#3a2e26;font:18px/1.5 Georgia,serif}}
main{{max-width:900px;margin:0 auto}}
img{{display:block;width:100%;height:auto;margin:0 0 6px}}
ul{{padding:24px 16px 0 36px}} li{{margin:0 0 12px}}
a{{color:#963e28}} .lang{{color:#7a6a5c;font-size:15px}} footer{{text-align:center;padding:24px 16px 40px}}
</style></head>
<body><main>
{body}
<footer>{foot}</footer>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="папка книги (там СКАЗКА_текст.md и pages/book/)")
    ap.add_argument("--text", default="СКАЗКА_текст.md", help="файл текста в папке книги (другой язык — свой файл)")
    ap.add_argument("--out", help="имя PDF в pages/ (по умолчанию — книга.pdf)", default="книга.pdf")
    ap.add_argument("--page", type=int, default=1792, help="ширина страницы в точках (1792 — полный размер Gemini)")
    ap.add_argument("--font", default=SERIF, help="шрифт с засечками и кириллицей (.ttc/.ttf)")
    ap.add_argument("--single", action="store_true", help="PDF по одной странице, а не разворотами (для телефона)")
    ap.add_argument("--web", default="", help="имя ленты на сайте: books/<имя>/ в выгрузке сайта (латиницей)")
    a = ap.parse_args()
    folder = a.folder.resolve()
    (folder / "pages" / "book").mkdir(parents=True, exist_ok=True)
    if a.web and not re.fullmatch(r"[a-z0-9-]+", a.web):
        ap.error("--web: только латиница, цифры и дефис")
    Book(folder, a.page, a.font, a.text).build(folder / "pages" / a.out, a.web, a.single)


if __name__ == "__main__":
    main()
