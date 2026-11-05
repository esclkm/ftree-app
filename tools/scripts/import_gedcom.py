#!/usr/bin/env python3
"""Загрузить чужое дерево из файла GEDCOM в дерево проекта — карточками или отчётом.

Зачем. GEDCOM — общий формат родословных: его отдают MyHeritage, FamilySearch, Geni, Gramps. Чтобы начать дерево с
чужой выгрузки или сверить с ней своё, этой команде дают файл, и она переводит его на язык карточек проекта (навыки
card-rules и dates): человек → карточка `people/` с новым номером `cr_id`; семья → связи father/mother/spouse вместе с
номерами `*_id`; брак, развод, место жительства → карточки `events/`; место → карточка `places/` (цепочкой: деревня →
губерния → страна); источник → карточка `sources/`. Даты — по GEDCOM, до 1918 года главная — по новому стилю.
Каждый факт — строкой «Факты (с источником)» со ссылкой на карточку самой выгрузки (номер человека в ней) и с
уверенностью «низкая»: чужое дерево — подсказка, не доказательство. Происхождение источника — «чужое дерево».

Два случая:
  • пустое дерево (людей нет) — карточки сразу; номер человека в выгрузке — `gedcom_id`;
  • живое дерево — только отчёт: для каждого человека из выгрузки — похожие карточки дерева (имя, пол, год рождения ±5),
    без слияний и без новых карточек. С `--create` — карточки всё-таки заводятся (номер в выгрузке — `external_id`, чтобы
    не спутать с `gedcom_id` своего дерева), а похожим ставится подозрение `maybe_same` (решает человек: rodo possible,
    rodo merge-cards … --why). Отчёт — в 3_research/tree_data/import/.
  --dry-run — только показать, что будет; ничего не пишет ни в каком случае.

  rodo import gedcom <файл.ged> [--dry-run] [--create] [--title "Дерево родственника X на MyHeritage"]

Что разбирает: INDI (NAME/GIVN/SURN/_MARNM/NICK, SEX, BIRT, CHR, DEAT, BURI, RESI с ADDR, OCCU, EDUC, RELI, NOTE, SOUR с
PAGE), FAM (HUSB, WIFE, CHIL, MARR, DIV), SOUR (TITL, AUTH, PUBL, _TYPE). Выгрузка MyHeritage чинится при чтении
(gedcom_parse.load_lines: CONC посреди буквы, разделители NEL). Два рождения одного человека с разницей 12–13 дней —
одна дата в двух стилях: главная — по новому, старая — рядом.

Чего не делает: не сливает людей, не трогает существующие карточки (кроме maybe_same с --create), фото (OBJE) не
качает — их адреса в отчёте.
"""
import argparse
import datetime
import json
import random
import re
import string
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dates  # noqa: E402
import gedcom_parse  # noqa: E402
import paths  # noqa: E402
from check_names import PATRONYMIC_END, PATRONYMIC_MID  # noqa: E402

LOW = "уверенность: низкая (чужое дерево, не проверено)"
EVENTS = {"BIRT": "рождение", "CHR": "крещение", "DEAT": "смерть", "BURI": "похороны", "RESI": "место жительства",
          "OCCU": "занятие", "EDUC": "образование", "RELI": "вероисповедание"}
SOURCE_TYPES = {"census": "census", "church": "church_record", "vital": "vital_record", "military": "military",
                "newspaper": "newspaper", "immigration": "immigration", "letter": "letter", "photo": "photo"}
SEX = {"M": "male", "F": "female"}


# ── чтение GEDCOM ─────────────────────────────────────────────────────────────────────────────────────────────────────

def child(n, tag):
    return next((c for c in n["children"] if c["tag"] == tag), None)


def children(n, tag):
    return [c for c in n["children"] if c["tag"] == tag]


def val(n, tag):
    c = child(n, tag) if n else None
    return c["value"].strip() if c and c["value"] else ""


