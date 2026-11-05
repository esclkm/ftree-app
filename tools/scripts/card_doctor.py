#!/usr/bin/env python3
"""«Доктор карточек»: ищет в карточках людей красные сигналы и сам чинит то, что чинится без раздумий.

Зачем. Галерея карточки (поле `media`) уходит на сайт и в книгу. Когда одно и то же фото висит в ней
дважды — из MyHeritage пришла копия, обрезка лица, реставрация рядом с оригиналом, — в книге человек
повторяется на соседних страницах. Руками это не уследить: людей 500, фото сотни.

Чинит сам (с --fix):
  M1  одна и та же ссылка в media дважды;
  M2  два разных файла с одинаковой картинкой (байт в байт или пиксель в пиксель — MyHeritage кладёт
      профильное фото вторым файлом, отличие только в служебных данных);
  M3  одно фото — большая часть другого: тот же снимок с другими краями (MyHeritage обрезал под
      квадрат) или реставрация рядом с оригиналом. Лицо, вырезанное из общего фото, — портрет, остаётся.
      Оставляем одно: реставрацию (не «без-ИИ»), иначе — самое полное; оно встаёт на место первого;
  S1  один источник в `sources` дважды;
  F1  одна и та же строка факта дважды.
Только сообщает (решает человек):
  F2  строка в «Факты (с источником)» без источника;
  D1  смерть раньше рождения, возраст больше 110;
  D2  родитель моложе 13 или мать старше 55 при рождении ребёнка — обычно ребёнок привязан не к тем;
  N1  отчество в названии карточки (правило проекта: отчеств в карточках нет).

Сами файлы фото не трогает — только строки в карточках. Оригиналы на этаже 1 остаются где были.

Запуск:  python3 tools/scripts/card_doctor.py                 # отчёт по всем карточкам
         python3 tools/scripts/card_doctor.py --fix           # отчёт + починить M1–M3, S1, F1
         python3 tools/scripts/card_doctor.py --fix "Имя" …   # только эти карточки (так зовёт хук)
         python3 tools/scripts/card_doctor.py --quiet         # одна строка-итог
Хэши картинок кэшируются в tools/.cache/card_doctor.json — повторный прогон быстрый.
"""
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)
PEOPLE = paths.TREE / "people"
CACHE = paths.CACHE / "card_doctor.json"
IMG = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
SKIP = (".git", "tools", ".obsidian", paths.OUTPUTS.name)
Image.MAX_IMAGE_PIXELS = None
# Обрезка меньше 40 % снимка — это лицо, вырезанное из общего фото (Анна из пары с Прокопом):
# оно служит портретом, его не убираем. Больше — тот же снимок с другими краями.
FACE_CROP = 0.4
SAME = 0.95  # корреляция яркости, выше которой две картинки — один снимок


# ---------- файлы и картинки ----------

def file_index():
    idx = defaultdict(list)
    for d, ds, fs in os.walk(paths.ROOT):
        if os.path.relpath(d, paths.ROOT).startswith(SKIP):
            ds[:] = []
            continue
        for f in fs:
            idx[N(f)].append(Path(d) / f)
    return idx


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def open_small(p, side=96):
    im = Image.open(p)
    im.draft("L", (side * 4, side * 4))  # JPEG декодируется сразу уменьшенным — в разы быстрее
    return ImageOps.exif_transpose(im).convert("L")


def signature(p, cache):
    """Размер, хэш пикселей и уменьшенная копия 48 px по длинной стороне — для сравнения обрезок."""
    st = p.stat()
    key = f"{p.relative_to(paths.ROOT).as_posix()}|{st.st_size}|{int(st.st_mtime)}"
    if key in cache:
        return cache[key]
    try:
        full = ImageOps.exif_transpose(Image.open(p))
        size = full.size
        pix = __import__("hashlib").sha1(full.convert("RGB").tobytes()).hexdigest()
        im = open_small(p)
        k = 48 / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        sig = {"size": size, "pix": pix, "w": im.width, "h": im.height, "px": list(im.tobytes())}
    except Exception:
        sig = None
    cache[key] = sig
    return sig


def arr(sig):
    return np.array(sig["px"], dtype=np.float32).reshape(sig["h"], sig["w"])


