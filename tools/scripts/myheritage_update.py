#!/usr/bin/env python3
"""Обновление дерева на MyHeritage из карточек Obsidian — файл GEDCOM и его проверка.

Зачем. Дерево на MyHeritage уже есть (платный тариф), а всё новое мы пишем в карточки
`3_research/tree/`. MyHeritage ищет совпадения (Smart Matches, Record Matches) только по тому, что
лежит в его дереве. Выгрузка GEDCOM дополнения Charted Roots теряет факты, источники у людей, другие
имена и прежние номера MyHeritage — поэтому свой скрипт.

Как. За основу берётся свежая выгрузка дерева с сайта (`1_sources/others_trees/myheritage/*.ged`,
самая новая). Все её строки остаются как были — номера людей и семей (@I25@), RIN, _UID, фото,
ссылки на совпадения. Поверх дописывается то, чего на сайте нет:
  • даты и места рождения и смерти из карточки (карточка главнее; каждая замена — в отчёте);
  • другие имена (`aliases`, имя карточки, если на сайте оно записано иначе) — `NAME … / TYPE aka`;
  • события из `3_research/tree/events/` — жительство, учёба, работа, война, похороны, браки;
  • факты из раздела «Факты (с источником)» — заметкой, одна строка на факт (только у умерших);
  • наши источники с привязкой к людям: страница / минута записи и уверенность (QUAY);
  • люди из карточек, которых на сайте нет, и недостающие связи (родитель, супруг).
Ничего с сайта не удаляется, связи не переписываются — только добавляются.

Слить файл с деревом на сайте можно только через Family Tree Builder (Import GEDCOM → Merge):
загрузка GEDCOM прямо на сайт всегда создаёт второе дерево. Сначала — проба на копии проекта.

Команды:
  python3 tools/scripts/myheritage_update.py build [выгрузка.ged]  # → tree_data/myheritage_update.ged + отчёт
  python3 tools/scripts/myheritage_update.py check                 # четыре ступени проверки файла, код 1 при ошибке
  python3 tools/scripts/myheritage_update.py lint                  # карточки: что потеряется или задвоится на сайте
Файлы результата — сборка, в git не хранятся (.gitignore).
"""
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import dates
import living  # noqa: E402

OUT = paths.TREE_DATA / "myheritage_update.ged"
# Люди, которых уже нет на сайте (двойники удалены руками), а старая выгрузка .ged их ещё помнит: «I25  кто, когда».
DELETED = paths.TREE_DATA / "myheritage_deleted.txt"
REPORT = paths.TREE_DATA / "myheritage_update_report.md"
PEOPLE, EVENTS, SOURCES, PLACES = (paths.TREE / d for d in ("people", "events", "sources", "places"))

NFC = lambda s: unicodedata.normalize("NFC", s)
MAX_LINE = 200          # длина строки GEDCOM с запасом до предела 255; длиннее — перенос CONC
QUAY = {"очень высокая": 3, "высокая": 3, "обычная": 2, "средняя": 2, "низкая": 1, "очень низкая": 0}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
EVENT_TAG = {"residence": "RESI", "education": "EDUC", "occupation": "OCCU", "burial": "BURI"}
EVENT_SKIP = {"birth", "death", "marriage", "divorce", "custom"}   # рождение/смерть — из карточки,
# браки — в семьи, custom — служебные заметки из старой выгрузки MyHeritage («15 APR 2024 01:56:38»)
FACT_SECTIONS = ("### Факты (с источником)", "### Заметки (из дерева MyHeritage и записей проекта)")


# ─── GEDCOM: чтение и запись ────────────────────────────────────────────────────────────────