@dataclass
class Event:
    tag: str
    date: "dates.GDate | None"
    date_raw: str
    place: str
    addr: str = ""
    value: str = ""          # у OCCU, EDUC, RELI — само значение
    note: str = ""
    cites: list = field(default_factory=list)   # [(xref источника, PAGE)]


@dataclass
class Indi:
    xref: str
    given: str
    surname: str
    married: list
    nick: str
    sex: str
    events: list
    notes: list
    cites: list
    famc: list
    fams: list
    media: list
    problems: list = field(default_factory=list)

    @property
    def gid(self):
        return self.xref.strip("@")

    def first(self, tag):
        return next((e for e in self.events if e.tag == tag), None)


def cites_of(n):
    return [(c["value"].strip(), val(c, "PAGE")) for c in children(n, "SOUR") if c["value"].startswith("@")]


def read_event(n, problems):
    raw = val(n, "DATE")
    try:
        d = dates.parse_gedcom(raw)
    except dates.DateError as e:
        problems.append(f"{n['tag']}: {e} — дата оставлена словами")
        d = dates.GDate("PHRASE", phrase=raw)
    return Event(n["tag"], d, raw, val(n, "PLAC"), val(n, "ADDR"),
                 n["value"].strip(), val(n, "NOTE"), cites_of(n))


def read_gedcom(path):
    records = gedcom_parse.build_tree(gedcom_parse.fold_cont(gedcom_parse.load_lines(path)))
    people, fams, srcs, head = {}, {}, {}, {}
    for r in records:
        if r["tag"] == "HEAD":
            head = {"source": val(r, "SOUR"), "name": val(child(r, "SOUR"), "NAME") if child(r, "SOUR") else ""}
        elif r["tag"] == "INDI":
            probs = []
            nm = child(r, "NAME")
            full = nm["value"] if nm else ""
            m = re.match(r"^(.*?)/(.*?)/(.*)$", full)
            given = val(nm, "GIVN") or ((m[1] + " " + m[3]) if m else full).strip()
            surname = val(nm, "SURN") or (m[2] if m else "")
            events = [read_event(c, probs) for c in r["children"] if c["tag"] in EVENTS]
            people[r["xref"]] = Indi(
                r["xref"], re.sub(r"\s+", " ", given).strip(), surname.strip(),
                [c["value"].strip() for c in (children(nm, "_MARNM") if nm else []) if c["value"].strip()],
                val(nm, "NICK"), val(r, "SEX"), events, [c["value"] for c in children(r, "NOTE") if c["value"].strip()],
                cites_of(r), [c["value"] for c in children(r, "FAMC")], [c["value"] for c in children(r, "FAMS")],
                [val(o, "FILE") for o in children(r, "OBJE") if val(o, "FILE")], probs)
        elif r["tag"] == "FAM":
            probs = []
            fams[r["xref"]] = {
                "xref": r["xref"], "husb": val(r, "HUSB"), "wife": val(r, "WIFE"),
                "chil": [c["value"] for c in children(r, "CHIL")],
                "marr": [read_event(c, probs) for c in children(r, "MARR")],
                "div": [read_event(c, probs) for c in children(r, "DIV")], "problems": probs}
        elif r["tag"] == "SOUR":
            srcs[r["xref"]] = {"xref": r["xref"], "title": val(r, "TITL") or r["xref"].strip("@"), "author": val(r, "AUTH"),
                               "publ": val(r, "PUBL"), "type": val(r, "_TYPE") or val(r, "TYPE"), "text": val(r, "TEXT")}
    return head, people, fams, srcs


# ── имена ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def clean_name(given, surname):
    """Имя для поля name по стандарту check_names: без отчества (оно — в aliases), без пустот; ничего — «Unknown»."""
    words = given.split()
    kept = [w for i, w in enumerate(words) if not (i > 0 and (PATRONYMIC_MID.search(w) or PATRONYMIC_END.search(w)))]
    name = " ".join(kept + ([surname] if surname else [])).strip()
    return name or "Unknown", " ".join(words + ([surname] if surname else [])) if kept != words else ""


def safe_stem(s):
    return re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", s).replace("  ", " ").strip()


