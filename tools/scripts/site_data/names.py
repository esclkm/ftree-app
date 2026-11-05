"""Имена и названия латиницей, адреса страниц. Общие для HTML-страниц и для JSON (site_data.export).

Где в дереве уже есть латинская форма (Jasieniew, Witold, Kazimierz) — она и остаётся; кириллические слова
переводятся буквами: для польского — по-польски (Wasilij, Szczepan), для остальных — по-английски (Vasiliy).
Привычные названия мест — словарём PLACE_LATIN: полякам «Brześć», а не «Briest».
"""
import json
import os
import re
import unicodedata
from pathlib import Path

import paths

CYR = re.compile("[А-Яа-яЁёІіЎў]")
_EN = dict(zip("абвгдезийклмнопрстуфыэіў", "abvgdeziyklmnoprstufyeiw")) | {
    "ж": "zh", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ь": "", "ё": "yo", "ю": "yu", "я": "ya"}
_PL = dict(zip("абвгдзийклмнопрстуфыэіў", "abwgdzijklmnoprstufyeił")) | {
    "ж": "ż", "х": "ch", "ц": "c", "ч": "cz", "ш": "sz", "щ": "szcz", "ъ": "", "ь": ""}
_SOFT = {"е": "e", "ё": "o", "ю": "u", "я": "a"}  # йотированные: в начале и после гласной — с «й», после согласной — мягко
_VOW = set("аеёиоуыэюяіaeiouy")


def translit(word, lang):
    out, prev = [], ""
    for ch in word:
        low = ch.lower()
        if low in _SOFT:
            if lang == "pl":
                r = ("j" if not prev or prev in _VOW or prev in "ъь" else "i") + _SOFT[low]
            else:
                r = ("y" + _SOFT[low]) if (not prev or prev in _VOW or prev in "ъь") and low != "е" or (low == "е" and (not prev or prev in _VOW)) else _EN.get(low, "e")
        else:
            r = (_PL if lang == "pl" else _EN).get(low, ch)
        out.append(r.capitalize() if ch.isupper() and r else r)
        prev = low
    return "".join(out)


def latin(name, lang):
    return re.sub(r"[А-Яа-яЁёІіЎў]+", lambda m: translit(m.group(), lang), name)


# Привычные названия мест (полякам — «Brześć», а не «Briest») и адреса страниц, уже разосланные родне, — настройки
# дерева в ftree.toml: [places.latin] и [places.slug_keep]. Остальные места — буквами, как выше.
PLACE_LATIN = {ru: tuple(v) for ru, v in paths.CONFIG.get("places", {}).get("latin", {}).items()}  # ru: (pl, en/es)
PLACE_SLUG_KEEP = dict(paths.CONFIG.get("places", {}).get("slug_keep", {}))


def latin_place(name, lang):
    i = 0 if lang == "pl" else 1
    if name in PLACE_LATIN:
        return PLACE_LATIN[name][i]
    for ru, v in sorted(PLACE_LATIN.items(), key=lambda x: -len(x[0])):  # «Брест — кладбище · 38 квадрат» → «Brześć — cmentarz …»
        name = re.sub(rf"(?<![А-Яа-яЁё]){re.escape(ru)}(?![А-Яа-яЁё])", v[i], name)
    return latin(name, lang)


def slugify(s):
    s = unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L"))
    return re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode().lower()).strip("-") or "x"


def person_names(name, aliases):
    """Имя человека на языках сайта. По-русски — кириллицей, если такая форма есть в aliases
    («Ivan Jasieniew» → «Иван Ясенев»); по-польски и по-английски — латиницей (испанский пока = английский)."""
    cyr = [a for a in map(str, aliases) if CYR.search(a) and not re.search("[A-Za-z]", a)]
    ru = cyr[0] if re.search("[A-Za-z]", name) and cyr else name
    return {"ru": ru, "en": latin(name, "en"), "pl": latin(name, "pl")}


def place_names(name):
    """Название места на языках сайта (адрес уже без номера дома — site_data.privacy)."""
    return {"ru": name, "en": latin_place(name, "en"), "pl": latin_place(name, "pl")}


PERSON_SLUGS = paths.PERSON_SLUGS


def person_slugs():
    """Адреса страниц людей, однажды выданные (номер карточки → адрес). Ссылку уже могли отправить родне — поэтому
    адрес не меняется, даже когда меняется имя (26.10.2026: из имён убрали пояснения «(Вербичи, 1908)»).
    Новым людям адрес выдаёт assign_slugs, и сборка дописывает его сюда (remember_slugs)."""
    return json.loads(PERSON_SLUGS.read_text()) if PERSON_SLUGS.exists() else {}


def remember_slugs(slugs):
    """Дописать в person_slugs.json адреса новых людей; выданные не трогаем."""
    old = person_slugs()
    new = {k: v for k, v in slugs.items() if k not in old}
    if new:
        PERSON_SLUGS.parent.mkdir(parents=True, exist_ok=True)   # новое дерево (rodo init): папки tree_data ещё нет
        # проверки в tools/ci.sh идут одновременно и пишут этот файл вместе: через временный файл и замену — иначе
        # соседняя проверка читает его недописанным (так падала check_lifeline на свежем дереве, 05.11.2026)
        tmp = PERSON_SLUGS.with_name(f".{PERSON_SLUGS.name}.{os.getpid()}")
        tmp.write_text(json.dumps(dict(sorted({**old, **new}.items())), ensure_ascii=False, indent=0) + "\n")
        os.replace(tmp, PERSON_SLUGS)


def assign_slugs(items, keep=None):
    """Читаемые адреса страниц: people/ivan-yasenev-1878 — такую ссылку можно отправить. items — (id, имя латиницей,
    год рождения или None). Тёзкам добавляется год, а если и он совпал — начало номера. keep — уже выданные адреса
    {id: slug}: они остаются как есть. → {id: slug}"""
    keep = {k: v for k, v in (keep or {}).items() if k in {i[0] for i in items}}
    seen, out = set(keep.values()), dict(keep)
    for pid, en, born in sorted((i for i in items if i[0] not in keep), key=lambda x: (x[2] or 0, x[0])):
        base = slugify(en)
        slug = base if base not in seen else f"{base}-{born or pid[:3]}"
        while slug in seen:
            slug += "-" + pid[:3]
        seen.add(slug)
        out[pid] = slug
    return out