def read_ged(path):
    """Логические строки файла. MyHeritage переносит длинные строки (CONC) посреди русской буквы —
    склеиваем байты до разбора, иначе файл не читается как UTF-8."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    raw = re.sub(rb"[\r\n]+\d+ CONC ", b"", raw)
    out = []
    for l in re.split(r"[\r\n]+", raw.decode("utf-8")):
        if not l.strip():
            continue
        if re.match(r"\d+ ", l) or not out:
            out.append(l)
        else:   # перенос строки внутри заметки MyHeritage пишет без уровня — это продолжение (CONT)
            lvl = int(out[-1].split(" ", 1)[0])
            lvl = lvl if out[-1].split(" ")[1] == "CONT" else lvl + 1
            out.append(f"{lvl} CONT {l.strip()}")
    return out


def records(lines):
    """[(xref или None, тип, [строки])] в порядке файла; первая строка записи — «0 …»."""
    out = []
    for l in lines:
        if l.startswith("0 "):
            m = re.match(r"0 @([^@]+)@ (\w+)", l)
            out.append((m.group(1), m.group(2), [l]) if m else (None, l[2:].split()[0], [l]))
        elif out:
            out[-1][2].append(l)
    return out


def blocks(rec_lines):
    """Строки записи → [первая строка, [[блок уровня 1], …]]."""
    head, bl = rec_lines[0], []
    for l in rec_lines[1:]:
        if l.startswith("1 ") or not bl:
            bl.append([l])
        else:
            bl[-1].append(l)
    return head, bl


def wrap(line):
    """Строка длиннее MAX_LINE → строка + продолжения «N+1 CONC …». Разрез — не на пробеле:
    CONC склеивает части без пробела, а пробел на краю строки многие программы съедают."""
    if len(line) <= MAX_LINE:
        return [line]
    lvl, tag = line.split(" ", 2)[:2]
    lvl = int(lvl) if tag in ("CONT", "CONC") else int(lvl) + 1   # продолжение продолжения — тот же уровень
    out, rest = [], line
    while len(rest) > MAX_LINE:
        cut = MAX_LINE
        while cut > MAX_LINE - 40 and (rest[cut - 1] == " " or rest[cut] == " "):
            cut -= 1
        out.append(rest[:cut])
        rest = f"{lvl} CONC " + rest[cut:]
    out.append(rest)
    return out


def write_ged(path, lines):
    body = []
    for l in lines:
        body += wrap(l)
    path.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(body) + "\r\n").encode("utf-8"))


def text_lines(level, tag, text):
    """Многострочный текст → «level TAG первая строка» + «level+1 CONT …»."""
    parts = text.split("\n")
    return [f"{level} {tag} {parts[0]}".rstrip()] + [f"{level + 1} CONT {p}".rstrip() for p in parts[1:]]


# ─── Даты ───────────────────────────────────────────────────────────────────────────────────

def ged_date(v):
    """Дата карточки → GEDCOM: «1971-03-05» → «5 MAR 1971», «ABT 1935», «BET 2005 AND 2006» (tools/scripts/dates.py).
    Не по правилу — None (check_dates.py такое в карточке не пропускает)."""
    g = dates.card_or_none(v)
    return g.gedcom() if g else None


def date_core(g):
    """Дата без «около / до / после» — чтобы «ABT FEB 1986» на сайте и «FEB 1986» в карточке
    считались одной датой, а не расхождением."""
    return re.sub(r"^(ABT|EST|CAL|BEF|AFT)\s+", "", (g or "").strip().upper())


GED_DATE = re.compile(r"((ABT|EST|CAL|BEF|AFT|INT) )?((\d{1,2} )?(%s) )?\d{3,4}(/\d\d)?"
                      r"|BET .+ AND .+|FROM .+( TO .+)?|TO .+|\(.*\)|Y" % "|".join(MONTHS))


# ─── Карточки ───────────────────────────────────────────────────────────────────────────────

def read_note(p):
    t = p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n?(.*)", t, re.S)
    if not m:
        return {}, t
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return {}, m.group(2)


def as_list(v):
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def link_target(v):
    """«[[Имя|подпись]]» → «Имя» (без пути и .md)."""
    m = re.match(r"\[\[([^\]|#]+)", str(v or "").strip())
    return NFC(m.group(1).split("/")[-1].removesuffix(".md")) if m else None


def plain(md):
    """Строка Markdown → простой текст для MyHeritage: без ** и *, ссылки — их подписью."""
    def link(m):
        target, _, label = m.group(1).partition("|")
        if label and not label.startswith("@I"):
            return label
        return target.split("#")[0].split("/")[-1].removesuffix(".md")
    s = re.sub(r"\[\[([^\]]+)\]\]", link, md)
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def section_lines(body, header):
    """Строки «- …» раздела ### header (до следующего заголовка)."""
    i = body.find(header + "\n")
    if i < 0:
        return []
    chunk = body[i + len(header):]
    m = re.search(r"^#{1,3} ", chunk, re.M)
    chunk = chunk[:m.start()] if m else chunk
    return [l[2:].strip() for l in chunk.splitlines() if l.startswith("- ")]


def split_name(name):
    """«Прокоп Ясенев (1852)» → («Прокоп», «Ясенев»). Пояснение в скобках — не часть имени."""
    name = re.sub(r"\s*\(.*?\)\s*", " ", str(name or "")).strip()
    if not name or name.startswith("Unknown"):
        return None
    parts = name.split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (parts[0], "")


class Tree:
    def __init__(self):
        self.people = {}      # stem → {fm, body}
        self.by_cr = {}       # cr_id → stem
        for p in sorted(PEOPLE.glob("*.md")):
            fm, body = read_note(p)
            if fm.get("cr_type") == "person":
                stem = NFC(p.stem)
                self.people[stem] = {"fm": fm, "body": body}
                self.by_cr[fm.get("cr_id")] = stem
        self.places = {}
        for p in PLACES.rglob("*.md"):
            fm, _ = read_note(p)
            if fm.get("cr_type") == "place":
                self.places[NFC(p.stem)] = fm
        self.sources = {}
        for p in SOURCES.rglob("*.md"):           # с подпапками (press/ — газеты и тексты семьи), как на сайте
            fm, _ = read_note(p)
            if fm.get("cr_type") == "source":
                self.sources[NFC(p.stem)] = fm
        self.events = defaultdict(list)   # stem человека → [fm события]
        for p in sorted(EVENTS.glob("*.md")):
            fm, _ = read_note(p)
            if fm.get("cr_type") != "event":
                continue
            names = {link_target(x) for x in as_list(fm.get("persons")) + as_list(fm.get("person"))}
            fm["_persons"] = sorted(n for n in names if n in self.people)
            for n in fm["_persons"]:
                self.events[n].append(fm)

    def gid(self, stem):
        return str(self.people[stem]["fm"].get("gedcom_id") or "") or None

    def place_chain(self, stem):
        """Место → «Вербичи, Беларусь» (от мелкого к крупному, по parent_place)."""
        chain, seen = [], set()
        while stem and stem not in seen and stem in self.places:
            seen.add(stem)
            chain.append(self.places[stem].get("name") or stem)
            stem = link_target(self.places[stem].get("parent_place"))
        return ", ".join(chain) if chain else None

    def place_names(self, stem):
        fm = self.places.get(stem) or {}
        return {norm(stem), norm(fm.get("name") or "")} | {norm(a) for a in as_list(fm.get("aliases"))}

    def city_of(self, stem):
        """Кладбище, дом, улица — не место смерти: для DEAT берём город, в котором они стоят."""
        fm = self.places.get(stem) or {}
        if fm.get("place_type") in ("cemetery", "house", "street", "hospital", "church", "school"):
            return link_target(fm.get("parent_place")) or stem
        return stem

    def place_lines(self, level, stem):
        text = self.place_chain(stem) or stem
        out = [f"{level} PLAC {text}"]
        c = (self.places.get(stem) or {}).get("coordinates") or {}
        if isinstance(c, dict) and c.get("lat") is not None and c.get("long") is not None:
            lat, lon = float(c["lat"]), float(c["long"])
            out += [f"{level + 1} MAP", f"{level + 2} LATI {'N' if lat >= 0 else 'S'}{abs(lat):.4f}",
                    f"{level + 2} LONG {'E' if lon >= 0 else 'W'}{abs(lon):.4f}"]
        return out

    def is_living(self, stem):
        """Живой — общее правило (living.py): нет смерти и родился не раньше 110 лет назад, или год неизвестен. Факты
        живых на сайт не отправляем: MyHeritage показывает их тем, кто нашёл совпадение."""
        fm = self.people[stem]["fm"]
        return living.is_living(fm.get("born"), fm.get("died"), unknown=True)  # «ABT 1900» — тоже 1900