def new_id(taken):
    while True:
        a, b = ("".join(random.choices(string.ascii_lowercase, k=3)) for _ in range(2))
        cid = f"{a}-{random.randint(0, 999):03d}-{b}-{random.randint(0, 999):03d}"
        if cid not in taken:
            taken.add(cid)
            return cid


# ── план: что будет создано ───────────────────────────────────────────────────────────────────────────────────────────

class Plan:
    def __init__(self, ged_path, title, tree, live):
        self.ged = Path(ged_path)
        self.tree, self.live = tree, live
        self.head, self.indi, self.fams, self.srcs = read_gedcom(ged_path)
        self.taken = set(tree.people) | set(tree.places) | set(tree.sources)
        self.files = {}          # путь от корня → текст
        self.report = []         # строки отчёта
        self.stems_people = {p.stem for p in tree.people.values()}
        self.stems_places = {pl.stem for pl in tree.places.values()}
        self.stems_events = {p.stem for p in paths.EVENTS.glob("*.md")} if paths.EVENTS.exists() else set()
        prog = self.head.get("name") or self.head.get("source") or "GEDCOM"
        self.file_title = safe_stem(title or f"Чужое дерево — {self.ged.name} ({prog})")
        self.candidates = {}     # xref → [(Person, почему)]

    # источники
    def sources(self):
        by_title = {s.title: s for s in self.tree.sources.values()}
        self.src_stem = {}
        rows = [(None, {"title": self.file_title, "author": "", "publ": "", "type": "", "text": ""})] + list(self.srcs.items())
        for xref, s in rows:
            stem = safe_stem(s["title"])
            if stem in by_title or (paths.TREE_SOURCES / f"{stem}.md").exists():
                self.src_stem[xref] = stem          # уже есть (повторная загрузка) — ссылаемся на неё
                continue
            self.src_stem[xref] = stem
            kind = next((v for k, v in SOURCE_TYPES.items() if k in s["type"].lower()), "custom")
            fm = {"cr_type": "source", "origin": "чужое дерево", "cr_id": new_id(self.taken), "title": stem,
                  "source_type": kind, "author": s["author"], "repository": s["publ"],
                  "confidence": "low", "tags": ["Происхождение-чужое-дерево"]}
            if xref is None:
                body = (f"Выгрузка чужого дерева в формате GEDCOM: файл `{self.ged.name}`, программа — "
                        f"{self.head.get('name') or self.head.get('source') or 'не указана'}. Загружена "
                        f"`rodo import gedcom` {datetime.date.today():%d.%m.%Y}. Номер человека в выгрузке — "
                        f"`gedcom_id` (или `external_id`) в его карточке и «где» в строке факта. Всё отсюда — подсказка "
                        f"для проверки, не доказательство.")
            else:
                body = (f"Источник, на который ссылается чужое дерево (`{self.ged.name}`, {xref.strip('@')}). Сам "
                        f"документ проект не видел — сведения взяты из выгрузки." + (f"\n\n{s['text']}" if s["text"] else ""))
            self.files[paths.rel(paths.TREE_SOURCES / f"{stem}.md")] = card(fm, f"# {stem}\n\n{body}\n")

    def cite(self, ind_or_fam_id, cites, page_fallback=""):
        """Строка «источник: …» — выгрузка с номером, потом источники, на которые она ссылается."""
        parts = [f"[[{self.src_stem[None]}]], {ind_or_fam_id.strip('@')}"]
        for xref, page in cites:
            if xref in self.src_stem:
                parts.append(f"[[{self.src_stem[xref]}]]" + (f", {page} (по чужому дереву)" if page else ""))
        return "; ".join(parts)

    # места
    def places(self):
        """Каждая строка PLAC — цепочка «деревня, губерния, страна». Карточка — на каждое звено; одно и то же имя с разной
        цепочкой выше — разные карточки («Вербичи (Брестская область)»): это может быть одно место в разных государствах
        или два разных места, решает человек (отчёт)."""
        chains = set()
        years = defaultdict(set)          # цепочка → годы событий
        for p in self.indi.values():
            for e in p.events:
                if e.place:
                    ch = tuple(x.strip() for x in e.place.split(",") if x.strip())
                    chains.add(ch)
                    if e.date and e.date.first_year:
                        for i in range(len(ch)):
                            years[ch[i:]] |= {e.date.first_year, e.date.last_year}
        for f in self.fams.values():
            for e in f["marr"] + f["div"]:
                if e.place:
                    ch = tuple(x.strip() for x in e.place.split(",") if x.strip())
                    chains.add(ch)
                    if e.date and e.date.first_year:
                        for i in range(len(ch)):
                            years[ch[i:]] |= {e.date.first_year, e.date.last_year}
        links = {ch[i:] for ch in chains for i in range(len(ch))}
        by_name = defaultdict(list)
        for ln in sorted(links, key=lambda c: (len(c), c)):
            by_name[ln[0]].append(ln)
        existing = {}
        for pl in self.tree.places.values():
            parent = self.tree.places.get(pl.parent)
            for k in {pl.stem, pl.name, *pl.aliases}:
                existing.setdefault((k, parent.name if parent else None), pl.stem)
        self.place_stem = {}
        for ln in sorted(links, key=len):
            parent = ln[1] if len(ln) > 1 else None
            if (ln[0], parent) in existing:
                self.place_stem[ln] = existing[(ln[0], parent)]
                continue
            stem = safe_stem(ln[0])
            if len(by_name[ln[0]]) > 1 or stem in self.stems_places:
                stem = safe_stem(f"{ln[0]} ({', '.join(ln[1:]) or 'без области'})")
            self.stems_places.add(stem)
            self.place_stem[ln] = stem
            kind = "country" if len(ln) == 1 and any(len(c) > 1 for c in links if c[-1] == ln[0]) else \
                ("region" if len(ln) > 1 and any(c[1:] == ln for c in links) else "locality")
            fm = {"cr_type": "place", "cr_id": new_id(self.taken), "name": ln[0], "place_type": kind,
                  "place_category": "real"}
            if parent:
                fm["parent_place"] = f"[[{self.place_stem[ln[1:]]}]]"
            body = f"# {ln[0]}\n\n## О месте\n\nТак место записано в чужом дереве (`{self.ged.name}`): «{', '.join(ln)}».\n"
            if not parent:
                ys = sorted(years.get(ln, ()))
                span = (f"{ys[0]}–{ys[-1]}" if ys[0] != ys[-1] else f"{ys[0]}") if ys else "(без даты)"
                what = ln[0] if kind == "country" else f"{ln[0]} — страна в выгрузке не указана"
                body += (f"\n## Государства по годам\n\n- {span} — {what} (так в выгрузке, по годам событий в ней; "
                         f"полные годы — уточнить)\n")
            self.files[paths.rel(paths.PLACES / f"{stem}.md")] = card(fm, body)
        for name, lns in by_name.items():
            if len(lns) > 1:
                self.report.append(f"- Место «{name}» записано по-разному: " + "; ".join("«" + ", ".join(x) + "»" for x in lns)
                                   + " — разные карточки; одно ли это место (сменило государство) — решить по источнику.")

    def place_link(self, place, shown=None):
        if not place:
            return ""
        ch = tuple(x.strip() for x in place.split(",") if x.strip())
        stem = self.place_stem[ch]
        shown = shown or ch[0]
        return f"[[{stem}]]" if stem == shown else f"[[{stem}|{shown}]]"

    # люди
    def people(self):
        born = {x: (p.first("BIRT") or p.first("CHR")) for x, p in self.indi.items()}
        year = {x: (e.date.first_year if e and e.date else None) for x, e in born.items()}
        names = {}
        for x, p in self.indi.items():
            name, full = clean_name(p.given, p.surname)
            wife_married = (p.sex == "F" and p.married and p.married[0] != p.surname and (year[x] or 0) >= 1900)
            maiden = p.surname if wife_married else ""
            if wife_married:
                name = clean_name(p.given, p.married[0])[0]
            aliases = [a for a in dict.fromkeys([full, clean_name(p.given, p.surname)[0] if wife_married else "",
                                                 *(clean_name(p.given, m)[0] for m in p.married), p.nick]) if a and a != name]
            names[x] = (name, maiden, aliases)
        count = Counter(n for n, _, _ in names.values())
        self.stem = {}
        used = set(self.stems_people)
        for x, (name, _, _) in names.items():
            stem = safe_stem(name)
            if not self.indi[x].given and year[x]:      # имени нет, только фамилия — «Ясенев (1883)», а не просто «Ясенев»
                stem = safe_stem(f"{name} ({year[x]})")
            elif count[name] > 1 or stem in used:
                yrs = [year[y] for y, (n, _, _) in names.items() if n == name]
                stem = safe_stem(f"{name} ({year[x]})") if year[x] and yrs.count(year[x]) == 1 else safe_stem(
                    f"{name} ({self.indi[x].gid})")
            while stem in used:
                stem += " (импорт)"
            used.add(stem)
            self.stem[x] = stem
        self.ids = {x: new_id(self.taken) for x in self.indi}
        # семьи → связи
        father, mother, spouses = {}, {}, defaultdict(list)
        for f in self.fams.values():
            h, w = f["husb"] if f["husb"] in self.indi else None, f["wife"] if f["wife"] in self.indi else None
            if h and w:
                spouses[h].append(w)
                spouses[w].append(h)
            for c in f["chil"]:
                if c in self.indi:
                    if h:
                        father[c] = h
                    if w:
                        mother[c] = w
        self.kids = defaultdict(list)
        for c in self.indi:
            for par in (father.get(c), mother.get(c)):
                if par:
                    self.kids[par].append(c)
        couple_facts = defaultdict(list)     # человек → строки фактов о браке/разводе
        for f in self.fams.values():
            self.family_events(f, couple_facts)
        for x, p in self.indi.items():
            self.person_card(x, p, names[x], father.get(x), mother.get(x), spouses.get(x, []), couple_facts[x])
        self.names = names

    def family_events(self, f, couple_facts):
        h, w = f["husb"], f["wife"]
        if not (h in self.indi and w in self.indi):
            return
        for tag, kind, word in (("marr", "marriage", "брак"), ("div", "divorce", "развод")):
            for e in f[tag]:
                when = e.date.ru() if e.date and e.date.kind != "PHRASE" else ""
                where = self.place_link(e.place)
                src = self.cite(f["xref"], e.cites)
                for me, other in ((h, w), (w, h)):
                    text = ", ".join(x for x in (f"с [[{self.stem[other]}]]", where) if x)
                    label = f"{when}, {word}" if when else word.capitalize()
                    couple_facts[me].append(f"- **{label}:** {text} — *источник: {src} · {LOW}*")
                title = safe_stem(f"{'Брак' if kind == 'marriage' else 'Развод'} — {self.stem[h]} и {self.stem[w]}"
                                  + (f" ({e.date.first_year})" if e.date and e.date.first_year else ""))
                self.event_card(title, kind, [h, w], e, src)

    def event_card(self, title, kind, who, e, src, place_stem=None):
        while title in self.stems_events:
            title += " (импорт)"
        self.stems_events.add(title)
        fm = {"cr_type": "event", "cr_id": new_id(self.taken), "title": title, "event_type": kind,
              "date_precision": "exact" if e.date and e.date.kind == "" else ("unknown" if not e.date else "estimated"),
              "persons": [f"[[{self.stem[x]}]]" for x in who]}
        if e.date and e.date.kind != "PHRASE":
            fm["date"] = e.date.card()
        if place_stem or e.place:
            fm["place"] = f"[[{place_stem or self.place_stem[tuple(x.strip() for x in e.place.split(',') if x.strip())]}]]"
        desc = f"Из чужого дерева: {src.replace('[[', '').replace(']]', '')}."
        fm["description"] = desc
        self.files[paths.rel(paths.EVENTS / f"{title}.md")] = card(fm, f"# {title}\n\n{desc}\n")

    def house(self, x, e, src):
        """RESI с адресом → карточка дома «<город> — <адрес>» и событие «место жительства». Номер дома сайт прячет сам
        (site_data/privacy.py, по названиям мест), в карточке он цел."""
        ch = tuple(s.strip() for s in e.place.split(",") if s.strip()) if e.place else ()
        city = self.place_stem.get(ch)
        stem = safe_stem(f"{ch[0]} — {e.addr}" if ch else e.addr)
        if stem not in self.stems_places:
            self.stems_places.add(stem)
            fm = {"cr_type": "place", "cr_id": new_id(self.taken), "name": stem, "place_type": "house",
                  "place_category": "real", "house_kind": "apartment" if re.search(r"\d+\s*[-/]\s*\d+", e.addr) else "private"}
            if city:
                fm["parent_place"] = f"[[{city}]]"
            self.files[paths.rel(paths.PLACES / f"{stem}.md")] = card(
                fm, f"# {stem}\n\n## О месте\n\nАдрес из чужого дерева (`{self.ged.name}`). Номер дома на сайте не "
                    f"показывается.\n")
        self.event_card(safe_stem(f"Место жительства — {self.stem[x]}" + (f" ({e.date.ru()})" if e.date else "")),
                        "residence", [x], e, src, place_stem=stem)
        return stem

    def person_card(self, x, p, nm, fa, mo, sps, couple):
        name, maiden, aliases = nm
        fm = {"cr_id": self.ids[x], "cr_type": "person"}
        if self.live:
            fm.update({"external_id": p.gid, "external_id_source": self.ged.name})
        else:
            fm["gedcom_id"] = p.gid
        fm["name"] = name
        if aliases:
            fm["aliases"] = aliases
        if maiden:
            fm["maiden_name"] = maiden
        if p.sex not in SEX:
            p.problems.append(f"пол «{p.sex}» не указан — записан male, проверить")
        fm["sex"] = SEX.get(p.sex, "male")
        facts = []
        # рождение: несколько BIRT — одна дата в двух стилях (12–13 дней) или расхождение
        births = [e for e in p.events if e.tag == "BIRT"]
        if len(births) == 2 and births[0].date and births[1].date and births[0].date.kind == births[1].date.kind == "" \
                and births[0].date.a.d and births[1].date.a.d and not births[0].date.os:
            a, b = births[0].date.a, births[1].date.a
            if dates.julian_to_gregorian(a) == b or dates.julian_to_gregorian(b) == a:
                old, new = (a, b) if dates.julian_to_gregorian(a) == b else (b, a)
                births[0].date = dates.GDate("", new, os=old)
                births[0].note = (births[0].note + "; " if births[0].note else "") + \
                    f"в выгрузке две даты — {old.ru()} и {new.ru()}: это одна дата в двух стилях (старый и новый)" + \
                    (f"; при второй: «{births[1].note}»" if births[1].note else "")
                births[0].place = births[0].place or births[1].place
                births[0].cites += births[1].cites
                p.events.remove(births[1])
        main = {"BIRT": p.first("BIRT") or p.first("CHR"), "DEAT": p.first("DEAT") or p.first("BURI")}
        for key, prop, pprop in (("BIRT", "born", "birth_place"), ("DEAT", "died", "death_place")):
            e = main[key]
            fm[prop] = e.date.card() if e and e.date and e.date.kind != "PHRASE" else ""
            if e and e.place:
                fm[pprop] = f"[[{self.place_stem[tuple(s.strip() for s in e.place.split(',') if s.strip())]}]]"
        if fa:
            fm.update({"father": f"[[{self.stem[fa]}]]", "father_id": self.ids[fa]})
        if mo:
            fm.update({"mother": f"[[{self.stem[mo]}]]", "mother_id": self.ids[mo]})
        if sps:
            fm["spouse"] = [f"[[{self.stem[s]}]]" for s in sps]
            fm["spouse_id"] = [self.ids[s] for s in sps]
        kids = [c for c in self.kids.get(x, [])]
        if kids:
            fm["children"] = [f"[[{self.stem[c]}]]" for c in kids]
            fm["children_id"] = [self.ids[c] for c in kids]
        cands = self.candidates.get(x, [])
        if cands:
            fm["maybe_same"] = [f"[[{c.stem}]]" for c, _ in cands]
            fm["maybe_same_id"] = [c.id for c, _ in cands]
        used_src = [self.src_stem[None]] + [self.src_stem[c] for e in p.events for c, _ in e.cites if c in self.src_stem] \
            + [self.src_stem[c] for c, _ in p.cites if c in self.src_stem]
        for e in p.events:
            word = EVENTS[e.tag]
            when = e.date.ru() if e.date and e.date.kind != "PHRASE" else ""
            if e.date and e.date.kind == "PHRASE":
                e.value = (e.value + " " if e.value else "") + f"(дата в выгрузке: «{e.date_raw}»)"
            where = self.place_link(e.place)
            if e.tag == "RESI" and e.addr:
                where = f"[[{self.house(x, e, self.cite(p.xref, e.cites))}]]"
            text = ", ".join(s for s in (e.value, where, e.note) if s) or "место не указано"
            label = f"{when}, {word}" if when else word.capitalize()
            facts.append(f"- **{label}:** {text} — *источник: {self.cite(p.xref, e.cites)} · {LOW}*")
        facts += couple
        for c in cands:
            facts.append(f"- **Возможно, тот же человек:** [[{c[0].stem}]] — {c[1]} — *источник: "
                         f"{self.cite(p.xref, [])} · уверенность: низкая (вывод проекта: совпали имя, пол и годы; "
                         f"решить по документу)*")
        body = "## Факты и заметки\n\n### Факты (с источником)\n\n" + "\n".join(facts) + "\n"
        if p.problems:
            body += "\n### Открытые вопросы\n\n" + "\n".join(f"- {q}" for q in p.problems) + "\n"
        if p.notes or p.media:
            body += "\n### Заметки (из дерева MyHeritage и записей проекта)\n\n"
            body += "\n\n".join(f"Из чужого дерева ({p.gid}): " + re.sub(r"<[^>]+>", " ", n).strip() for n in p.notes)
            if p.media:
                body += ("\n\n" if p.notes else "") + "Фото в чужом дереве (не скачаны): " + ", ".join(p.media)
            body += "\n"
        srcs = list(dict.fromkeys(used_src))
        fm["sources"] = [f"[[{s}]]" for s in srcs]
        body += "\n## Источники\n\n" + "\n".join(
            f"- [[{s}]] — {p.gid} · уверенность: низкая · происхождение: чужое дерево" for s in srcs) + "\n"
        self.files[paths.rel(paths.PEOPLE / f"{self.stem[x]}.md")] = card(fm, body)

    # живое дерево: похожие
    def match(self):
        """Похожие карточки дерева: имя (кириллица и латиница сравниваются через латиницу), пол, год рождения ±5."""
        from find_duplicates import tokens, lev
        index = []
        for c in self.tree.people.values():
            toks = set()
            for n in [c.name, *map(str, c.fm.get("aliases") or [])]:
                toks |= set(tokens(n))
            index.append((c, toks, len(tokens(c.name)), c.born.first_year if c.born else None))
        for x, p in self.indi.items():
            mine = set(tokens(" ".join([p.given, p.surname, *p.married])))
            e = p.first("BIRT") or p.first("CHR")
            y = e.date.first_year if e and e.date else None
            found = []
            for c, toks, size, cy in index:
                if SEX.get(p.sex, "") and c.sex != p.sex[:1]:
                    continue
                if not mine or not toks:
                    continue
                same = sum(1 for t in mine if any(t == u or (len(t) > 3 and lev(t, u) <= 1) for u in toks))
                # нужно два слова (имя и фамилия); у кого одно слово («Ясенев» без имени) — и у второго одно
                if same < min(2, max(len(set(tokens(" ".join([p.given, p.surname])))), size)):
                    continue
                if y and cy and abs(y - cy) > 5:
                    continue
                why = f"имя ({c.name}), пол" + (f", год {cy} ~ {y}" if y and cy else ", год неизвестен")
                found.append((c, why))
            if found:
                self.candidates[x] = found[:3]

    def build(self):
        if self.live:
            self.match()
        self.sources()
        self.places()
        self.people()


