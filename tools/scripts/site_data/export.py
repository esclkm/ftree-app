"""Дерево (cards.Tree) → JSON по схеме web/schema/: один файл — одна сущность, плюс общий список.

  data/index.json           — все люди, места, источники одной строкой каждый (поиск, дерево, карта)
  data/people/<id>.json     — человек: имена, даты, связи, факты с источниками
  data/places/<id>.json     — место: названия, координаты, государства по годам
  data/sources/<id>.json    — источник: чей, откуда
  data/docs/<номер>.json    — заметка проекта, на которую есть ссылка: расшифровка, находка, документ человека
  data/research.json        — «Что ещё искать»: план поиска по предкам (<папка поиска>/ПОИСК_*.md)
  data/progress.json        — «Состояние дерева» и «Что нового»: цифры по родам и лента правок по дням (progress.py)

Всё, что увидит посетитель, проходит через site_data.text (контакты и номера домов вырезаны, ссылки — по номеру).
Биографии, фото, «Места и эпохи» и значки выгрузка берёт через Extras — их считает site_export.py (SiteExtras).
"""
import datetime
import json
import math
import re

import dates
from cards.notes import as_list, link_target
from cards.kinship import ROOT as HOME_GEDCOM, levels as kinship_levels
from cards.places import about_of, states_of, text_of as place_text_md
from . import eras
from .life import WHERE_COL, lifespan
from .names import PLACE_SLUG_KEEP, assign_slugs, person_slugs, latin, person_names, place_names, slugify
from .privacy import Privacy, audio_source, social_only
from .text import Text

VERSION = "1"
UNKNOWN = re.compile(r"Unknown\b")  # «Unknown (I25)» — имя неизвестно
NO_BRANCH = "Без ветки"


def _gist(desc):
    """Суть события одной фразой для карты: первое предложение описания без пометок `[вывод]` и «Источник: …»."""
    s = re.split(r"\s*Источник[и]?:", desc)[0]
    s = re.sub(r"`\[[^\]]*\]`", "", s).strip()
    s = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])", s)[0].strip()
    if len(s) > 160:
        s = s[:160].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s


def _fact_gist(text):
    """Строка факта для карты: не по первой точке — в фактах она чаще от сокращения («в 1972 г. дочь», «польск.»), —
    а до 160 знаков по слову; ссылку [[…]] не рвём."""
    if len(text) <= 160:
        return text
    s = text[:160].rsplit(" ", 1)[0]
    if s.rfind("[[") > s.rfind("]]"):
        s = s[:s.rfind("[[")].rstrip()
    return s.rstrip(",;:") + "…"


def date_json(g):
    """GDate → {value, ru, sort, words?, calendar?}; дата из одних слов («(без даты)») — None: это не дата."""
    if g is None or g.kind == "PHRASE":
        return None
    f = g.first
    out = {"value": g.card(), "ru": g.ru(), "sort": f.y * 10000 + f.m * 100 + f.d + (99 if g.kind == "AFT" else 0)}
    if g.phrase:
        out["words"] = g.phrase
    if g.julian:
        out["calendar"] = "julian"
    if g.os:                          # главная — по новому стилю, дата документа по старому — рядом мелко
        out["os"] = g.os.ru()
        out["ru"] = dates.GDate(g.kind, g.a, g.b, g.phrase).ru()
    return out