def norm(s):
    return NFC(str(s)).lower().replace("ё", "е").strip()


def same_place(site, names):
    """Место на сайте то же, что в карточке: название карточки (или его прежнее написание) есть
    в строке сайта — «д. Вербичи, Лесогорской области» = «Вербичи». Тогда строку сайта не трогаем:
    она часто подробнее нашей."""
    s = norm(site)
    names = {re.sub(r"\s*\(.*?\)", "", n).strip() for n in names if n}
    return any(n and re.search(r"(^|[\s,.])" + re.escape(n) + r"($|[\s,.])", s) for n in names)


def keep_site_date(site, card):
    """Причина оставить дату сайта (или None — заменить карточкой).
    • та же дата («ABT FEB 1986» и «FEB 1986»);
    • разница 12–13 дней — это старый и новый стиль одной даты, не расхождение;
    • в карточке только год, а на сайте полная дата того же года — сайт точнее."""
    a, b = date_core(site), date_core(card)
    if a == b:
        return "та же"
    da, db = full_date(a), full_date(b)
    if da and db and abs((da - db).days) in (12, 13):
        return "старый/новый стиль (12–13 дней)"
    if re.fullmatch(r"\d{4}", b) and re.search(r"\b" + b + r"$", a) and not a.startswith(("BET", "FROM", "TO")):
        return "на сайте точнее, год тот же"
    return None


def full_date(g):
    m = re.fullmatch(r"(\d{1,2}) (%s) (\d{4})" % "|".join(MONTHS), g)
    return date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1))) if m else None


# ─── Сборка ────────────────────────────────────────────────────────────────────────────────

# сайт нашего дерева на MyHeritage («1 _EXPORTED_FROM_SITE_ID …» в выгрузке; ftree.toml, [myheritage] export_site);
# выгрузки других страниц MyHeritage — не наши. Не задан — дерево с MyHeritage не связано (новое, rodo init)
OUR_SITE = str(paths.setting("FTREE_MYHERITAGE_EXPORT_SITE", "", toml="myheritage.export_site"))
# наше дерево на MyHeritage в карточках и в .ged — ftree.toml [myheritage.ours]
SOURCE_CARD = paths.tree_conf("myheritage.ours.source_card", "")     # карточка-источник: его факты обратно не шлём
NOTE_ORIGIN = paths.tree_conf("myheritage.ours.note_origin", "") or paths.tree_conf("tree.title", "ftree")
FACTS_NOTE = paths.tree_conf("myheritage.ours.facts_note", "Факты из семейного архива")


def site_of(path):
    """Номер сайта MyHeritage, с которого выгрузка (строка «1 _EXPORTED_FROM_SITE_ID …» в начале файла)."""
    with open(path, "rb") as f:
        m = re.search(rb"_EXPORTED_FROM_SITE_ID (\d+)", f.read(4000))
    return m.group(1).decode() if m else None


