#!/usr/bin/env python3
"""Кто где на общем фото — рамки лиц с именами. На сайте в окне просмотра снимка навёл мышь на лицо — рамка и имя.

Хранится в самом снимке, в невидимой подписи jpg (метаданные XMP) — стандартной метке лиц MWG Regions, той, что
пишут и читают Lightroom, digiKam, ExifTool. Снимок унёс в другую программу или отдал родне — имена едут с ним.
В каждой рамке — имя карточки («Анна Ковальчик», «Иван Петров (1957)»): по нему сайт находит человека. Ещё
список имён — в поле «люди на снимке» (IPTC PersonInImage), по нему программы для фото ищут.

Рамка — доли ширины и высоты снимка (центр, ширина, высота — так требует стандарт). В файле — только лицо: так
метку понимают программы. Фигуру целиком для сайта находит распознавание (bodies.swift) при сборке. Снимки с поворотом в EXIF не
трогаем: программы по-разному понимают, к чему тогда относятся доли.

Пишет и читает exiftool (brew). Файл после записи другой — `media.py push` отправит новую копию в облако.

Лица ищет то же распознавание macOS, что у аватаров (avatar.py, faces.swift). Машина не знает, кто есть кто: `show`
рисует снимок с номерами найденных лиц, номер ставит человек или модель по подписи, потом `tag … --face N`.
Лицо, которое распознавание не нашло (старое, мутное, в профиль), — `--box` в пикселях снимка.

    tools/py tools/scripts/photo_faces.py show "<файл.jpg>"                      # снимок с номерами лиц → путь к картинке
    tools/py tools/scripts/photo_faces.py tag "<файл.jpg>" "<Карточка>" --face N # или --box x0,y0,x1,y1 (пиксели)
    tools/py tools/scripts/photo_faces.py untag "<файл.jpg>" "<Карточка>"
    tools/py tools/scripts/photo_faces.py list                                   # что отмечено (снимки из карточек людей)
    tools/py tools/scripts/photo_faces.py todo                                   # общие фото, где отмечены не все
    tools/py tools/scripts/photo_faces.py from-avatars [--dry]                   # лица, уже выбранные для аватаров

`avatar.py set … --face N` на общем фото отмечает лицо и здесь.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

import paths

CACHE = paths.CACHE / "photo_faces"
READ_CACHE = CACHE / "read.json"
BODY_CACHE = CACHE / "bodies.json"
BODIES_SRC = paths.SCRIPTS / "bodies.swift"
BODIES_BIN = CACHE / "bodies"


def N(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def exiftool() -> str:
    exe = shutil.which("exiftool")
    if not exe:
        raise SystemExit("нет exiftool: brew install exiftool")
    return exe


# ---------- карточки ----------

def cards() -> dict[str, str]:
    """имя карточки → cr_id"""
    out = {}
    for card in paths.PEOPLE.glob("*.md"):
        if m := re.search(r"^cr_id:\s*\"?([^\"\n]+)", card.read_text(encoding="utf-8"), re.M):
            out[N(card.stem)] = m[1].strip()
    return out


def media_of_people() -> dict[str, set[str]]:
    """снимок → карточки, в чьих media он стоит"""
    import avatar
    out: dict[str, set[str]] = {}
    for card in paths.PEOPLE.glob("*.md"):
        fm, _ = avatar.front(card)
        for f in avatar.links(fm, "media"):
            if f.lower().endswith((".jpg", ".jpeg")):
                out.setdefault(f, set()).add(N(card.stem))
    return out


def source(file: str) -> Path:
    import avatar
    src = avatar.media_paths().get(N(file))
    if not src or not src.exists():
        raise SystemExit(f"нет снимка в описи медиа: {file}")
    return src


# ---------- чтение и запись метки в файле ----------

def _parse(row: dict) -> list[dict]:
    """Строка exiftool -j -struct → [{"name", "box": [x0, y0, x1, y1] в долях}]"""
    info = row.get("RegionInfo") or {}
    out = []
    for r in info.get("RegionList") or []:
        a = r.get("Area") or {}
        if r.get("Type", "Face") != "Face" or not r.get("Name") or a.get("Unit", "normalized") != "normalized":
            continue
        x, y, w, h = (float(a.get(k, 0)) for k in ("X", "Y", "W", "H"))
        out.append({"name": N(str(r["Name"])), "box": [round(x - w / 2, 4), round(y - h / 2, 4), round(x + w / 2, 4), round(y + h / 2, 4)]})
    return out


def read(files: list[Path]) -> dict[Path, list[dict]]:
    """Рамки из файлов; прочитанное помним по размеру и времени файла — повторная сборка сайта не ждёт exiftool."""
    cache = json.loads(READ_CACHE.read_text()) if READ_CACHE.exists() else {}
    out, todo = {}, []
    for f in files:
        st = f.stat()
        c = cache.get(str(f))
        if c and c["mtime"] == st.st_mtime and c["size"] == st.st_size:
            out[f] = c["faces"]
        else:
            todo.append(f)
    for i in range(0, len(todo), 500):
        part = todo[i:i + 500]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as t:
            t.write("\n".join(map(str, part)))
        run = subprocess.run([exiftool(), "-j", "-struct", "-n", "-charset", "filename=utf8", "-XMP-mwg-rs:RegionInfo",
                              "-@", t.name], capture_output=True, text=True)
        Path(t.name).unlink()
        rows = {N(r["SourceFile"]): r for r in json.loads(run.stdout or "[]")}
        for f in part:
            faces = _parse(rows.get(N(str(f)), {}))
            st = f.stat()
            cache[str(f)] = {"mtime": st.st_mtime, "size": st.st_size, "faces": faces}
            out[f] = faces
    if todo:
        CACHE.mkdir(parents=True, exist_ok=True)
        READ_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    return out


def write(src: Path, faces: list[dict]) -> None:
    """Записать рамки в файл целиком (прежние метки лиц заменяются). Картинка не пережимается — меняется только подпись."""
    with Image.open(src) as im:
        if (im.getexif().get(0x0112) or 1) != 1:
            raise SystemExit(f"{src.name}: снимок с поворотом в EXIF — рамки не пишем (повернуть файл и сбросить поворот)")
        W, H = im.size
    faces = sorted(faces, key=lambda r: r["box"][0])  # слева направо — как подписи
    if faces:
        region = {"AppliedToDimensions": {"W": W, "H": H, "Unit": "pixel"},
                  "RegionList": [{"Type": "Face", "Name": r["name"],
                                  "Area": {"X": round((r["box"][0] + r["box"][2]) / 2, 4), "Y": round((r["box"][1] + r["box"][3]) / 2, 4),
                                           "W": round(r["box"][2] - r["box"][0], 4), "H": round(r["box"][3] - r["box"][1], 4),
                                           "Unit": "normalized"}} for r in faces]}
        data = [{"SourceFile": "*", "XMP-mwg-rs:RegionInfo": region, "XMP-iptcExt:PersonInImage": [r["name"] for r in faces]}]
    else:
        data = [{"SourceFile": "*", "XMP-mwg-rs:RegionInfo": "", "XMP-iptcExt:PersonInImage": ""}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as t:
        json.dump(data, t, ensure_ascii=False)
    run = subprocess.run([exiftool(), "-q", "-overwrite_original", "-charset", "filename=utf8", f"-j={t.name}", str(src)],
                         capture_output=True, text=True)
    Path(t.name).unlink()
    if run.returncode:
        raise SystemExit(f"exiftool: {src.name}: {run.stderr.strip()}")


def frac(box: tuple[float, float, float, float], w: int, h: int) -> list[float]:
    x0, y0, x1, y1 = box
    return [round(min(max(v, 0), 1), 4) for v in (x0 / w, y0 / h, x1 / w, y1 / h)]


def set_person(file: str, card_name: str, box: list[float] | None) -> None:
    """Поставить (box) или снять (None) рамку человека на снимке."""
    if N(card_name) not in cards():
        raise SystemExit(f"нет карточки: {card_name}")
    src = source(file)
    faces = [r for r in read([src])[src] if r["name"] != N(card_name)]
    if box:
        faces.append({"name": N(card_name), "box": box})
    write(src, faces)


def tag(file: str, card_name: str, face_no: int | None = None, box=None) -> list[float]:
    import avatar
    src = source(file)
    page = avatar.faces(src)
    if box is None:
        if face_no is None or not 1 <= face_no <= len(page["faces"]):
            raise SystemExit(f"{file}: лиц {len(page['faces'])} — укажите --face N (номер из show) или --box")
        f = page["faces"][face_no - 1]
        box = (f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"])
    fr = frac(box, page["width"], page["height"])
    set_person(file, card_name, fr)
    return fr


# ---------- фигура целиком ----------

def bodies(files: list[Path]) -> dict[Path, list[list[float]]]:
    """Фигуры людей (bodies.swift, Vision) в долях [x0, y0, x1, y1]; прочитанное помним по размеру и времени файла."""
    cache = json.loads(BODY_CACHE.read_text()) if BODY_CACHE.exists() else {}
    out, todo = {}, []
    for f in files:
        st, c = f.stat(), cache.get(str(f))
        if c and c["mtime"] == st.st_mtime and c["size"] == st.st_size:
            out[f] = c["bodies"]
        else:
            todo.append(f)
    if todo:
        if not BODIES_BIN.exists() or BODIES_BIN.stat().st_mtime < BODIES_SRC.stat().st_mtime:
            CACHE.mkdir(parents=True, exist_ok=True)
            subprocess.run(["swiftc", "-O", "-o", str(BODIES_BIN), str(BODIES_SRC)], check=True)
        for i in range(0, len(todo), 50):
            part = todo[i:i + 50]
            run = subprocess.run([str(BODIES_BIN), *map(str, part)], capture_output=True, text=True)
            rows = {N(r["image"]): r["bodies"] for r in map(json.loads, run.stdout.splitlines())}
            for f in part:
                b = [[x["x0"], x["y0"], x["x1"], x["y1"]] for x in rows.get(N(str(f)), []) if x["conf"] >= 0.3]
                st = f.stat()
                cache[str(f)] = {"mtime": st.st_mtime, "size": st.st_size, "bodies": b}
                out[f] = b
        BODY_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    return out


def body_of(faces: list[list[float]], found: list[list[float]]) -> list[list[float]]:
    """Каждому лицу — фигура. Своя — фигура из распознавания, у которой лицо вверху посередине и которую не делит с
    другим лицом (ребёнок на руках не получит фигуру взрослого). Нет такой — по пропорциям от лица: плечи в три
    ширины лица, вниз — четыре высоты лица (корпус: рост по лицу не угадать — ребёнок на руках получил бы взрослый),
    не ниже края снимка и не на того, кто стоит впереди (тогда — голова и плечи)."""
    claim: dict[int, list[tuple[float, int]]] = {}
    for k, (x0, y0, x1, y1) in enumerate(faces):
        cx, fw, fh = (x0 + x1) / 2, x1 - x0, y1 - y0
        best = None
        for j, (bx0, by0, bx1, by1) in enumerate(found):
            if bx0 <= cx <= bx1 and by0 - 1.5 * fh <= y0 and by0 <= y0 + 0.5 * fh and bx1 - bx0 <= 6 * fw and by1 > y1:
                d = abs(y0 - by0) + abs(cx - (bx0 + bx1) / 2)
                if best is None or d < best[0]:
                    best = (d, j)
        if best:
            claim.setdefault(best[1], []).append((best[0], k))
    own = {min(ks)[1]: j for j, ks in claim.items()}
    out = []
    for k, (x0, y0, x1, y1) in enumerate(faces):
        if k in own:
            bx0, by0, bx1, by1 = found[own[k]]
            out.append([round(min(bx0, x0), 4), round(min(by0, y0), 4), round(max(bx1, x1), 4), round(max(by1, y1), 4)])
            continue
        cx, fw, fh = (x0 + x1) / 2, x1 - x0, y1 - y0
        bottom = min(1, y1 + 4 * fh)
        # стоит сзади: фигура кончается там, где начинается человек перед ним (чужая фигура или лицо ниже его лица)
        ahead = [by0 for j, (bx0, by0, bx1, _) in enumerate(found) if own.get(k) != j and bx0 <= cx <= bx1 and by0 > y0 + 0.5 * fh]
        ahead += [oy0 for m, (ox0, oy0, ox1, _) in enumerate(faces) if m != k and ox0 - fw / 2 <= cx <= ox1 + fw / 2 and oy0 > y1]
        if ahead:
            bottom = min(bottom, max(y1 + fh, min(ahead)))
        out.append([round(max(0, cx - 1.5 * fw), 4), round(max(0, y0 - 0.35 * fh), 4),
                    round(min(1, cx + 1.5 * fw), 4), round(bottom, 4)])
    return out


# ---------- для сайта ----------

def for_site() -> dict[str, list[tuple[str, list[float], list[float]]]]:
    """Имя снимка → [(cr_id, рамка лица, рамка фигуры)] — снимки из карточек людей; имя без карточки — пропуск."""
    import avatar
    where, ids = avatar.media_paths(), cards()
    files = {f: where[f] for f in media_of_people() if f in where and where[f].exists()}
    got = read(list(files.values()))
    marked = {f: p for f, p in files.items() if any(r["name"] in ids for r in got[p])}
    found = bodies(list(marked.values()))
    out = {}
    for f, p in marked.items():
        rows = [r for r in got[p] if r["name"] in ids]
        figs = body_of([r["box"] for r in rows], found[p])
        out[f] = [(ids[r["name"]], r["box"], b) for r, b in zip(rows, figs)]
    return out


# ---------- команды ----------

def cmd_show(file: str) -> None:
    import avatar
    src = source(file)
    page = avatar.faces(src)
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=max(18, im.width // 30))
    thick = max(2, im.width // 300)
    for i, f in enumerate(page["faces"], 1):
        d.rectangle((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), outline=(255, 40, 40), width=thick)
        d.text((f["x"], max(0, f["y"] - font.size - 4)), str(i), fill=(255, 40, 40), font=font)
    for r in read([src])[src]:  # уже отмеченные — зелёным, с именем
        x0, y0, x1, y1 = r["box"]
        d.rectangle((x0 * im.width, y0 * im.height, x1 * im.width, y1 * im.height), outline=(40, 200, 80), width=thick)
        d.text((x0 * im.width, y1 * im.height + 4), r["name"], fill=(40, 200, 80), font=font)
    im.thumbnail((1600, 1600))
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / (re.sub(r"[^\w.-]", "_", Path(file).stem) + ".jpg")
    im.save(out, "JPEG", quality=85)
    print(f"лиц найдено {len(page['faces'])}; красные — номера для --face, зелёные — уже отмечены\n{out}")


def cmd_list() -> None:
    import avatar
    where = avatar.media_paths()
    files = [where[f] for f in media_of_people() if f in where and where[f].exists()]
    for p, faces in sorted(read(files).items()):
        if faces:
            print(f"{p.name}: " + ", ".join(r["name"] for r in faces))


def cmd_todo() -> None:
    """Снимки, что стоят в media у двух и больше карточек, а отмечены на них не все."""
    import avatar
    where = avatar.media_paths()
    # метрики, списки, прошения и могилы — не снимки людей, отмечать на них нечего (те же приметы, что у аватаров)
    by_file = {f: c for f, c in media_of_people().items() if len(c) > 1 and f in where and where[f].exists()
               and not avatar.GRAVE.search(f) and not (avatar.DOC.search(f) and not avatar.DOC_PHOTO.search(f))}
    got = read([where[f] for f in by_file])
    n = 0
    for f, who in sorted(by_file.items()):
        miss = who - {r["name"] for r in got[where[f]]}
        if miss:
            n += 1
            print(f"{f}: не отмечены — " + ", ".join(sorted(miss)))
    print(f"\nснимков, где отмечены не все: {n}")


def cmd_from_avatars(dry: bool) -> None:
    """Аватар с общего фото — это вырезка вокруг одного из найденных лиц. Вырезаем вокруг каждого лица так же,
    как avatar.py, и берём то, что больше всего похоже на сохранённый аватар; не похоже ни одно — пропускаем."""
    import avatar
    where = avatar.media_paths()
    n, skipped = 0, []
    for card in sorted(paths.PEOPLE.glob("*.md")):
        fm, _ = avatar.front(card)
        av, origin = (avatar.links(fm, "avatar") or [None])[0], (avatar.links(fm, "avatar_from") or [None])[0]
        if not av or not origin or av == origin:
            continue
        src, cut = where.get(origin), avatar.OUT_DIR / av
        if not src or not src.exists() or not cut.exists():
            continue
        page = avatar.faces(src)
        if len(page["faces"]) < 2:
            continue  # портрет одного — рамка на сайте ничего не скажет
        want = Image.open(cut).convert("L").resize((48, 48))
        best = None
        for f in page["faces"]:
            got = avatar.crop_face(src, f, None, margin=1.5).convert("L").resize((48, 48))
            diff = sum(abs(a - b) for a, b in zip(want.tobytes(), got.tobytes())) / (48 * 48)
            if best is None or diff < best[0]:
                best = (diff, f)
        if best[0] > 12:  # среднее отличие яркости больше 12 из 255 — лицо выбирали рамкой (--box), не угадываем
            skipped.append(f"{N(card.stem)} ({origin}, отличие {best[0]:.0f})")
            continue
        f = best[1]
        if not dry:
            set_person(origin, card.stem, frac((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), page["width"], page["height"]))
        n += 1
        print(f"{N(card.stem)} → {origin}")
    print(f"\nотмечено {n}{' (проба, не записано)' if dry else ''}; пропущено {len(skipped)}")
    for s in skipped:
        print("  пропущен:", s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").add_argument("file")
    t = sub.add_parser("tag")
    t.add_argument("file")
    t.add_argument("card")
    t.add_argument("--face", type=int)
    t.add_argument("--box")
    u = sub.add_parser("untag")
    u.add_argument("file")
    u.add_argument("card")
    sub.add_parser("list")
    sub.add_parser("todo")
    sub.add_parser("from-avatars").add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "show":
        cmd_show(a.file)
    elif a.cmd == "tag":
        print(tag(a.file, a.card, a.face, tuple(int(x) for x in a.box.split(",")) if a.box else None))
    elif a.cmd == "untag":
        set_person(a.file, a.card, None)
    elif a.cmd == "list":
        cmd_list()
    elif a.cmd == "todo":
        cmd_todo()
    else:
        cmd_from_avatars(a.dry)


if __name__ == "__main__":
    sys.exit(main())