class Extras:
    """Что о человеке знает сборка страниц, а не карточка. Это считает site_export.py (биографии, фото, «Места и
    эпохи» — его отлаженный код); переедет сюда по одному, а этот стык останется. Строки — как есть, из карточек и
    биографий: ссылки Obsidian и очистку от адресов делает выгрузка (одно место — одна очистка)."""

    def names(self, pid):
        """Имя на языках сайта, как на страницах (с name_local из переводов, «неизвестно» у Unknown) или None"""
        return None

    def card(self, pid):
        """Круг без фото и линии на дереве: {"initials": {lang: «СМ»} или None, "color": 0–7, "marriage": номер брака
        родителей, от которого ребёнок (0 — один брак)} или None"""
        return None

    def ui(self):
        """Надписи интерфейса и значки: {"i18n": {lang: {ключ: текст}}, "icons": {имя: контур SVG}} или None"""
        return None

    def source_text(self, stem):
        """Текст карточки источника с встроенными расшифровками (![[…md]]) — как на его странице, или None"""
        return None

    def note(self, target):
        """Ссылка [[target]] на заметку проекта (не карточку): ("doc", номер) — заметка выгружается в data/docs/;
        ("person", cr_id) — это биография человека; None — на сайт не идёт (оставить словами)"""
        return None

    def next_doc(self):
        """Следующая заметка из тех, на которые выгрузка уже дала ссылку (note), или None, когда очередь пуста:
        {"id", "title", "path", "meta": {origin, repository, confidence}, "people": [cr_id], "media": [(адрес, по паролю?)],
        "files": [(имя, адрес)], "audio": bool, "md": текст} или {"id", "goto": (вид, номер)} — старый адрес заметки,
        у которой теперь своя страница (источник, человек)"""
        return None

    def research(self):
        """«Что ещё искать» (paths.RESEARCH_NEXT): {"md": текст без заголовка, "updated": "ГГГГ-ММ-ДД" или None} или None"""
        return None

    def progress(self, tree):
        """«Состояние дерева» и «Что нового» (site_data/progress.py) или None — без них"""
        return None

    def gallery(self):
        """Фото мест и времени по альбомам: [{"slug", "names": {ru, en, pl}, "kind": place|theme, "place": cr_id или
        None, "photos": [{"url", "thumb", "year", "year_txt", "desc", "whose", "exact", "note", "source", "rights",
        "link", "section", "era", "addr": cr_id точного места (дом, вуз) или None, "like": «≈ не наше» — {"real", "ours":
        названия на языках, "km", "ours_place": cr_id} или None}]}] — строки как в описях, их чистит выгрузка"""
        return []

    def place_people(self, place_id):
        """Кто связан с местом и чем: [(cr_id человека, [ev_birth, pp_born, ev_residence …])] — как на странице места"""
        return []

    def place_events(self, place_id, pid):
        """События человека в этом месте: [(ключ надписи ev_*, дата из карточки события или None, описание)]"""
        return []

    def place_mentions(self, place_id):
        """Кто упоминает место ссылкой в биографии или карточке, кроме тех, что уже в place_people: [cr_id]"""
        return []

    def place_text(self, place_id):
        """Текст карточки места без заголовка, «Государств по годам» и «О месте» (они — отдельно) или None"""
        return None

    def life_photos(self, pid):
        """Фото мест из жизни: ([{"names", "place": cr_id или None, "album": slug или None, "photos": [как в gallery]}],
        [cr_id адресов, где снимки есть, но не из его лет]) — отбор по годам его жизни в этих местах"""
        return [], []

    def source_media(self, stem):
        """Снимки из media карточки источника → [(адрес от корня сайта, закрыт паролем?)]"""
        return []

    def place_tr(self, place_id):
        """Переводы текста карточки места: {язык: (тело перевода, ИИ не проверен?, отстаёт от русского?)}"""
        return {}

    def fact_tr(self, f):
        """Перевод строки факта: {язык: {label, text, reasoning, locators («a ¦ b» — места в источниках по порядку)}}"""
        return {}

    def source_titles(self, stem, title):
        """Название источника на других языках: {язык: название}"""
        return {}

    def occupation_tr(self, text):
        """Поле «Занятие» на других языках: {язык: текст}"""
        return {}

    def photo_tr(self, r):
        """Перевод подписи снимка (свежий): {язык: {desc, whose, exact, note, section}}"""
        return {}

    def biography(self, pid):
        """→ None или {"file": путь, "ru": текст без линии жизни и «Памяти», "lifeline": [(когда, что, [(колонка, значение)])],
        "memory": строки «Памяти» (после смерти) так же, "recollections": [(название, кто вспоминает · откуда, рассказ)],
        "questions": Markdown «Открытых вопросов» или "",
        "tr": {lang: (текст, перевод ИИ?, устарел?, строки линии жизни перевода, строки «Памяти» перевода,
                      «Воспоминания» перевода, «Открытые вопросы» перевода)}}"""
        return None

    def media(self, pid):
        """→ [(адрес от корня сайта, закрыт паролем?)] — фото из media карточки, первое — портрет"""
        return []

    def media_url(self, name):
        """Имя файла из [[…jpg]] → адрес на сайте или None"""
        return None

    def stays(self, pid):
        """→ [(с, по, событие ev_…, cr_id места, государство тогда или None)]"""
        return []

    def stats(self, pid):
        """→ значки «сколько материала» (index.schema.json, stats) или None"""
        return None

    def documents(self, pid):
        """→ документы человека для профиля (кроме закрытых): [{title, kind, years, cover, pdf, page, pages, origin,
        private}] — адреса от корня сайта или None"""
        return []