def latest_export():
    """Самая свежая выгрузка НАШЕГО сайта: в папке могут лежать и выгрузки чужих страниц MyHeritage."""
    files = sorted((p for p in paths.MYHERITAGE.glob("*.ged") if site_of(p) == OUR_SITE), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit(f"нет выгрузки сайта {OUR_SITE} ({SOURCE_CARD or 'наше дерево'}) в {paths.MYHERITAGE}")
    return files[-1]


def build(src):
    T = Tree()
    recs = records(read_ged(src))
    rep = defaultdict(list)
    today = date.today()

    indi = {x: r for x, t, r in recs if t == "INDI"}
    fams = {x: r for x, t, r in recs if t == "FAM"}
    mh_sources = {x: r for x, t, r in recs if t == "SOUR"}

    def famv(fid, tag):
        return [l.split("@")[1] for l in fams[fid] if l.startswith(f"1 {tag} @")]

    # ── источники: наши заметки → SOUR @S9xxxxx@ (кроме чужих деревьев — они уже на сайте)
    mh_titles = {norm(l[7:]) for r in mh_sources.values() for l in r if l.startswith("1 TITL ")}
    src_id, new_sources = {}, []
    for i, (stem, fm) in enumerate(sorted(T.sources.items()), 1):
        title = str(fm.get("title") or stem)
        if fm.get("origin") == "чужое дерево" or norm(title) in mh_titles:
            continue
        sid = f"S9{i:05d}"
        src_id[stem] = sid
        r = [f"0 @{sid}@ SOUR", f"1 TITL {plain(title)}"]
        if fm.get("repository"):
            r.append(f"1 AUTH {plain(str(fm['repository']))}")
        r.append(f"1 NOTE Происхождение: {fm.get('origin') or 'не указано'} ({NOTE_ORIGIN})")
        new_sources.append(r)

    # ── люди с сайта: дописать недостающее
    gid_stem = {}
    for stem in T.people:
        g = T.gid(stem)
        if g:
            gid_stem.setdefault(g, stem)
    changed = {}
    for gid, rec in indi.items():
        stem = gid_stem.get(gid)
        if not stem:
            rep["На сайте, но нет карточки (перенести в Obsidian)"].append(f"@{gid}@ {name_of(rec)}")
            continue
        changed[gid] = update_person(T, stem, rec, src_id, rep)

    # ── новые люди (карточка есть, на сайте нет)
    new_people = {}
    for stem, p in T.people.items():
        g = T.gid(stem)
        if g and g in indi:
            continue
        g = g if g and g not in indi else f"I8{len(new_people) + 1:05d}"
        gid_stem[g] = stem
        new_people[g] = update_person(T, stem, [f"0 @{g}@ INDI"], src_id, rep, new=True)
        rep["Новые люди (карточка есть, на сайте нет)"].append(f"@{g}@ {stem}")
    stem_gid = {s: g for g, s in gid_stem.items()}
    allindi = {**changed, **new_people}

    # ── связи: добавить недостающие (ничего не убираем)
    famc = defaultdict(set)
    for fid, r in fams.items():
        for c in famv(fid, "CHIL"):
            famc[c].add(fid)
    new_fams, fam_lines = {}, {fid: list(r) for fid, r in fams.items()}

    def partners(fid):
        h = [l.split("@")[1] for l in fam_lines[fid] if l.startswith("1 HUSB @")]
        w = [l.split("@")[1] for l in fam_lines[fid] if l.startswith("1 WIFE @")]
        return (h[0] if h else None), (w[0] if w else None)

    def find_fam(a, b):
        """Семья пары — без учёта, кто записан мужем: на сайте у двух семей роли перепутаны."""
        want = {a, b} - {None}
        return next((fid for fid in fam_lines if set(partners(fid)) - {None} == want
                     and (None in partners(fid)) == (None in (a, b))), None)

    def add_fam(h, w):
        fid = f"F8{len(new_fams) + 1:05d}"
        r = [f"0 @{fid}@ FAM"] + ([f"1 HUSB @{h}@"] if h else []) + ([f"1 WIFE @{w}@"] if w else [])
        new_fams[fid] = r
        fam_lines[fid] = r
        for g in (h, w):
            if g:
                allindi[g].append(f"1 FAMS @{fid}@")
        return fid

    def role(g):
        return "WIFE" if T.people[gid_stem[g]]["fm"].get("sex") == "female" else "HUSB"

    # родители: сначала все дети, потом супруги — иначе пара «отец + новая мать» появилась бы
    # отдельной семьёй, а дети остались бы в семье отца без матери
    for stem, p in T.people.items():
        g = stem_gid.get(stem)
        if not g:
            continue
        fa = stem_gid.get(T.by_cr.get(p["fm"].get("father_id")))
        mo = stem_gid.get(T.by_cr.get(p["fm"].get("mother_id")))
        if not (fa or mo):
            continue
        fid = find_fam(fa, mo)
        if fid and fid in famc[g]:
            continue
        if famc[g]:
            # на сайте семья из одного родителя, а в карточке известен второй — дописать его туда же
            one = next((f for f in famc[g] if None in partners(f) and set(partners(f)) - {None} <= {fa, mo}), None)
            if one and fa and mo:
                other = mo if fa in partners(one) else fa
                fam_lines[one].insert(1, f"1 {role(other)} @{other}@")
                allindi[other].append(f"1 FAMS @{one}@")
                rep["Второй родитель дописан в семью с сайта"].append(f"{one}: + @{other}@ ({stem})")
                continue
            rep["Родители на сайте другие, чем в карточке (не трогали — проверить)"].append(
                f"@{g}@ {stem}: на сайте в семье {'; '.join(sorted(famc[g]))} "
                f"({' + '.join(x or '—' for f in sorted(famc[g]) for x in partners(f))}), "
                f"в карточке отец {fa or '—'}, мать {mo or '—'}")
            continue
        fid = fid or add_fam(fa, mo)
        fam_lines[fid].append(f"1 CHIL @{g}@")
        famc[g].add(fid)
        allindi[g].append(f"1 FAMC @{fid}@")
        rep["Добавлена связь с родителями"].append(f"@{g}@ {stem} → {fid}")

    for stem, p in T.people.items():
        g = stem_gid.get(stem)
        for sp in as_list(p["fm"].get("spouse_id")) if g else []:
            s2 = stem_gid.get(T.by_cr.get(sp))
            if s2 and not find_fam(g, s2):
                h, w = (g, s2) if role(g) == "HUSB" else (s2, g)
                add_fam(h, w)
                rep["Добавлена пара (супруги)"].append(f"@{h}@ + @{w}@ ({stem})")

    # ── браки из событий → MARR в семью пары, если на сайте его нет
    for stem, evs in T.events.items():
        for ev in evs:
            if ev.get("event_type") != "marriage" or len(ev["_persons"]) != 2:
                continue
            a, b = (stem_gid.get(x) for x in ev["_persons"])
            if not a or not b or stem != ev["_persons"][0]:
                continue
            fid = find_fam(a, b)
            d, pl = ged_date(ev.get("date")), link_target(ev.get("place"))
            if not fid or not (d or pl) or any(l.startswith("1 MARR") for l in fam_lines[fid]):
                continue
            fam_lines[fid] += ["1 MARR"] + ([f"2 DATE {d}"] if d else []) + (T.place_lines(2, pl) if pl else [])
            rep["Добавлен брак (дата/место)"].append(f"{fid}: {' + '.join(ev['_persons'])} {d or ''}")

    # ── сборка файла: шапка, люди, семьи, источники с сайта, наши источники, конец
    out = []
    for x, t, r in recs:
        if t == "HEAD":
            out += [l if not l.startswith("1 DATE ") else f"1 DATE {today.day} {MONTHS[today.month - 1]} {today.year}"
                    for l in r if not l.startswith("1 FILE ")]
            out.append("1 FILE myheritage_update.ged")
        elif t == "INDI":
            out += allindi.get(x, r)
        elif t == "FAM":
            out += fam_lines[x]
        elif t == "TRLR":
            continue
        else:
            out += r
    for g, r in new_people.items():
        out += r
    for r in new_fams.values():
        out += r
    for r in new_sources:
        out += r
    out.append("0 TRLR")
    write_ged(OUT, out)
    write_report(src, rep, out)
    print(f"готово: {OUT.relative_to(paths.ROOT)} ({len(out)} строк); отчёт — {REPORT.relative_to(paths.ROOT)}")


def name_of(rec):
    for l in rec:
        if l.startswith("1 NAME "):
            return l[7:].replace("/", "").strip()
    return "?"


def update_person(T, stem, rec, src_id, rep, new=False):
    """Запись человека: всё с сайта + недостающее из карточки."""
    fm, body = T.people[stem]["fm"], T.people[stem]["body"]
    head, bl = blocks(rec)
    label = f"@{head.split('@')[1]}@ {stem}"

    def find(tag):
        return next((b for b in bl if b[0].split()[1] == tag), None)

    # имя
    main = split_name(fm.get("name") or stem)
    if new:
        if main:
            bl.append([f"1 NAME {main[0]} /{main[1]}/", f"2 GIVN {main[0]}"] + ([f"2 SURN {main[1]}"] if main[1] else []))
        else:
            bl.append(["1 NAME //"])
        sex = {"male": "M", "female": "F"}.get(str(fm.get("sex") or "").lower(), "U")
        bl.append([f"1 SEX {sex}"])
    have_plain = {norm(" ".join(l[7:].replace("/", " ").split())) for b in bl for l in b if l.startswith("1 NAME ")}
    alts = [] if fm.get("surname_inferred") else [fm.get("name") or stem]
    alts += as_list(fm.get("aliases"))
    for a in alts:
        parts = split_name(a)
        if not parts:
            continue
        if not parts[1]:        # одно слово в aliases — это фамилия («Jasieniew»), имя — из карточки
            if not main or not main[1] or parts[0] == main[0]:
                continue
            parts = (main[0], parts[0])
        if norm(f"{parts[0]} {parts[1]}") in have_plain:
            continue
        have_plain.add(norm(f"{parts[0]} {parts[1]}"))
        bl.append([f"1 NAME {parts[0]} /{parts[1]}/", "2 TYPE aka"])
        rep["Добавлено другое имя"].append(f"{label}: {parts[0]} {parts[1]}")

    # рождение и смерть
    for tag, dkey, pkey in (("BIRT", "born", "birth_place"), ("DEAT", "died", "death_place")):
        d, pl = ged_date(fm.get(dkey)), link_target(fm.get(pkey))
        pl = T.city_of(pl) if pl else pl
        if not d and not pl:
            continue
        b = find(tag)
        if b is None:
            b = [f"1 {tag}"]
            bl.append(b)
            if not new:
                rep[f"Добавлено: {tag}"].append(f"{label}: {d or ''} {T.place_chain(pl) or pl or ''}".strip())
        if b[0].strip() == f"1 {tag} Y" and d:
            b[0] = f"1 {tag}"
        if d:
            old = next((i for i, l in enumerate(b) if l.startswith("2 DATE ")), None)
            if old is None:
                b.insert(1, f"2 DATE {d}")
            else:
                why = keep_site_date(b[old][7:], d)
                if why:
                    if why != "та же":
                        rep[f"Дата с сайта оставлена: {why}"].append(f"{label} {tag}: сайт «{b[old][7:]}», карточка «{d}»")
                else:
                    rep["Дата заменена данными карточки"].append(f"{label} {tag}: было «{b[old][7:]}» → «{d}»")
                    b[old] = f"2 DATE {d}"
        if pl:
            i = next((i for i, l in enumerate(b) if l.startswith("2 PLAC ")), None)
            if i is None:
                b += T.place_lines(2, pl)
            else:
                if not same_place(b[i][7:], T.place_names(pl)):
                    j = i + 1
                    while j < len(b) and int(b[j][0]) > 2:
                        j += 1
                    rep["Место заменено данными карточки"].append(
                        f"{label} {tag}: было «{b[i][7:]}» → «{T.place_chain(pl) or pl}»")
                    b[i:j] = T.place_lines(2, pl)
        if len(b) == 1 and not b[0].endswith(" Y"):
            b[0] += " Y"

    # события
    for ev in T.events.get(stem, []):
        et = ev.get("event_type")
        if et in EVENT_SKIP:
            continue
        d, pl = ged_date(ev.get("date")), link_target(ev.get("place"))
        title = plain(str(ev.get("title") or et))
        if not d and not pl:
            continue
        tag = EVENT_TAG.get(et, "EVEN")
        if any(b[0].split()[1] == tag and any(l == f"2 DATE {d}" for l in b) for b in bl) and d:
            continue
        head_line = f"1 {tag} {title}" if tag in ("OCCU", "EDUC") else f"1 {tag}"
        e = [head_line]
        if tag == "EVEN":
            e.append(f"2 TYPE {title}")
        if d:
            e.append(f"2 DATE {d}")
        if pl:
            e += T.place_lines(2, pl)
        desc = plain(str(ev.get("description") or ""))
        if desc and desc != title:
            e += text_lines(2, "NOTE", desc)
        bl.append(e)
        rep["Добавлено событие"].append(f"{label}: {tag} {title} {d or ''}".strip())

    # факты заметкой — только умершие
    mh_notes = " ".join(norm(l) for b in bl for l in b if " NOTE " in l or " CONT " in l)
    facts = []
    for sec in FACT_SECTIONS:
        for f in section_lines(body, sec):
            if SOURCE_CARD and re.search(rf"— \*источник: \[\[{re.escape(SOURCE_CARD)}\]\][^\[]*$", f):
                continue   # факт взят из самого дерева на MyHeritage (card_standard.py years) — обратно не шлём
            t = plain(f)
            core = norm(re.sub(r"\s+—\s+источник:.*$", "", t))
            core = re.sub(r"^заметка:\s*", "", core)
            if core and core not in mh_notes:
                facts.append(t)
    if facts:
        if T.is_living(stem):
            rep["Факты не отправлены — человек, возможно, жив"].append(f"{label}: {len(facts)} строк")
        else:
            txt = (f"{FACTS_NOTE} (обновлено {date.today():%d.%m.%Y}). "
                   "В конце каждой строки — источник и уверенность.\n" + "\n".join("• " + f for f in facts))
            bl.append(text_lines(1, "NOTE", txt))
            rep["Добавлены факты заметкой"].append(f"{label}: {len(facts)} строк")

    # источники человека: раздел «## Источники» — «- [[Источник]] — где · уверенность: … · происхождение: …»
    seen = set()
    for l in section_lines(body.replace("\n## Источники\n", "\n### __src\n"), "### __src"):
        s = link_target(l)
        if s not in src_id:
            continue
        rest = l.split("]]", 1)[1].lstrip(" —")
        parts = [x.strip() for x in rest.split("·")]
        page = next((x for x in parts if x and not x.startswith(("уверенность", "происхождение"))), "")
        conf = next((x.split(":", 1)[1].strip() for x in parts if x.startswith("уверенность")), "")
        key = (s, page)
        if key in seen:
            continue
        seen.add(key)
        c = [f"1 SOUR @{src_id[s]}@"] + ([f"2 PAGE {plain(page)}"] if page else [])
        if conf in QUAY:
            c.append(f"2 QUAY {QUAY[conf]}")
        bl.append(c)
    if seen:
        rep["Добавлены источники"].append(f"{label}: {len(seen)}")

    return [head] + [l for b in bl for l in b]


def write_report(src, rep, out):
    L = [f"# Обновление дерева MyHeritage — отчёт сборки ({date.today():%d.%m.%Y})", "",
         f"Основа: `{Path(src).relative_to(paths.ROOT)}`. Результат: `{OUT.relative_to(paths.ROOT)}`, "
         f"{len(out)} строк.", "", "| Что | Сколько |", "|---|---|"]
    L += [f"| {k} | {len(v)} |" for k, v in rep.items()]
    for k, v in rep.items():
        L += ["", f"## {k} ({len(v)})", ""] + [f"- {x}" for x in v]
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")


# ─── Проверка ──────────────────────────────────────────────────────────────────────────────

def check(src):
    errors, warns = [], []
    raw = OUT.read_bytes()

    # 1. формат
    if not raw.startswith(b"\xef\xbb\xbf"):
        warns.append("нет BOM в начале (MyHeritage пишет с ним)")
    try:
        text = raw.lstrip(b"\xef\xbb\xbf").decode("utf-8")
    except UnicodeDecodeError as e:
        errors.append(f"не UTF-8: {e}")
        text = raw.decode("utf-8", "replace")
    phys = text.split("\r\n")
    if phys and phys[-1] == "":
        phys.pop()
    prev, ids, ptrs = -1, Counter(), []
    for n, l in enumerate(phys, 1):
        m = re.match(r"^(\d+) (@[^@\s]+@ )?([A-Z_][A-Z0-9_]*)( (.*))?$", l)
        if not m:
            errors.append(f"строка {n}: не по формату «уровень метка значение»: {l[:80]!r}")
            continue
        lvl = int(m.group(1))
        if lvl > prev + 1:
            errors.append(f"строка {n}: уровень {lvl} после {prev} — пропуск уровня")
        prev = lvl
        if len(l) > 255:
            errors.append(f"строка {n}: длиннее 255 знаков ({len(l)})")
        if m.group(2):
            if lvl != 0:
                errors.append(f"строка {n}: номер записи не на уровне 0")
            ids[m.group(2).strip()] += 1
        val = m.group(5) or ""
        if re.fullmatch(r"@[^@\s]+@", val):
            ptrs.append((n, val))
        if m.group(3) == "DATE" and not GED_DATE.fullmatch(val.strip()) and lvl == 2:
            errors.append(f"строка {n}: дата не по формату GEDCOM: {val!r}")
        if m.group(3) in ("CONC", "CONT") and n > 1:
            pm = re.match(r"(\d+) (?:@[^@]+@ )?(\w+)", phys[n - 2])
            want = int(pm.group(1)) if pm and pm.group(2) in ("CONC", "CONT") else (int(pm.group(1)) + 1 if pm else -1)
            if lvl != want:
                errors.append(f"строка {n}: продолжение на уровне {lvl}, а нужно {want}")
    if not phys or not phys[0].startswith("0 HEAD"):
        errors.append("файл не начинается с 0 HEAD")
    if phys[-1] != "0 TRLR":
        errors.append("файл не кончается 0 TRLR")
    errors += [f"номер {i} встречается {c} раз" for i, c in ids.items() if c > 1]
    site_dangling = {p for p in re.findall(r"@[^@\s]+@", " ".join(read_ged(src)))} - {
        f"@{x}@" for x, _, _ in records(read_ged(src)) if x}
    for n, p in ptrs:
        if p in ids:
            continue
        if p in site_dangling:   # так было в выгрузке с сайта (альбомы фото MyHeritage не выгружает)
            warns.append(f"строка {n}: ссылка {p} — нет и в выгрузке с сайта, оставлена как была")
        else:
            errors.append(f"строка {n}: ссылка на несуществующую запись {p}")
    print(f"1. Формат: {len(phys)} строк, записей {len(ids)}, ссылок {len(ptrs)}")

    # 2. обратное чтение: файл против карточек
    T = Tree()
    new = {x: r for x, t, r in records(read_ged(OUT))}
    kids = defaultdict(set)
    fam = {}
    for x, r in new.items():
        if r[0].endswith(" FAM"):
            h = [l.split("@")[1] for l in r if l.startswith("1 HUSB @")]
            w = [l.split("@")[1] for l in r if l.startswith("1 WIFE @")]
            fam[x] = (h[0] if h else None, w[0] if w else None)
            for l in r:
                if l.startswith("1 CHIL @"):
                    kids[l.split("@")[1]].add(x)
    stem_gid = {}
    for stem in T.people:
        g = T.gid(stem)
        if g in new:
            stem_gid[stem] = g
    for x, r in new.items():
        if r[0].endswith(" INDI") and not any(x == g for g in stem_gid.values()):
            m = [l for l in r if l.startswith("1 NAME ")]
            nm = m[0][7:].replace("/", "").strip() if m else ""
            hit = next((s for s in T.people if s not in stem_gid and split_name(s)
                        and norm(" ".join(split_name(s))) == norm(" ".join(nm.split()))), None)
            if hit:
                stem_gid[hit] = x
    missing = [s for s in T.people if s not in stem_gid]
    errors += [f"человек из карточки не попал в файл: {s}" for s in missing]
    bad_par, bad_date = 0, 0
    for stem, g in stem_gid.items():
        fm, rec = T.people[stem]["fm"], new[g]
        fa = stem_gid.get(T.by_cr.get(fm.get("father_id")))
        mo = stem_gid.get(T.by_cr.get(fm.get("mother_id")))
        if (fa or mo) and not any(set(fam[f]) - {None} == {fa, mo} - {None} for f in kids[g]):
            bad_par += 1
            warns.append(f"родители не совпали с карточкой: {stem} (@{g}@) — см. отчёт сборки")
        _, bl = blocks(rec)
        for tag, key in (("BIRT", "born"), ("DEAT", "died")):
            d = ged_date(fm.get(key))
            if not d:
                continue
            got = [l[7:] for b in bl if b[0].split()[1] == tag for l in b if l.startswith("2 DATE ")]
            if not any(keep_site_date(x, d) for x in got):   # та же дата, другой стиль или сайт точнее
                bad_date += 1
                errors.append(f"{stem}: {tag} в файле {got or '—'}, в карточке {d}")
    print(f"2. Карточки: {len(T.people)} человек, в файле найдено {len(stem_gid)}; "
          f"родители не совпали — {bad_par}, даты не совпали — {bad_date}")

    # 3. ничего с сайта не потеряно
    mh = {x: r for x, t, r in records(read_ged(src)) if x}
    lost_rec = [x for x in mh if x not in new]
    errors += [f"запись с сайта пропала: @{x}@" for x in lost_rec]
    lost_lines = 0
    for x, r in mh.items():
        if x not in new:
            continue
        have = Counter(new[x])
        cur1 = ""
        for l in r[1:]:
            if l.startswith("1 "):
                cur1 = l
            if have[l] > 0:
                have[l] -= 1
                continue
            replaced = cur1.split()[1] in ("BIRT", "DEAT") and l[:1] in "234" and (
                l.startswith(("2 DATE ", "2 PLAC ")) or l[:1] in "34") or l in ("1 BIRT Y", "1 DEAT Y")
            if not replaced:
                lost_lines += 1
                errors.append(f"@{x}@: строка с сайта пропала: {l[:100]}")
    print(f"3. Сайт: записей {len(mh)}, все на месте — {'да' if not lost_rec else 'НЕТ'}; "
          f"пропавших строк (кроме заменённых дат и мест) — {lost_lines}")

    # 4. чужой разборщик: библиотека ged4py (строгая к структуре). Она в .venv проекта (`uv sync`):
    #    tools/py tools/scripts/myheritage_update.py check
    try:
        from ged4py.parser import GedcomReader
        with GedcomReader(str(OUT), encoding="utf-8-sig") as p:
            n4 = Counter(r.tag for r in p.records0())
        print(f"4. ged4py: прочитал — людей {n4['INDI']}, семей {n4['FAM']}, источников {n4['SOUR']}")
        if n4["INDI"] != sum(1 for r in new.values() if r[0].endswith(" INDI")):
            errors.append("ged4py насчитал другое число людей")
    except ImportError:
        warns.append("4-я ступень пропущена: нет ged4py (см. комментарий в check)")
    except Exception as e:  # noqa: BLE001 — любая ошибка разбора = файл битый
        errors.append(f"ged4py не прочитал файл: {e}")

    for w in warns[:30]:
        print("   ! " + w)
    if len(warns) > 30:
        print(f"   ! … и ещё {len(warns) - 30}")
    for e in errors[:50]:
        print("   ✗ " + e)
    if len(errors) > 50:
        print(f"   ✗ … и ещё {len(errors) - 50}")
    print("ИТОГ: " + ("ошибок нет" if not errors else f"ошибок {len(errors)}") + f", предупреждений {len(warns)}")
    return 1 if errors else 0


# ─── Валидатор карточек ────────────────────────────────────────────────────────────────────
# `check` проверяет готовый файл. `lint` — сами карточки: то, что при выгрузке молча пропадёт или
# на сайте превратится в двойника. Главная опасность — новые люди и ветки: MyHeritage при слиянии
# даёт им свои номера, и если не вписать номер в `gedcom_id` карточки, следующая выгрузка привезёт
# того же человека второй раз.

def lint(src, quiet=False):
    T = Tree()
    gone = {l.split()[0] for l in DELETED.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")} \
        if DELETED.exists() else set()
    mh = {x: r for x, t, r in records(read_ged(src)) if t == "INDI" and x not in gone}
    err, warn, info = [], [], defaultdict(list)

    # номера
    by_gid = defaultdict(list)
    for stem in T.people:
        g = T.gid(stem)
        if g:
            by_gid[g].append(stem)
            if not re.fullmatch(r"I\d+", g):
                err.append(f"{stem}: gedcom_id «{g}» — не номер вида I25")
    err += [f"gedcom_id {g} у нескольких карточек: {', '.join(v)}" for g, v in by_gid.items() if len(v) > 1]

    # двойник: карточки нет на сайте под её номером, но на сайте есть человек с тем же именем и годом
    linked = {g for g in by_gid if g in mh}
    free = {x: r for x, r in mh.items() if x not in linked}
    def key(name, born):
        parts = split_name(name)
        return (norm(" ".join(parts)), born[:4]) if parts else None
    free_keys = defaultdict(list)
    for x, r in free.items():
        nm = next((l[7:].replace("/", " ") for l in r if l.startswith("1 NAME ")), "")
        _, bl = blocks(r)
        by = next((re.search(r"\d{4}", l).group(0) for b in bl if b[0].startswith("1 BIRT")
                   for l in b if l.startswith("2 DATE ") and re.search(r"\d{4}", l)), "")
        for n in [nm] + [l[7:].replace("/", " ") for l in r if l.startswith("1 NAME ")]:
            k = key(n, by)
            if k and k[0]:
                free_keys[k].append(x)
    for stem, p in T.people.items():
        g = T.gid(stem)
        if g in mh:
            continue
        fm = p["fm"]
        by = str(dates.year(fm.get("born")) or "")
        names = [fm.get("name") or stem] + as_list(fm.get("aliases"))
        hits = sorted({x for n in names if key(n, by) for x in free_keys.get(key(n, by), [])})
        if hits:
            err.append(f"{stem}: на сайте уже есть {', '.join('@'+h+'@' for h in hits)} с тем же именем и годом — "
                       f"впишите номер в gedcom_id карточки, иначе на сайте будет двойник")
        elif g:
            info["ещё не на сайте (уйдут новыми людьми)"].append(f"{stem} ({g})")
        else:
            info["без gedcom_id (получат временный номер I8…)"].append(stem)

    # даты, которые выгрузка не поймёт — они молча пропадут
    for stem, p in T.people.items():
        for k in ("born", "died"):
            v = p["fm"].get(k)
            if v not in (None, "") and not ged_date(v):
                err.append(f"{stem}: {k} «{v}» — не понимаю дату (нужно 1902, 1986-02, 1971-03-05, ABT 1935, BET 2005 AND 2006 — check_dates.py)")
    for stem, evs in T.events.items():
        for ev in evs:
            v = ev.get("date")
            if v not in (None, "") and not ged_date(v):
                warn.append(f"событие «{ev.get('title')}» ({stem}): дата «{v}» не уйдёт на сайт")

    # пол, места, события, источники
    no_country = defaultdict(list)
    for stem, p in T.people.items():
        fm = p["fm"]
        if str(fm.get("sex") or "").lower() not in ("male", "female"):
            warn.append(f"{stem}: не указан пол — на сайте будет «неизвестен», совпадения хуже")
        for k in ("birth_place", "death_place"):
            pl = link_target(fm.get(k))
            if fm.get(k) and not pl:
                warn.append(f"{stem}: {k} без ссылки [[…]] — место не найдётся в карточках мест")
            elif pl and pl not in T.places:
                warn.append(f"{stem}: {k} [[{pl}]] — нет карточки места, уйдёт без страны и координат")
            elif pl and "," not in (T.place_chain(T.city_of(pl)) or ""):
                if (T.places[pl].get("place_type") or "") != "country":
                    no_country[pl].append(stem)
        for l in section_lines(p["body"].replace("\n## Источники\n", "\n### __src\n"), "### __src"):
            s2 = link_target(l)
            if s2 and s2 not in T.sources:
                warn.append(f"{stem}: источник [[{s2}]] — нет карточки источника, не уйдёт на сайт")
    for pl, who in sorted(no_country.items()):
        warn.append(f"место [[{pl}]] без parent_place (страны) — уйдёт без страны, MyHeritage хуже сопоставит; "
                    f"людей {len(who)}: {', '.join(who[:4])}{' …' if len(who) > 4 else ''}")
    known = set(EVENT_TAG) | EVENT_SKIP | {"war", "kin", "military", "emigration", "immigration", "migration"}
    for stem, evs in T.events.items():
        for ev in evs:
            if ev.get("event_type") not in known:
                info[f"событие нового типа «{ev.get('event_type')}» — уйдёт как EVEN"].append(str(ev.get("title")))

    if not quiet:
        for k, v in info.items():
            print(f"· {k}: {len(v)}" + (f" — {', '.join(v[:8])}{' …' if len(v) > 8 else ''}" if v else ""))
        for w in warn:
            print("! " + w)
    for e in err:
        print("✗ " + e)
    print(f"Карточки для MyHeritage: людей {len(T.people)}, ошибок {len(err)}, предупреждений {len(warn)}")
    return 1 if err else 0


def main():
    quiet = "--quiet" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    cmd = args[0] if args else ""
    if len(args) < 2 and not OUR_SITE and cmd in ("lint", "check"):
        print("MyHeritage к этому дереву не подключён ([myheritage] export_site в ftree.toml) — сверять не с чем")
        return 0
    src = Path(args[1]) if len(args) > 1 else latest_export()
    if cmd == "build":
        build(src)
    elif cmd == "check":
        return lint(src, quiet=True) | check(src)
    elif cmd == "lint":
        return lint(src, quiet=quiet)
    else:
        print(__doc__)
        return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
