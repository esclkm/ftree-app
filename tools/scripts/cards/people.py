"""Карточки людей и связи между ними."""
import dates
from . import layout, possible
from .facts import read_facts
from .model import Person, Problem
from .notes import N, card_path, as_list, link_target, read_note

SEX = {"male": "M", "female": "F"}
# kinship — насколько связь человека с деревом доказана (шкала проекта; на сайте — цвет рамки карточки в дереве)
KINSHIP = {"доказано": "proven", "вероятно": "likely", "возможно": "possible", "маловероятно": "unlikely",
           "не родня": "no"}


def _date(f, key, card, problems):
    try:
        return dates.parse_card(f.get(key))
    except dates.DateError as e:
        problems.append(Problem(card, 1, f"{key}: {e}"))
        return None


def _place(f, key, place_by_name, card, problems):
    if not f.get(key):
        return None
    pid = place_by_name.get(link_target(f[key]))
    if not pid:
        problems.append(Problem(card, 1, f"{key}: {f[key]} — нет такой карточки места"))
    return pid


def read_people(folder, place_by_name, source_by_name, sources, problems):
    people, stems, card_of = {}, {}, {}
    for p in sorted(folder.glob("*.md")):
        note, card = read_note(p), card_path(p)
        f = note.fm
        if not f.get("cr_id"):
            continue
        if f.get("sex") not in SEX:
            problems.append(Problem(card, 1, f"sex «{f.get('sex')}» — только male или female"))
        if f.get("kinship") and str(f["kinship"]).strip() not in KINSHIP:
            problems.append(Problem(card, 1, f"kinship «{f['kinship']}» — только: {', '.join(KINSHIP)}"))
        src = []
        for s in as_list(f.get("sources")):
            sid = source_by_name.get(link_target(s))
            if sid:
                src.append(sid)
            else:
                problems.append(Problem(card, 1, f"sources: {s} — нет такой карточки источника"))
        person = Person(
            f["cr_id"], note.stem, N(str(f.get("name") or note.stem)), SEX.get(f.get("sex"), "M"),
            _date(f, "born", card, problems), _date(f, "died", card, problems),
            _place(f, "birth_place", place_by_name, card, problems), _place(f, "death_place", place_by_name, card, problems),
            [], [], [], [], src, read_facts(note, card, source_by_name, sources, problems), f, note.body)
        problems.extend(layout.check(note, card))   # разделы — по образцу (3_research/templates/Карточка человека — устройство.md)
        people[person.id] = person
        stems[person.stem] = person.id
        card_of[person.id] = card
    _link(people, stems)
    possible.read(people, stems, problems, card_of)
    return people, stems


def _link(people, stems):
    """Связь — по номеру (father_id …), а если номера нет — по имени. Связи бывают записаны только с одной стороны —
    достраиваем обратные (как всегда делал сайт)."""
    def ids(f, key):
        found = [i for i in as_list(f.get(f"{key}_id")) if i in people]
        return found or [stems[t] for t in map(link_target, as_list(f.get(key))) if t in stems]

    for d in people.values():
        d.father, d.mother = ids(d.fm, "father")[:1], ids(d.fm, "mother")[:1]
        d.spouses, d.children = ids(d.fm, "spouse"), ids(d.fm, "children")
    for d in people.values():
        for pid in d.father + d.mother:
            if d.id not in people[pid].children:
                people[pid].children.append(d.id)
        for sid in d.spouses:
            if d.id not in people[sid].spouses:
                people[sid].spouses.append(d.id)
        for cid in d.children:
            c = people[cid]
            side = c.father if d.sex == "M" else c.mother
            if not side:
                side.append(d.id)