def distance(a, b):
    """Километры по прямой между (широта, долгота)."""
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _drop_empty(d, keep=()):
    """Без пустых полей — кроме обязательных по схеме (keep): пустой список связей — тоже ответ."""
    return {k: v for k, v in d.items() if k in keep or v not in (None, "", [], {})}


class Export:
    def __init__(self, tree, extras=None):
        self.tree, self.extras = tree, extras or Extras()
        self.privacy = Privacy([p.name for p in tree.places.values()],
                               [p.name for p in tree.places.values() if p.fm.get("address_public")])
        self.text = Text(tree, self.privacy, self.extras.media_url, self.extras.note)
        clean = self.text.clean
        self.person_names = {p.id: self.extras.names(p.id) or person_names(p.name, as_list(p.fm.get("aliases")))
                             for p in tree.people.values()}
        # название латиницей — побуквенно; описательное («хата Прокопа до войны») — переводом из карточки: name_pl, name_es, name_en
        self.place_names = {p.id: {**place_names(clean(p.name)), **{k[5:]: clean(str(p.fm[k])) for k in ("name_en", "name_pl", "name_es")
                                                                    if p.fm.get(k)}} for p in tree.places.values()}
        self.slugs = {
            **assign_slugs([(i, n["en"], p.born.first_year if p.born and p.born.first else None)
                            for i, p in tree.people.items() for n in [self.person_names[i]]], person_slugs()),
            **assign_slugs([(i, PLACE_SLUG_KEEP.get(n["ru"], n["en"]), None) for i, n in self.place_names.items()]),
            **assign_slugs([(i, latin(clean(s.title), "en"), None) for i, s in tree.sources.items()]),
        }
        stems = {p.stem: p.id for p in tree.people.values()}
        died = {stems[t] for e in tree.events if e.get("event_type") in ("death", "burial")
                for t in map(link_target, as_list(e.get("persons"))) if t in stems}
        self.life = {p.id: lifespan(p.fm.get("born"), p.fm.get("died"), p.id in died) for p in tree.people.values()}

    # ---------- человек ----------

    def fact(self, f):
        out = {"text": self.text(f.text), "sources": [_drop_empty({"source": r.source, "locator": self.text(r.locator)})
                                                     for r in f.refs],
               "confidence": f.confidence, "provenance": f.provenance}
        d = date_json(f.date)
        if d:
            out["date"] = d
        elif f.date is not None:  # «(без даты)» — слова вместо даты
            out["label"] = f.date.ru()
        if f.label:
            out["label"] = self.text(f.label)
        if f.reasoning:
            out["reasoning"] = self.text(f.reasoning)
        tr = {}
        for lang, v in self.extras.fact_tr(f).items():
            locs = v.get("locators", "").split(" ¦ ") if v.get("locators") else []
            tr[lang] = _drop_empty({"label": self.text(v["label"]) if v.get("label") else None,
                                    "text": self.text(v["text"]) if v.get("text") else None,
                                    "reasoning": self.text(v["reasoning"]) if v.get("reasoning") else None,
                                    "locators": [self.text(x) for x in locs] if len(locs) == len(f.refs) else None,
                                    "when": self.text.clean(v["when"]) if v.get("when") else None})
        if tr := {k: v for k, v in tr.items() if v.get("text")}:
            out["tr"] = tr
        return out

    def relationships(self, p):
        rels = [{"type": "parent-child", "parent": par, "child": p.id} for par in p.father + p.mother]
        rels += [{"type": "parent-child", "parent": p.id, "child": c} for c in p.children]
        for s in p.spouses:
            r = {"type": "couple", "person1": p.id, "person2": s}
            pair = frozenset((p.id, s))
            if pair in self.tree.divorces:
                y = self.tree.divorces[pair]
                r["divorced"] = date_json(dates.parse_card(str(y))) if y else True
            rels.append(r)
        return rels

    def possible(self, p):
        """«Возможно, тот же человек / родня» — подозрение, не связь (на дереве не рисуется). Обе стороны — из cards."""
        return [_drop_empty({"type": x.kind, "person": x.person, "relation": x.relation or None,
                             "reason": self.text(x.reason) if x.reason else None}) for x in p.possible]

    def person(self, p):
        f, clean = p.fm, self.text.clean
        tags = [str(t) for t in as_list(f.get("tags"))]
        return _drop_empty({
            "schema": "person/1", "id": p.id, "slug": self.slugs[p.id],
            "identifiers": _drop_empty({"gedcom_id": str(f.get("gedcom_id") or "").strip("@")}),
            "names": _drop_empty({"display": self.person_names[p.id],
                                  "home": [clean(x) for x in as_list(f.get("home_names"))],
                                  "aliases": [clean(x) for x in as_list(f.get("aliases"))],
                                  "surname_inferred": bool(f.get("surname_inferred")) or None}),
            "sex": p.sex,
            "born": _drop_empty({"date": date_json(p.born), "place": p.birth_place}),
            "died": _drop_empty({"date": date_json(p.died), "place": p.death_place}),
            "occupation": self.text(f["occupation"]) if f.get("occupation") else None,
            "occupation_tr": {k: self.text(v) for k, v in self.extras.occupation_tr(f["occupation"]).items()} or None
                             if f.get("occupation") else None,
            "relationships": self.relationships(p),
            "possible": self.possible(p),
            "research": _drop_empty({"priority": f.get("research_priority"),
                                     "lineage": [str(x) for x in as_list(f.get("lineage"))],
                                     "lineage_by_marriage": [str(x) for x in as_list(f.get("lineage_by_marriage"))],
                                     "direct_ancestor": "Прямой-предок" in tags or None}),
            "facts": [self.fact(x) for x in p.facts if not social_only(x.text)],
            "biography": self.biography(p.id),
            "stays": [_drop_empty({"place": place, "from": y0, "to": y1, "event": ev,
                                   "state": eras.translate(self.text.clean(era)) if era else None})
                      for y0, y1, ev, place, era in self.extras.stays(p.id)],
            "homes": self.homes(p.id),
            "media": self.media(p.id),
            "avatar": (self.media(p.id) or [None])[0],
            **self.life_photos(p.id),
            "documents": [_drop_empty({**x, "title": self.text.clean(x["title"]), "private": x["private"] or None,
                                       "titles": {k: self.text.clean(v) for k, v in x["titles"].items()} if x.get("titles") else None})
                          for x in self.extras.documents(p.id)],
            "sources": p.sources,
        }, keep=("relationships", "facts", "sources"))

    def biography(self, pid):
        b = self.extras.biography(pid)
        if not b:
            return None
        texts = {"ru": {"md": self.text(b["ru"])}}
        for lang, (md, ai, stale, rows, mem, rec, qs) in b["tr"].items():
            texts[lang] = _drop_empty({"md": self.text(md), "ai": ai or None, "stale": stale or None,
                                       "lifeline": self.lifeline(rows, ru=False), "memory": self.lifeline(mem, ru=False),
                                       "recollections": self.recollections(rec),
                                       "questions": self.text(qs) if qs else None})
        return _drop_empty({"file": b["file"], "lifeline": self.lifeline(b["lifeline"]),
                            "memory": self.lifeline(b.get("memory", [])),
                            "recollections": self.recollections(b.get("recollections", [])),
                            "questions": self.text(b["questions"]) if b.get("questions") else None, "texts": texts},
                           keep=("lifeline",))

    def recollections(self, items):
        """«Воспоминания» → JSON: название, кто вспоминает и откуда, рассказ (всё — через ту же очистку текста)."""
        return [_drop_empty({"title": self.text.clean(title), "by": self.text(by) if by else None, "text": self.text(text)})
                for title, by, text in items]

    def lifeline(self, rows, ru=True):
        """Строки таблицы «Линия жизни» → JSON. Дату разбираем только у русской: в переводе она словами того языка."""
        out = []
        for when, what, extra in rows:
            where = next((v for c, v in extra if WHERE_COL.match(c)), "")
            extra = [(c, v) for c, v in extra if not WHERE_COL.match(c)]
            try:
                d = date_json(dates.parse_ru(when)) if ru else None
            except dates.DateError:
                d = None
            # в колонке даты — только дата: без **жирного**, ⭐ и значков (правило — check_dates.py)
            # старый стиль из скобок — отдельно (date.os), в «when» только главная дата по новому
            shown = d["ru"] if d and d.get("os") else dates.clean(when)
            out.append(_drop_empty({"when": self.text.clean(shown), "date": d, "text": self.text(what),
                                    "where": self.text(where) if where.strip("—-? ") else None,
                                    "extra": [{"col": self.text.clean(c), "value": self.text(v)} for c, v in extra]}))
        return out

    def life_photos(self, pid):
        groups, other = self.extras.life_photos(pid)
        clean = self.text.clean
        return {"life_photos": [_drop_empty({"names": {k: clean(v) for k, v in g["names"].items()}, "place": g["place"],
                                             "album": g["album"], "photos": [self.photo(r) for r in g["photos"]]},
                                            keep=("photos",)) for g in groups],
                "life_photos_other": other}

    def media(self, pid):
        return [{"url": url, "kind": "photo", "private": private} for url, private in self.extras.media(pid)]

    # ---------- место и источник ----------

    def place(self, pl):
        own = pl.states or None
        states = own or states_of(pl, self.tree.places)
        src = None if own else next((x.id for x in self._up(pl) if x.states), None)
        return _drop_empty({
            "schema": "place/1", "id": pl.id, "slug": self.slugs[pl.id], "names": self.place_names[pl.id],
            "aliases": [self.text.clean(a) for a in pl.aliases], "type": pl.type or "locality", "real": pl.real,
            "coords": {"lat": pl.coords[0], "lng": pl.coords[1]} if pl.coords else None,
            "parent": pl.parent,
            "states": [_drop_empty({"date": date_json(s.date), "state": eras.translate(self.text.clean(s.label)), "main": s.main or None})
                       for s in states],
            "states_from": src,
            "people": self.people_at(pl.id),
            "who": [_drop_empty({"person": pid, "what": what, "events": [_drop_empty(
                {"what": k, "date": date_json(dates.card_or_none(d)) if d else None,
                 "text": self.text(t) if (t := _fact_gist(desc) if k == "pp_fact" else _gist(desc)) else None})
                for k, d, desc in self.extras.place_events(pl.id, pid)] or None}) for pid, what in self.extras.place_people(pl.id)],
            "mentions": self.extras.place_mentions(pl.id),
            "about": {**{k: self.text(v) for lang, (tb, _, _) in self.extras.place_tr(pl.id).items()
                         for k, v in about_of(tb).items() if k == lang},
                      **{k: self.text(v) for k, v in about_of(pl.body).items()}} or None,
            "inside": [x.id for x in sorted(self.tree.places.values(), key=lambda x: x.name) if x.parent == pl.id],
            "nearby": self.nearby(pl),
            "similar": self.similar(pl),
            "md": self.text(t) if (t := self.extras.place_text(pl.id)) else None,
            "tr": {lang: _drop_empty({"md": self.text(m) if (m := place_text_md(tb)) else None, "ai": ai or None,
                                      "stale": stale or None}) for lang, (tb, ai, stale) in self.extras.place_tr(pl.id).items()} or None,
            "house": self.house(pl),
            "residents": [_drop_empty({"person": r.person, "date": date_json(r.date), "what": r.what})
                          for r in self.tree.residents.get(pl.id, [])],
        }, keep=("real", "people"))

    # ---------- дом ----------

    def house_entry(self, pl):
        """Дом в общем списке — для раздела «Дома» на карте: {kind, from, to, residents} или None."""
        if pl.house is None:
            return None
        y0, y1 = self.house_years(pl.id)
        return _drop_empty({"kind": pl.house["kind"], "from": y0, "to": y1,
                            "residents": len(dict.fromkeys(r.person for r in self.tree.residents.get(pl.id, [])))},
                           keep=("residents",))

    def house(self, pl):
        """Свойства дома (cards/houses.py) и годы, когда в нём жили наши: {kind, built, gone, from, to} или None."""
        if pl.house is None:
            return None
        years = self.house_years(pl.id)
        return _drop_empty({"kind": pl.house["kind"], "built": date_json(pl.house["built"]),
                            "gone": date_json(pl.house["gone"]), "from": years[0], "to": years[1]})

    def house_years(self, place_id):
        """Первый и последний год, про который известно, что в доме жили наши (по датам жильцов); чего нет — None."""
        # «до 1943» (BEF) — только конец, «после 1956» (AFT) — только начало: иначе вышло бы, что жили один год
        rows = [r.date for r in self.tree.residents.get(place_id, []) if r.date and r.date.first]
        y0 = [d.first_year for d in rows if d.kind != "BEF"]
        y1 = [d.last_year for d in rows if d.kind != "AFT"]
        return (min(y0) if y0 else None, max(y1) if y1 else None)

    def homes(self, pid):
        """Дома человека по году: [{place, date, what}] — из тех же жильцов, что на странице дома."""
        rows = [(r.date, house, r.what) for house, rs in self.tree.residents.items() for r in rs if r.person == pid]
        rows.sort(key=lambda x: (x[0].sort_key() or "9999") if x[0] else "9999")
        return [_drop_empty({"place": house, "date": date_json(d), "what": what}) for d, house, what in rows]

    # Населённые пункты — то, что имеет смысл показывать «рядом»; дом, больница, участок кладбища — внутри своего города.
    SETTLEMENT = {"city", "town", "village", "locality", ""}
    NEAR_KM = 150

    def nearby(self, pl, limit=6):
        """Города и деревни не дальше NEAR_KM от места, кроме тех, в которые оно входит, и тех, что внутри него: [{place, km}]."""
        own = self._up_coords(pl)
        if not own or pl.type in ("country", "region", "river"):
            return []
        skip = {pl.id, *(x.id for x in self._up(pl))}
        out = []
        for x in self.tree.places.values():
            if x.id in skip or not x.coords or x.type not in self.SETTLEMENT or pl.id in {y.id for y in self._up(x)}:
                continue
            if (km := distance(own, x.coords)) <= self.NEAR_KM:
                out.append((km, x.name, x.id))
        return [{"place": i, "km": round(km)} for km, _, i in sorted(out)[:limit]]

    def similar(self, pl, limit=8):
        """Места того же рода внутри того же места выше (страны у стран, деревни Беларуси у деревни в Беларуси), ближние
        первыми; кто уже в «рядом» — не повторяем."""
        near = {n["place"] for n in self.nearby(pl)}
        own = self._up_coords(pl)
        kin = [x for x in self.tree.places.values()
               if x.id != pl.id and x.id not in near and x.parent == pl.parent and (x.type or "") == (pl.type or "")]
        kin.sort(key=lambda x: (distance(own, x.coords) if own and x.coords else math.inf, x.name))
        return [x.id for x in kin[:limit]]

    def place_folk(self, place_id):
        """Все, кто связан с местом и с местами внутри него (город → его дома и больницы): сначала те, кто там родился,
        жил, умер, потом упомянувшие его в биографии; с портретом — вперёд (их лица на плитке альбома)."""
        ids = [place_id, *self._inside_all(place_id)]
        folk = list(dict.fromkeys([pid for i in ids for pid, _ in self.extras.place_people(i)]
                                  + [pid for i in ids for pid in self.extras.place_mentions(i)]))
        face = {pid for pid in folk if any(not private for _, private in self.extras.media(pid)[:1])}
        return sorted(folk, key=lambda pid: pid not in face)  # сортировка устойчивая: внутри — прежний порядок

    def _inside_all(self, place_id):
        out, todo = [], [place_id]
        while todo:
            cur = todo.pop()
            kids = [x.id for x in self.tree.places.values() if x.parent == cur and x.id not in out]
            out += kids
            todo += kids
        return out

    def _up_coords(self, pl):
        """Координаты места, а нет своих — места выше (дом → город)."""
        return pl.coords or next((x.coords for x in self._up(pl) if x.coords), None)

    def _up(self, pl):
        """Места выше: деревня → район → страна."""
        seen = {pl.id}
        while pl.parent and pl.parent not in seen:
            pl = self.tree.places[pl.parent]
            seen.add(pl.id)
            yield pl

    def people_at(self, place_id):
        return [p.id for p in self.tree.people.values() if place_id in (p.birth_place, p.death_place)]

    def place_count(self, place_id):
        """Сколько людей связано с местом — размер точки на карте: родились, умерли, события и места в фактах (как «who»)."""
        return len(set(self.people_at(place_id)) | {pid for pid, _ in self.extras.place_people(place_id)})

    def source(self, s):
        return _drop_empty({
            "schema": "source/1", "id": s.id, "slug": self.slugs[s.id], "title": self.text.clean(s.title),
            "titles": {k: self.text.clean(v) for k, v in self.extras.source_titles(s.stem, s.title).items()} or None,
            "provenance": s.provenance, "type": s.type, "author": self.text.clean(s.author),
            "repository": self.text.clean(s.repository),
            "md": self.text(t) if (t := self.extras.source_text(s.stem)) else None,
            "audio": audio_source(s.fm) or None,
            "media": [{"url": u, "kind": "photo", "private": private} for u, private in self.extras.source_media(s.stem)],
            "people": [p.id for p in self.tree.people.values() if s.id in p.sources],
        }, keep=("people",))

    def doc(self, d):
        """Заметка проекта (расшифровка, полный текст находки, документ человека) — data/docs/<номер>.json"""
        if d.get("goto"):
            return {"schema": "doc/1", "id": d["id"], "goto": {"kind": d["goto"][0], "id": d["goto"][1]}}
        clean = self.text.clean
        return _drop_empty({
            "schema": "doc/1", "id": d["id"], "title": clean(d["title"]), "path": clean(d["path"]),
            "meta": {k: clean(v) for k, v in d.get("meta", {}).items() if v} or None,
            "people": d.get("people") or None,
            "media": [{"url": u, "kind": "photo", "private": private} for u, private in d.get("media", [])],
            "files": [{"name": clean(n), "url": u} for n, u in d.get("files", [])],
            "audio": d.get("audio") or None,
            "md": self.text(d["md"]) if d.get("md") and not d.get("audio") else None})

    # ---------- галерея ----------

    def photo(self, r):
        """Снимок из галереи → JSON: подписи — через очистку, эпоха — на языках."""
        clean, md = self.text.clean, self.text
        return _drop_empty({
            "url": r["url"], "thumb": r["thumb"], "year": r["year"], "year_txt": clean(r["year_txt"]),
            "desc": md(r["desc"]), "whose": md(r["whose"]), "exact": md(r["exact"]), "note": md(r["note"]),
            "source": md(r["source"]), "rights": clean(r["rights"]), "link": r["link"], "section": md(r["section"]),
            "era": eras.translate(clean(r["era"])) if r["era"] else None, "addr": r.get("addr"),
            "like": _drop_empty(r["like"]) if r.get("like") else None,
            "tr": {lang: {k: md(v) for k, v in fs.items() if v and k in ("desc", "whose", "exact", "note", "section")}
                   for lang, fs in self.extras.photo_tr(r).items()} or None})

    def gallery(self):
        clean = self.text.clean
        albums = [_drop_empty({"slug": a["slug"], "names": {k: clean(v) for k, v in a["names"].items()}, "kind": a["kind"],
                               "place": a["place"], "people": self.place_folk(a["place"]) if a["place"] else a.get("people") or None,
                               "about": {k: self.text(v) for k, v in a["about"].items()} if a.get("about") else None,
                               "photos": [self.photo(r) for r in a["photos"]]}, keep=("photos",))
                  for a in self.extras.gallery()]
        return {"schema": "gallery/1", "albums": albums}

    def research(self):
        """«Что ещё искать» — та же очистка и те же ссылки по номеру, что у текстов источников; нет файла — None."""
        r = self.extras.research()
        if not r or not r.get("md"):
            return None
        return _drop_empty({"schema": "research/1", "md": self.text(r["md"]), "updated": r.get("updated")})

    def review(self):
        """«Сверка»: отмеченные пары (maybe_*) и найденные автоматически (possible.auto) — карточки рядом и команды
        решений. Пары с проверенным «нет» не попадают (possible.pairs и possible.auto их пропускают)."""
        import possible

        def side(p):
            return _drop_empty({"person": p.id, "born": date_json(p.born), "birth_place": p.birth_place,
                                "died": date_json(p.died), "death_place": p.death_place, "parents": p.father + p.mother,
                                "sources": len(set(p.sources + [r.source for f in p.facts for r in f.refs]))},
                               keep=("parents", "sources"))
        pairs = [_drop_empty({"source": "marked", "type": x.kind, "relation": x.relation or None, "a": side(a), "b": side(b),
                              "reason": self.text(x.reason) if x.reason else None,
                              "commands": possible.commands(a, b, x.kind)}) for a, b, x in possible.pairs(self.tree)]
        pairs += [{"source": "auto", "type": "same", "a": side(a), "b": side(b), "why": why,
                   "commands": possible.commands(a, b, marked=False)} for a, b, why, _ in possible.auto(self.tree)]
        ruled = {frozenset((p.id, i)) for p in self.tree.people.values() for _, i in p.ruled_out}
        return {"schema": "review/1", "pairs": pairs, "ruled_out": len(ruled)}

    # ---------- общий список ----------

    def branches(self):
        """Ветки рода (lineage) по числу людей, «Без ветки» — последней. Людей с неизвестным именем не считаем —
        в списках их нет (в дереве остаются)."""
        count = {}
        for p in self.tree.people.values():
            if not UNKNOWN.match(p.name):
                for ln in as_list(p.fm.get("lineage")) or [NO_BRANCH]:
                    count[str(ln)] = count.get(str(ln), 0) + 1
        order = sorted(count, key=lambda k: (k == NO_BRANCH, -count[k]))
        return [{"key": k, "slug": slugify(latin(k, "en")), "names": {"ru": k, "en": latin(k, "en"), "pl": latin(k, "pl")},
                 "people": count[k]} for k in order]

    def index(self):
        t = self.tree
        start = next((p.id for p in t.people.values() if p.fm.get("gedcom_id") == HOME_GEDCOM), next(iter(t.people)))
        kin = kinship_levels(t)
        return {
            "schema": "index/1", "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "start": start,
            "people": [_drop_empty({"id": p.id, "slug": self.slugs[p.id], "names": self.person_names[p.id], "sex": p.sex,
                                    "life": self.life[p.id], "lineage": [str(x) for x in as_list(p.fm.get("lineage"))],
                                    "parents": p.father + p.mother, "spouses": p.spouses, "children": p.children,
                                    "avatar": next((u for u, private in self.extras.media(p.id)[:1] if not private), None),
                                    "stats": self.extras.stats(p.id), **(self.extras.card(p.id) or {}),
                                    "kinship": kin[p.id][0], "kinship_by": kin[p.id][1],
                                    "unknown": bool(UNKNOWN.match(p.name)) or None},
                                   keep=("life", "parents", "spouses", "children"))
                       for p in t.people.values()],
            "divorces": {"|".join(sorted(k)): str(v or "") for k, v in t.divorces.items()},
            "branches": self.branches(),
            "places": [_drop_empty({"id": pl.id, "slug": self.slugs[pl.id], "names": self.place_names[pl.id],
                                    "lat": pl.coords[0] if pl.coords else None, "lng": pl.coords[1] if pl.coords else None,
                                    "people": self.place_count(pl.id), "type": pl.type or "locality", "parent": pl.parent,
                                    "house": self.house_entry(pl)}, keep=("people",))
                       for pl in t.places.values()],
            "sources": [_drop_empty({"id": s.id, "slug": self.slugs[s.id], "title": self.text.clean(s.title),
                                     "titles": {k: self.text.clean(v) for k, v in self.extras.source_titles(s.stem, s.title).items()} or None,
                                     "provenance": s.provenance}) for s in t.sources.values()],
        }

    def files(self):
        """→ {путь от data/: объект}"""
        out = {"index.json": self.index()}
        if ui := self.extras.ui():
            out["ui.json"] = {"schema": "ui/1", **ui}
        out["gallery.json"] = self.gallery()
        if research := self.research():
            out["research.json"] = research
        out["review.json"] = self.review()
        if progress := self.extras.progress(self.tree):
            out["progress.json"] = progress
        out |= {f"people/{p.id}.json": self.person(p) for p in self.tree.people.values()}
        out |= {f"places/{p.id}.json": self.place(p) for p in self.tree.places.values()}
        out |= {f"sources/{s.id}.json": self.source(s) for s in self.tree.sources.values()}
        while d := self.extras.next_doc():  # заметки, на которые дали ссылку тексты выше; их текст тянет новые
            out[f"docs/{d['id']}.json"] = self.doc(d)
        return out


ICLOUD_COPY = re.compile(r" \d+(\.\w+)?$")  # «people 2», «index 2.json» — копии, которые оставляет iCloud


def write(tree, folder, extras=None):
    """Привести data/ к выгрузке: изменившиеся файлы переписать, лишние и копии iCloud удалить. Папку целиком не стираем:
    «Документы» синхронизирует iCloud, и стёртая и тут же созданная заново папка становится «people 2», а своя — пустой
    (28.09.2026). → сколько файлов."""
    import shutil
    files = {rel: json.dumps(obj, ensure_ascii=False, separators=(",", ":")) for rel, obj in Export(tree, extras).files().items()}
    folder.mkdir(parents=True, exist_ok=True)
    for p in sorted(folder.rglob("*"), key=lambda p: -len(p.parts)):
        rel = p.relative_to(folder).as_posix()
        if ICLOUD_COPY.search(p.name) or (p.is_file() and rel not in files):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for rel, text in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            p.write_text(text, encoding="utf-8")
    return len(files)
