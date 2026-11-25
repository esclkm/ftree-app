#!/usr/bin/env python3
"""Карта для детской книжки (навык kids-story): места героя по настоящим координатам, мягкие акварельные тона.

Модели-картинки коверкают буквы, поэтому карту рисует скрипт: бумага, лес пятнами с ёлочками, реки не рисуются,
точки мест с подписями, пунктир — дорога семьи. Результат — pages/book/map.png (вертикальная страница 3:4),
его ставит в книгу kids_book.py (раздел «## Карта. …»).

Запуск:
  tools/py tools/scripts/kids_map.py <папка книги> \\
      --place "Ивановка:50.10,30.20" --place "Город:50.40,30.50:big" ... \\
      --forest "Бор:50.20,30.30,0.15" --route "Ивановка>Хутор>Город" [--route "…"] [--region "Соседняя страна:50.60,29.80"]
  «:big» — крупная точка и подпись (главные места). Подпись — справа от точки; «:left», «:below», «:above», «:belowright» — иначе.
  --route можно повторять: каждая дорога — своим пунктиром со стрелкой.
"""
import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SERIF = "/System/Library/Fonts/Supplemental/PTSerif.ttc"
PAPER, INK, ACCENT = (247, 240, 226), (58, 46, 38), (150, 62, 40)
GREEN, GREEN2, SAND = (150, 170, 120), (110, 140, 95), (232, 220, 196)


def parse_place(s):
    name, rest = s.split(":", 1)
    lat, lon, *flags = rest.replace(":", ",").split(",")
    return name, float(lat), float(lon), set(flags)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--place", action="append", default=[], help="Имя:широта,долгота[:big][:left]")
    ap.add_argument("--forest", action="append", default=[], help="Имя:широта,долгота,радиус_в_градусах")
    ap.add_argument("--region", action="append", default=[], help="подпись страны/края курсивом: Имя:широта,долгота")
    ap.add_argument("--route", action="append", default=[], help="дорога пунктиром: Место>Место>… (можно несколько)")
    ap.add_argument("--page", type=int, default=1792)
    ap.add_argument("--font", default=SERIF)
    a = ap.parse_args()

    W = a.page
    H = round(W * 4 / 3) - 1
    K = W / 768
    places = [parse_place(p) for p in a.place]
    forests = []
    for f in a.forest:
        name, rest = f.split(":", 1)
        lat, lon, r = map(float, rest.split(","))
        forests.append((name, lat, lon, r))
    regions = [(r.split(":")[0], *map(float, r.split(":")[1].split(","))) for r in a.region]

    lats = [p[1] for p in places] + [f[1] for f in forests]
    lons = [p[2] for p in places] + [f[2] for f in forests]
    lat0 = sum(lats) / len(lats)
    kx = math.cos(math.radians(lat0))
    x0, x1 = min(lons) * kx, max(lons) * kx
    y0, y1 = min(lats), max(lats)
    mx_, my_ = 190 * K, 130 * K  # поля под подписи
    s = min((W - 2 * mx_) / (x1 - x0), (H - 2 * my_) / (y1 - y0))
    ox = (W - (x1 - x0) * s) / 2
    oy = (H - (y1 - y0) * s) / 2

    def xy(lat, lon):
        return ox + (lon * kx - x0) * s, H - (oy + (lat - y0) * s)

    def font(size, italic=False, bold=False):
        try:
            return ImageFont.truetype(a.font, round(size * K), index=3 if bold else 1 if italic else 0)
        except OSError:
            return ImageFont.truetype(a.font, round(size * K))

    rnd = random.Random(7)
    img = Image.new("RGB", (W, H), PAPER)
    wash = Image.new("RGB", (W, H), PAPER)  # акварельные пятна: песок по всей карте и лес
    dw = ImageDraw.Draw(wash)
    for _ in range(60):
        cx, cy, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(80, 260) * K
        dw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SAND)
    for _, lat, lon, rad in forests:
        cx, cy = xy(lat, lon)
        R = rad * s
        for _ in range(40):
            ang, dist = rnd.uniform(0, 2 * math.pi), rnd.uniform(0, R)
            px, py = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
            r = rnd.uniform(0.25, 0.5) * R
            dw.ellipse([px - r, py - r, px + r, py + r], fill=GREEN)
    wash = wash.filter(ImageFilter.GaussianBlur(28 * K))
    img = Image.blend(img, wash, 0.75)
    d = ImageDraw.Draw(img)
    for name, lat, lon, rad in forests:  # ёлочки в лесу
        cx, cy = xy(lat, lon)
        R = rad * s * 0.8
        for _ in range(55):
            ang, dist = rnd.uniform(0, 2 * math.pi), R * math.sqrt(rnd.uniform(0, 1))
            px, py = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
            h = rnd.uniform(18, 30) * K
            d.polygon([(px, py - h), (px - h * 0.38, py), (px + h * 0.38, py)], fill=GREEN2)
        d.text((cx, cy - R - 26 * K), name, font=font(30, italic=True, bold=True), fill=(80, 110, 70), anchor="mm",
               stroke_width=round(4 * K), stroke_fill=PAPER)
    for name, lat, lon in regions:
        d.text(xy(lat, lon), name, font=font(34, italic=True), fill=(125, 105, 85), anchor="mm")

    pos = {p[0]: xy(p[1], p[2]) for p in places}
    legs = [(p, q) for r in a.route for route in [[x for x in r.split(">") if x]] for p, q in zip(route, route[1:])]
    for p, q in legs:  # пунктир чуть дугой
        (ax, ay), (bx, by) = pos[p], pos[q]
        mx, my = (ax + bx) / 2 + (by - ay) * 0.15, (ay + by) / 2 - (bx - ax) * 0.15
        pts = [((1 - t) ** 2 * ax + 2 * (1 - t) * t * mx + t * t * bx,
                (1 - t) ** 2 * ay + 2 * (1 - t) * t * my + t * t * by) for t in [i / 60 for i in range(61)]]
        for i in range(0, 60, 3):
            d.line([pts[i], pts[i + 1]], fill=ACCENT, width=round(5 * K))
        (px, py), (qx, qy) = pts[52], pts[56]  # стрелка у конца
        ang = math.atan2(qy - py, qx - px)
        L = 20 * K
        d.polygon([(qx, qy), (qx - L * math.cos(ang - 0.45), qy - L * math.sin(ang - 0.45)),
                   (qx - L * math.cos(ang + 0.45), qy - L * math.sin(ang + 0.45))], fill=ACCENT)

    for name, lat, lon, flags in places:
        x, y = xy(lat, lon)
        big = "big" in flags
        r = (15 if big else 9) * K
        d.ellipse([x - r, y - r, x + r, y + r], fill=ACCENT if big else INK, outline=PAPER, width=round(3 * K))
        f = font(36 if big else 27, bold=big)
        at = {"left": ((x - r - 10 * K, y), "rm"), "below": ((x, y + r + 8 * K), "mt"),
              "above": ((x, y - r - 8 * K), "mb"), "belowright": ((x + r, y + r + 6 * K), "lt")}
        (tx, ty), anchor = next((at[k] for k in at if k in flags), ((x + r + 10 * K, y), "lm"))
        d.text((tx, ty), name, font=f, fill=INK, anchor=anchor, stroke_width=round(4 * K), stroke_fill=PAPER)

    out = a.folder / "pages" / "book" / "map.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(out)


if __name__ == "__main__":
    main()