def is_part_of(small, big):
    """Какую долю картинки big занимает small, если small — её кусок (обрезка) или она же с другими краями.

    Уменьшаем big до 48 px, small — до размера, который он занимал бы внутри big (перебор масштабов),
    и ищем место с корреляцией яркости ≥ SAME. Разные удостоверения на одном фоне дают до 0.90,
    обрезка из того же кадра — 0.95–1.00. Возвращает долю площади или 0.
    """
    A, B = arr(small), arr(big)
    for s in np.arange(1.05, 0.34, -0.025):
        w, h = round(B.shape[1] * s), round(B.shape[1] * s * small["h"] / small["w"])
        if w < 12 or h < 12 or w > B.shape[1] + 2 or h > B.shape[0] + 2:
            continue
        t = np.asarray(Image.fromarray(A.astype(np.uint8)).resize((w, h), Image.LANCZOS), dtype=np.float32)
        t = t[: B.shape[0], : B.shape[1]]  # другие края (реставрация срезала рамку) — сравниваем серединой
        win = np.lib.stride_tricks.sliding_window_view(B, t.shape)
        win = win - win.mean(axis=(2, 3), keepdims=True)
        t = t - t.mean()
        den = np.sqrt((win * win).sum(axis=(2, 3)) * (t * t).sum())
        score = ((win * t).sum(axis=(2, 3)) / np.where(den, den, 1)).max()
        if score >= SAME:
            return min(1.0, t.size / B.size)
    return 0.0


def restored_of(a, b):
    """a — реставрация b по имени: «X_restored…» рядом с «X» или «X-17» (номер листа архива).

    Реставрация меняет яркость и контраст, по картинке она похожа на оригинал только на 0.92–0.93."""
    stem = lambda t: re.sub(r"-\d+$", "", Path(t).stem)
    m = re.match(r"(.+?)_restored", Path(a).stem)
    return bool(m) and m.group(1) == stem(b) and "restored" not in b


def keep_rank(name, sig):
    """Кого оставить из группы одинаковых: реставрацию → «без ИИ» → самую большую."""
    n = name.lower()
    restored = "restored" in n or "реставр" in n
    return (restored and "без-ии" not in n, restored, sig["size"][0] * sig["size"][1] if sig else 0)


# ---------- карточка ----------

def list_block(text, key):
    """(начало, конец, строки) списка `key:` в блоке свойств."""
    m = re.search(rf"^{key}:\n((?:  - .*\n)*)", text, re.M)
    return (m.start(1), m.end(1), m.group(1).splitlines()) if m else None


target = lambda line: N(re.sub(r'^\s*-\s*"?\[\[([^\]|]+).*', r"\1", line).strip().strip('"'))
year = lambda v: int(m.group(1)) if (m := re.search(r"(\d{4})", v or "")) else None  # «ABT 1935» — тоже 1935


def check_media(name, text, idx, cache, fixes):
    blk = list_block(text, "media")
    if not blk:
        return text
    start, end, lines = blk
    items = []  # (строка, имя файла, подпись)
    seen, drop = {}, set()
    for i, line in enumerate(lines):
        t = target(line)
        if t in seen:
            fixes.append(f"M1 {name}: ссылка дважды — {t}")
            drop.add(i)
            continue
        seen[t] = i
        f = (idx.get(os.path.basename(t)) or [None])[0]
        sig = signature(f, cache) if f and f.suffix.lower() in IMG else None
        items.append((i, t, sig))

    # группы одинаковых картинок: объединяем пары (M2 — пиксели, M3 — часть другой)
    group = {i: {i} for i, _, _ in items}
    for a in range(len(items)):
        for b in range(a):
            (i, ti, si), (j, tj, sj) = items[a], items[b]
            if not si or not sj or group[i] is group[j]:
                continue
            code = None
            if si["pix"] == sj["pix"]:
                code = "M2"
            elif restored_of(ti, tj) or restored_of(tj, ti):
                code = "M3"
            else:
                small, big = sorted((si, sj), key=lambda s: s["size"][0] * s["size"][1])
                if is_part_of(small, big) >= FACE_CROP:
                    code = "M3"
            if code:
                merged = group[i] | group[j]
                for k in merged:
                    group[k] = merged
                fixes.append(f"{code} {name}: одно фото дважды — {ti} ≈ {tj}")

    new = {}  # позиция → строка-замена
    info = {i: (t, s) for i, t, s in items}
    for g in {id(g): g for g in group.values() if len(g) > 1}.values():
        best = max(g, key=lambda k: keep_rank(*info[k]))
        first = min(g)
        new[first] = lines[best]
        drop |= g - {first}
    if not drop and not new:
        return text
    out = [new.get(i, l) for i, l in enumerate(lines) if i not in drop]
    return text[:start] + "\n".join(out) + "\n" + text[end:]


