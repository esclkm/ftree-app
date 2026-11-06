#!/usr/bin/env python3
"""Детская книжка-сказка → PDF: обложка, развороты (слева текст, справа картинка), последняя страница.

Навык kids-story. Папка книги (в данных дерева) устроена так:
  СКАЗКА_текст.md   — «## Обложка» (1-я строка — название, 2-я — подзаголовок), «## Разворот N. …», «## Последняя
                      страница. …»; абзацы — текст страницы; строки «*Картинка: …*» — что на картинке (в книгу не идут);
                      всё после «## По каким правилам» / «## Откуда факты» в книгу не идёт.
  pages/book/<id>.png|jpg|jpeg — картинки: cover, s01…sNN, last. Нет картинки — на её месте рамка с описанием,
                      так картинки можно вставлять по одной и пересобирать книгу.
Поля, которые генератор рисует сам (ровная полоса по краю), срезаются; горизонтальная картинка вписывается целиком.

Запуск:  tools/py tools/scripts/kids_book.py <папка книги> [--out имя.pdf] [--page 1792]
"""
import argparse
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

SERIF = "/System/Library/Fonts/Supplemental/PTSerif.ttc"  # macOS; другой шрифт с кириллицей — --font
PAPER, INK, ACCENT, FRAME = (247, 240, 226), (58, 46, 38), (150, 62, 40), (200, 188, 168)
STOP = ("## По каким правилам", "## Откуда факты")


class Book:
    def __init__(self, folder: Path, page_w: int, font_path: str):
        self.dir, self.font_path = folder, font_path
        self.K = page_w / 768  # все размеры заданы для страницы 768 px и масштабируются
        self.W, self.H, self.M = page_w, round(page_w * 4 / 3) - 1, round(70 * self.K)

    def font(self, size, bold=False, italic=False):
        try:
            return ImageFont.truetype(self.font_path, round(size * self.K), index=3 if bold else 1 if italic else 0)
        except OSError:
            return ImageFont.truetype(self.font_path, round(size * self.K))

    # --- текст -------------------------------------------------------------------------------------------------
    def parse(self):
        text = (self.dir / "СКАЗКА_текст.md").read_text()
        for stop in STOP:
            text = text.split(stop)[0]
        out = []
        for block in re.split(r"\n## ", text)[1:]:
            head, *body = block.strip().splitlines()
            m = re.match(r"Разворот (\d+)", head)
            pid = f"s{int(m.group(1)):02d}" if m else "cover" if head.startswith("Обложка") else "last"
            paras, buf, desc, in_pic = [], [], [], False
            for ln in body + [""]:
                s = ln.strip()
                if s.startswith("*Картинка"):
                    in_pic = not s.endswith("*") or s == "*Картинка"
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
            out.append((pid, head.split(". ", 1)[-1], paras, " ".join(desc)))
        return out

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
        for ext in ("png", "jpg", "jpeg"):
            p = self.dir / "pages" / "book" / f"{pid}.{ext}"
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
        lines = ["Здесь будет картинка", f"({pid})", ""] + self.wrap(d, desc.replace("Картинка", "").strip(" :—"), f,
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

    def cover(self, title, paras, desc):
        K, W, H, M = self.K, self.W, self.H, self.M
        pic, _ = self.picture("cover", desc, (W, H))
        d = ImageDraw.Draw(pic)
        name = paras[0].strip("*") if paras else title
        sub = paras[1].strip("*") if len(paras) > 1 else ""
        f = self.font(58, bold=True)
        y = round(90 * K)
        for ln in self.wrap(d, name, f, W - 2 * M):
            d.text((W // 2, y), ln, font=f, fill=ACCENT, anchor="ma", stroke_width=round(3 * K), stroke_fill=PAPER)
            y += round(70 * K)
        if sub:
            d.text((W // 2, H - round(90 * K)), sub, font=self.font(28, italic=True), fill=INK, anchor="mm",
                   stroke_width=round(2 * K), stroke_fill=PAPER)
        return pic

    def build(self, out: Path):
        pages, have, total = [], 0, 0
        for pid, title, paras, desc in self.parse():
            total += 1
            if pid == "cover":
                pages.append(self.cover(title, paras, desc))
                have += any((self.dir / "pages" / "book" / f"cover.{e}").exists() for e in ("png", "jpg", "jpeg"))
                continue
            spread = Image.new("RGB", (self.W * 2, self.H), PAPER)
            spread.paste(self.text_page(paras, 1 + 2 * (len(pages) - 1)), (0, 0))
            pic, ok = self.picture(pid, desc, (self.W, self.H))
            have += ok
            spread.paste(pic, (self.W, 0))
            ImageDraw.Draw(spread).line([(self.W, 0), (self.W, self.H)], fill=FRAME, width=round(2 * self.K))
            pages.append(spread)
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=300, quality=92)
        print(f"{out} — страниц/разворотов: {len(pages)}, картинок есть: {have} из {total}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="папка книги (там СКАЗКА_текст.md и pages/book/)")
    ap.add_argument("--out", help="имя PDF в pages/ (по умолчанию — книга.pdf)", default="книга.pdf")
    ap.add_argument("--page", type=int, default=1792, help="ширина страницы в точках (1792 — полный размер Gemini)")
    ap.add_argument("--font", default=SERIF, help="шрифт с засечками и кириллицей (.ttc/.ttf)")
    a = ap.parse_args()
    folder = a.folder.resolve()
    (folder / "pages" / "book").mkdir(parents=True, exist_ok=True)
    Book(folder, a.page, a.font).build(folder / "pages" / a.out)


if __name__ == "__main__":
    main()