# ── запись ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def yval(v):
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?|[a-z]{3}-\d{3}-[a-z]{3}-\d{3}|[a-z]+|", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def card(fm, body):
    out = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            out.append(f"{k}:")
            out += [f"  - {yval(x)}" for x in v]
        else:
            out.append(f"{k}: {yval(v)}".rstrip())
    return "\n".join(out) + "\n---\n" + body


def report_text(plan, written):
    p = plan
    lines = [f"# Импорт GEDCOM — {p.ged.name} ({datetime.date.today():%d.%m.%Y})", "",
             f"В выгрузке: людей {len(p.indi)}, семей {len(p.fams)}, источников {len(p.srcs)}.",
             f"Дерево: {'живое — людей ' + str(len(p.tree.people)) if p.live else 'пустое'}. "
             f"{'Карточки записаны.' if written else 'Ничего не записано.'}", ""]
    kinds = Counter(f.split("/")[2] for f in p.files)
    lines.append("Будет создано: " + ", ".join(f"{k} — {n}" for k, n in sorted(kinds.items())) + ".")
    if p.live:
        lines += ["", "## Похожие карточки дерева", "",
                  "Совпали имя, пол и год рождения (±5). Это подсказка, не доказательство: решать по документу "
                  "(`rodo possible`, `rodo merge-cards … --why`).", "",
                  "| В выгрузке | Год | Похожие в дереве | Почему |", "|---|---|---|---|"]
        for x, cands in p.candidates.items():
            ind = p.indi[x]
            e = ind.first("BIRT")
            y = e.date.first_year if e and e.date else ""
            for c, why in cands:
                lines.append(f"| {ind.gid} {clean_name(ind.given, ind.surname)[0]} | {y} | [[{c.stem}]] | {why} |")
        if not p.candidates:
            lines.append("| — | | никого похожего | |")
    probs = [(i.gid, q) for i in p.indi.values() for q in i.problems] + \
        [(f["xref"].strip("@"), q) for f in p.fams.values() for q in f["problems"]]
    if probs or p.report:
        lines += ["", "## Проверить руками", ""] + [f"- {g}: {q}" for g, q in probs] + p.report
    return "\n".join(lines) + "\n"