def check_sources(name, text, fixes):
    blk = list_block(text, "sources")
    if not blk:
        return text
    start, end, lines = blk
    out, seen = [], set()
    for l in lines:
        t = target(l)
        if t in seen:
            fixes.append(f"S1 {name}: источник дважды — {t}")
            continue
        seen.add(t)
        out.append(l)
    return text if len(out) == len(lines) else text[:start] + "\n".join(out) + "\n" + text[end:]


def check_facts(name, text, fixes, flags):
    m = re.search(r"^### Факты \(с источником\)\n(.*?)(?=^#{1,3} |\Z)", text, re.M | re.S)
    if not m:
        return text
    body, out, seen = m.group(1), [], set()
    for l in body.split("\n"):
        key = re.sub(r"\s+", " ", l.strip())
        if key.startswith("- "):
            if key in seen:
                fixes.append(f"F1 {name}: факт дважды — {key[:80]}")
                continue
            seen.add(key)
            if "источник" not in key.lower() and "[[" not in key:
                flags.append(f"F2 {name}: факт без источника — {key[:90]}")
        out.append(l)
    new = "\n".join(out)
    return text if new == body else text[:m.start(1)] + new + text[m.end(1):]


def check_people(notes, flags):
    """Даты и возраст родителей — сверка между карточками."""
    val = lambda f, k: (re.search(rf"^{k}:[ \t]*(.*)$", f, re.M) or [None, ""])[1].strip().strip('"')
    by_id = {val(f, "cr_id"): n for n, f in notes.items()}
    for n, f in notes.items():
        b, d = year(val(f, "born")), year(val(f, "died"))
        if b and d and d < b:
            flags.append(f"D1 {n}: смерть ({d}) раньше рождения ({b})")
        elif b and d and d - b > 110:
            flags.append(f"D1 {n}: прожил(а) {d - b} лет — проверить даты")
        if re.search(r"(вич|вна|ична)\b", n) and not re.search(r"(вич|вна)$", n.split()[-1]):
            flags.append(f"N1 {n}: похоже на отчество в названии карточки")
        for key, top in (("father_id", 70), ("mother_id", 55)):
            p = by_id.get(val(f, key))
            pb = year(val(notes[p], "born")) if p else None
            if b and pb and not 13 <= b - pb <= top:
                who = "отец" if key == "father_id" else "мать"
                flags.append(f"D2 {n}: {who} [[{p}]] {b - pb} лет при рождении — ребёнок привязан к тем?")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix, quiet = "--fix" in sys.argv, "--quiet" in sys.argv
    files = {N(p.stem): p for p in PEOPLE.glob("*.md")}
    notes = {n: N(p.read_text(encoding="utf-8")) for n, p in files.items()}
    only = [N(a).removesuffix(".md").split("/")[-1] for a in args]
    todo = [n for n in only if n in notes] if only else sorted(notes)

    idx, cache = file_index(), load_cache()
    fixes, flags, changed = [], [], 0
    for n in todo:
        text = notes[n]
        new = check_media(n, text, idx, cache, fixes)
        new = check_sources(n, new, fixes)
        new = check_facts(n, new, fixes, flags)
        if new != text and fix:
            files[n].write_text(new, encoding="utf-8")
            notes[n] = new
            changed += 1
    people_flags = []
    check_people(notes, people_flags)
    flags += [x for x in people_flags if x.split(":")[0].split(" ", 1)[1] in todo]

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    live = {k: v for k, v in cache.items() if (paths.ROOT / k.split("|")[0]).exists()}
    CACHE.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")

    if not quiet:
        if fixes:
            print(("Починено:" if fix else "Чинится (запусти с --fix):"))
            print("\n".join("  " + x for x in fixes))
        if flags:
            print("Посмотреть человеку:")
            print("\n".join("  " + x for x in flags))
    verb = "починено" if fix else "чинится"
    print(f"Доктор карточек: карточек {len(todo)}, {verb} {len(fixes)}"
          + (f" (в {changed} карточках)" if fix else "") + f", сигналов посмотреть {len(flags)}")
    return 1 if (fixes and not fix) else 0


if __name__ == "__main__":
    sys.exit(main())
