#!/usr/bin/env python3
"""Аватар человека на сайте — какое лицо показывать в кружке у имени.

Зачем: раньше аватаром была просто первая строка `media` карточки, и в кружке оказывались могила, лист метрики или
общее фото с пятью людьми. Теперь у карточки своё поле `avatar:` — вырезанное лицо, — а `avatar_from:` говорит, из
какого снимка его вырезали (закрыт снимок паролем — закрыт и аватар). Нет поля — сайт берёт первое фото, как раньше.

Порядок выбора (решение владельца дерева, 17.11.2026):
  1. портрет, где человек один;
  2. нет портрета — лицо, вырезанное из общего фото;
  3. нет общего — лицо с фото на документе (паспорт, анкета, удостоверение);
  4. только могила — снимок могилы;
  5. только документ без фото — документ.

Лица ищет встроенное в macOS распознавание (faces.swift, Vision) — без сети. На общем фото машина не знает, кто
есть кто: такой снимок идёт в список «выбрать лицо» с пронумерованными рамками (`pick`), номер ставит человек или
модель по подписи, потом `set … --face N`.

    tools/py tools/scripts/avatar.py scan                  # все люди с фото: вид снимков, лица, что выбрано бы
    tools/py tools/scripts/avatar.py auto [--dry]          # проставить, где выбор однозначен (портрет, могила, документ…)
    tools/py tools/scripts/avatar.py pick                  # снимки с рамками лиц для тех, где надо выбрать лицо
    tools/py tools/scripts/avatar.py set "<Карточка>" "<файл.jpg>" [--face N | --box x0,y0,x1,y1 | --whole]
    tools/py tools/scripts/avatar.py missing               # у кого есть фото, а аватара нет
    tools/py tools/scripts/avatar.py sheet [--out файл]    # лист всех аватаров для проверки (лёгкий HTML)
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFile, ImageFont, ImageOps

ImageFile.LOAD_TRUNCATED_IMAGES = True  # обрезанный в конце JPEG из старых выгрузок — читаем, что есть

import paths

FACES_SRC = paths.SCRIPTS / "faces.swift"
FACES_BIN = paths.CACHE / "avatar" / "faces"
SCAN = paths.CACHE / "avatar" / "scan.json"
OUT_DIR = paths.PHOTOS_PROCESSED / "avatars"
PICK_DIR = paths.CACHE / "avatar" / "pick"
MANIFEST = paths.ROOT / "media" / "manifest.jsonl"
IMG = (".jpg", ".jpeg", ".png", ".webp")

RANK_NAME = {1: "портрет одного", 2: "общее фото", 3: "фото на документе", 4: "могила", 5: "документ", 9: "не ясно"}
GRAVE = re.compile(r"могил|надгроб|кладбищ|grave|памятник", re.I)
DOC_PHOTO = re.compile(r"паспорт|анкет|удостовер|пропуск|фото-на-документ|личн\w*-листок|билет|карточк|документ", re.I)
GROUP = re.compile(r"дед_баба|семь|-с-|_с-|-и-|_и_|внук|дет[иь]|родител|компани|family|with", re.I)
DOC = re.compile(r"метрик|рожд|прошени|№\d|крещени|брак|смерт|венча|ГАСО|ревиз|перепис|сказк|запис|акт|DGS|_FS_|FamilySearch|_сн\d|"
                 r"Ellis|список|выпис|трудов|справк|ф\d+_оп|разв\d|приход|книг|ведомост|исповед|заявлен|письм|некролог|газет", re.I)


def N(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def media_paths() -> dict[str, Path]:
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rel = json.loads(line)["path"]
            out.setdefault(N(Path(rel).name), paths.ROOT / rel)
    return out


def front(p: Path) -> tuple[str, str]:
    s = p.read_text(encoding="utf-8")
    end = s.index("\n---", 4)
    return s[:end], s[end:]


def links(fm: str, field: str) -> list[str]:
    m = re.search(rf"^{field}:[ \t]*(.*)\n((?:  - .*\n?)*)", fm + "\n", re.M)
    if not m:
        return []
    return [N(x.split("|")[0]) for x in re.findall(r"\[\[([^\]]+)\]\]", m.group(1) + m.group(2))]


def faces(img: Path) -> dict:
    if not FACES_BIN.exists():
        FACES_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", "-o", str(FACES_BIN), str(FACES_SRC)], check=True)
    try:
        with Image.open(img) as im:  # Vision не знает про поворот из EXIF — даём уже повёрнутую копию
            im = ImageOps.exif_transpose(im).convert("RGB")
            with tempfile.NamedTemporaryFile(suffix=".jpg") as t:
                im.save(t.name, "JPEG", quality=92)
                run = subprocess.run([str(FACES_BIN), t.name], capture_output=True, text=True)
    except OSError as e:
        print(f"не открыть {img.name}: {e}", file=sys.stderr)
        return {"width": 0, "height": 0, "faces": []}
    try:
        page = json.loads(run.stdout.strip().splitlines()[0])
    except (IndexError, json.JSONDecodeError):
        return {"width": 0, "height": 0, "faces": []}
    page["faces"] = [f for f in page["faces"] if f["conf"] >= 0.5 and f["w"] >= 12]
    return page


def rank_of(name: str, n_faces: int) -> int:
    if GRAVE.search(name):
        return 4
    if DOC_PHOTO.search(name):
        return 3 if n_faces else 5
    if DOC.search(name):
        return 3 if n_faces else 5
    if n_faces == 1:  # Vision на старых снимках пропускает лица: «дед_баба», «с-женой» — общее, хоть лицо найдено одно
        return 2 if GROUP.search(name) else 1
    if n_faces > 1:
        return 2
    return 9


def scan(only: set[str] | None = None) -> dict:
    where = media_paths()
    cache = json.loads(SCAN.read_text()) if SCAN.exists() else {}
    seen_faces = {f["file"]: f for p in cache.values() for f in p["files"]}
    out = {}
    for card in sorted(paths.PEOPLE.glob("*.md")):
        if only and N(card.stem) not in only:
            continue
        fm, _ = front(card)
        files = [m for m in links(fm, "media") if m.lower().endswith(IMG)]
        if not files:
            continue
        rows = []
        for name in files:
            src = where.get(name)
            if not src or not src.exists():
                rows.append({"file": name, "missing": True, "rank": 9, "faces": []})
                continue
            old = seen_faces.get(name)
            page = old if old and old.get("mtime") == src.stat().st_mtime else {**faces(src), "mtime": src.stat().st_mtime}
            n = len(page["faces"])
            rows.append({"file": name, "path": str(src.relative_to(paths.ROOT)), "faces": page["faces"],
                         "width": page["width"], "height": page["height"], "mtime": page["mtime"], "rank": rank_of(name, n)})
        out[N(card.stem)] = {"avatar": (links(fm, "avatar") or [None])[0], "files": rows}
    SCAN.parent.mkdir(parents=True, exist_ok=True)
    SCAN.write_text(json.dumps({**cache, **out}, ensure_ascii=False, indent=1))
    return out


def choice(person: dict) -> tuple[dict | None, str]:
    """Лучший снимок по порядку и что с ним делать: auto (однозначно) или pick (выбрать лицо)."""
    ok = [f for f in person["files"] if not f.get("missing")]
    if not ok:
        return None, "нет файлов"
    best = min(ok, key=lambda f: f["rank"])  # min устойчив: при равенстве — раньше в media
    if best["rank"] in (1, 4, 5):
        return best, "auto"
    if best["rank"] == 3:
        return best, "auto" if len(best["faces"]) == 1 else "pick"
    if best["rank"] == 2:  # на общем фото машина не знает, кто есть кто, даже если нашла одно лицо
        return best, "pick"
    return best, "pick"


def crop_face(src: Path, face: dict | None, box: tuple[int, int, int, int] | None, margin: float = 2.2) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    W, H = im.size
    if face:  # голова с плечами: квадрат в margin раз шире лица (на общем фото — теснее, без соседей), лицо чуть выше середины
        cx, cy, side = face["x"] + face["w"] / 2, face["y"] + face["h"] * 0.6, max(face["w"], face["h"]) * margin
    elif box:
        x0, y0, x1, y1 = box
        cx, cy, side = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * margin / 2.2
    else:
        return im
    side = min(side, W, H)
    x0 = min(max(cx - side / 2, 0), W - side)
    y0 = min(max(cy - side / 2, 0), H - side)
    return im.crop((int(x0), int(y0), int(x0 + side), int(y0 + side)))


def write_fields(card: Path, avatar: str, origin: str) -> None:
    fm, rest = front(card)
    fm = re.sub(r"^avatar(_from)?:.*\n?", "", fm + "\n", flags=re.M).rstrip("\n")
    add = f'avatar: "[[{avatar}]]"\navatar_from: "[[{origin}]]"'
    if re.search(r"^lineage:", fm, re.M):  # ветки assign_lineage держит последними — встаём перед ними
        fm = re.sub(r"^lineage:", lambda m: add + "\nlineage:", fm, count=1, flags=re.M)
    else:
        fm += "\n" + add
    card.write_text(fm + rest, encoding="utf-8")


def set_avatar(card_name: str, file: str, face_no: int | None = None, box=None, whole=False, dry=False) -> str:
    card = paths.PEOPLE / f"{card_name}.md"
    src = media_paths().get(N(file))
    if not card.exists() or not src:
        raise SystemExit(f"нет карточки или файла: {card_name} / {file}")
    if whole:  # могила, документ без фото — сам снимок, без вырезки
        if not dry:
            write_fields(card, N(file), N(file))
        return N(file)
    page = faces(src)
    face = None
    if box is None:
        if face_no is None:
            if len(page["faces"]) != 1:
                raise SystemExit(f"{file}: лиц {len(page['faces'])} — укажите --face N (avatar.py pick) или --box")
            face_no = 1
        if not 1 <= face_no <= len(page["faces"]):
            raise SystemExit(f"{file}: лица №{face_no} нет, всего {len(page['faces'])}")
        face = page["faces"][face_no - 1]
    group = len(page["faces"]) > 1 or box is not None
    if face and not group and face["w"] < 0.12 * page["width"]:  # крошечное лицо вдали: снимок одного — целиком
        whole = True
    if whole:
        if not dry:
            write_fields(card, N(file), N(file))
        return N(file)
    name = N(f"{card_name}_аватар.jpg").replace(" ", "-")
    if not dry:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        im = crop_face(src, face, box, margin=1.5 if group else 2.2)
        im.thumbnail((600, 600))
        im.save(OUT_DIR / name, "JPEG", quality=90)
        write_fields(card, name, N(file))
    return name


def cmd_auto(dry: bool) -> None:
    data = scan()
    done = picks = 0
    for card, person in data.items():
        if person["avatar"]:
            continue
        best, how = choice(person)
        if how != "auto":
            picks += how == "pick"
            continue
        whole = best["rank"] in (4, 5)
        name = set_avatar(card, best["file"], whole=whole, dry=dry)
        print(f"{'(проба) ' if dry else ''}{card}: {RANK_NAME[best['rank']]} — {best['file']} → {name}")
        done += 1
    if not dry and done:
        subprocess.run([sys.executable, str(paths.SCRIPTS / "media.py"), "add"], check=False)
    print(f"\nпроставлено: {done}; надо выбрать лицо: {picks} — avatar.py pick")


def cmd_pick() -> None:
    data = scan()
    PICK_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for card, person in data.items():
        if person["avatar"]:
            continue
        best, how = choice(person)
        if how != "pick":
            continue
        im = ImageOps.exif_transpose(Image.open(paths.ROOT / best["path"])).convert("RGB")
        d = ImageDraw.Draw(im)
        font = ImageFont.load_default(size=max(18, im.width // 30))
        for i, f in enumerate(best["faces"], 1):
            d.rectangle((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]), outline=(255, 40, 40), width=max(2, im.width // 300))
            d.text((f["x"], max(0, f["y"] - font.size - 4)), str(i), fill=(255, 40, 40), font=font)
        im.thumbnail((1400, 1400))
        out = PICK_DIR / f"{card}.jpg"
        im.save(out, "JPEG", quality=85)
        others = [f["file"] for f in person["files"] if f is not best]
        todo.append({"card": card, "file": best["file"], "kind": RANK_NAME[best["rank"]], "faces": len(best["faces"]),
                     "marked": str(out), "other_files": others})
    (PICK_DIR / "todo.json").write_text(json.dumps(todo, ensure_ascii=False, indent=1))
    for t in todo:
        print(f"{t['card']}: {t['kind']}, лиц {t['faces']} — {t['file']}")
    print(f"\nвсего {len(todo)}; снимки с номерами лиц — {PICK_DIR}, список — {PICK_DIR / 'todo.json'}")


def cmd_missing() -> None:
    n = 0
    for card in sorted(paths.PEOPLE.glob("*.md")):
        fm, _ = front(card)
        if any(m.lower().endswith(IMG) for m in links(fm, "media")) and not links(fm, "avatar"):
            print(card.stem)
            n += 1
    print(f"без аватара при фото: {n}")
    sys.exit(1 if n else 0)


def cmd_sheet(out: Path) -> None:
    where = {**media_paths(), **{N(p.name): p for p in OUT_DIR.glob("*.jpg")}}
    cards = []
    for card in sorted(paths.PEOPLE.glob("*.md")):
        fm, _ = front(card)
        av = links(fm, "avatar")
        if not av or not where.get(av[0]):
            continue
        im = ImageOps.exif_transpose(Image.open(where[av[0]])).convert("RGB")
        im.thumbnail((130, 130))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=68)
        src = (links(fm, "avatar_from") or [""])[0]
        cards.append(f'<figure><img src="data:image/jpeg;base64,{base64.b64encode(b.getvalue()).decode()}">'
                     f'<figcaption><b>{html.escape(card.stem)}</b><span>{html.escape(src)}</span></figcaption></figure>')
    out.write_text(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Аватары — проверка</title><style>
:root{{--bg:#faf8f4;--fg:#222;--mut:#777;--card:#fff}}@media (prefers-color-scheme:dark){{:root{{--bg:#1b1a18;--fg:#eee;--mut:#999;--card:#262522}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.35 -apple-system,system-ui,sans-serif;margin:0;padding:16px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
figure{{margin:0;background:var(--card);border-radius:8px;padding:8px;text-align:center}}
img{{width:110px;height:110px;object-fit:cover;border-radius:50%}}figcaption b{{display:block}}
figcaption span{{display:block;color:var(--mut);font-size:11px;word-break:break-all}}</style></head><body>
<h1>Аватары: {len(cards)}</h1><div class="g">{''.join(cards)}</div></body></html>""", encoding="utf-8")
    print(f"{out} — аватаров {len(cards)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    a = sub.add_parser("auto")
    a.add_argument("--dry", action="store_true")
    sub.add_parser("pick")
    s = sub.add_parser("set")
    s.add_argument("card")
    s.add_argument("file")
    s.add_argument("--face", type=int)
    s.add_argument("--box")
    s.add_argument("--whole", action="store_true")
    sub.add_parser("missing")
    h = sub.add_parser("sheet")
    h.add_argument("--out", type=Path, default=paths.CACHE / "avatar" / "аватары.html")
    args = ap.parse_args()
    if args.cmd == "scan":
        data = scan()
        from collections import Counter
        c = Counter()
        for person in data.values():
            best, how = choice(person)
            c[(RANK_NAME[best["rank"]] if best else "нет файлов", how)] += 1
        for (k, how), n in sorted(c.items()):
            print(f"{n:4}  {k} — {how}")
    elif args.cmd == "auto":
        cmd_auto(args.dry)
    elif args.cmd == "pick":
        cmd_pick()
    elif args.cmd == "set":
        box = tuple(int(x) for x in args.box.split(",")) if args.box else None
        print(set_avatar(args.card, args.file, args.face, box, args.whole))
    elif args.cmd == "missing":
        cmd_missing()
    elif args.cmd == "sheet":
        cmd_sheet(args.out)


if __name__ == "__main__":
    main()