def run(ged, dry_run=False, create=False, title=None, out=print):
    import cards
    tree = cards.load()
    live = bool(tree.people)
    plan = Plan(ged, title, tree, live)
    plan.build()
    write = not dry_run and (not live or create)
    text = report_text(plan, write)
    out(text)
    if dry_run:
        for f in sorted(plan.files):
            out(f"  (не записано) {f}")
        return plan
    if write:
        for rel, body in plan.files.items():
            path = paths.ROOT / rel
            if path.exists():
                continue                  # чужое не перезаписываем (повторная загрузка того же источника)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    if live:
        rep = paths.TREE_DATA / "import" / f"{plan.ged.stem} — {datetime.date.today():%Y-%m-%d}.md"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(text, encoding="utf-8")
        out(f"Отчёт: {paths.rel(rep)}" + ("" if write else " — карточки не созданы (живое дерево; создать — --create)"))
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="GEDCOM → карточки дерева")
    ap.add_argument("ged")
    ap.add_argument("--dry-run", action="store_true", help="только показать, ничего не писать")
    ap.add_argument("--create", action="store_true", help="в живом дереве всё-таки завести карточки (с maybe_same)")
    ap.add_argument("--title", help="название карточки источника-выгрузки")
    a = ap.parse_args(argv)
    if not Path(a.ged).is_file():
        raise SystemExit(f"нет файла {a.ged}")
    run(a.ged, a.dry_run, a.create, a.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
