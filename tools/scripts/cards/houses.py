"""Дома — места, где люди жили: «Лесогорск — Садовая, 12», хата деда в Вербичах, барак у моста.

Дом — обычная карточка места (place_type: house), поэтому он сразу на карте, с фото, «Государствами по годам» города и
заметками. Своё у дома — что это за жильё и годы самого дома (свойства карточки), а кто в нём жил — события
«место жительства» (event_type: residence, place: [[дом]]) с датой и источником: одна запись — одна правда,
дом жильцов списком не держит. Родился в доме (birth_place: [[дом]]) — тоже житель.

    place_type: house
    parent_place: "[[Брест]]"       # обязательно: дом всегда внутри города или деревни
    house_kind: private             # private — свой дом · apartment — квартира · barrack — барак · dorm — общежитие · hut — хата, изба
    built: ABT 1956                 # когда построен или собран (GEDCOM, как born) — если известно
    gone: 1944                      # когда дома не стало: снесён, сгорел, разобран (как именно — в «## Что стало»)

Разделы — «## О месте» (что за дом и чем важен), «## Как был устроен» (комнаты, из чего), «## Что стало».
"""
from dataclasses import dataclass

import dates
from .model import Problem
from .notes import as_list, link_target

HOUSE = "house"
KINDS = ("private", "apartment", "barrack", "dorm", "hut")


@dataclass
class Resident:
    person: str               # cr_id
    date: "dates.GDate | None"  # когда жил — дата события; у рождения — дата рождения
    what: str                 # ev_residence | pp_born


def house_info(pl, problems):
    """Свойства дома из карточки → {"kind", "built", "gone"} (пустые — None); не по правилам — в problems."""
    f, card = pl.fm, pl.card
    kind = str(f.get("house_kind") or "") or None
    if kind and kind not in KINDS:
        problems.append(Problem(card, 1, f"house_kind: {kind} — такого вида жилья нет ({', '.join(KINDS)})"))
        kind = None
    out = {"kind": kind}
    for key in ("built", "gone"):
        try:
            out[key] = dates.parse_card(f.get(key))
        except dates.DateError as e:
            problems.append(Problem(card, 1, f"{key}: {e}"))
            out[key] = None
    if not f.get("parent_place"):
        problems.append(Problem(card, 1, "у дома нет parent_place — в каком он городе или деревне"))
    return out


def residents(places, people, events, problems):
    """→ {cr_id дома: [Resident]} по событиям «место жительства» и местам рождения, по году. Дом, в котором никто не
    жил, — предупреждение: значит, событие не заведено, и на сайте дом пустой."""
    by_stem = {p.stem: p.id for p in people.values()}
    by_name = {k: pl.id for pl in places.values() for k in (pl.stem, pl.name, *pl.aliases)}
    out = {pid: [] for pid, pl in places.items() if pl.type == HOUSE}
    for e in events:
        if e.get("event_type") != "residence" or not e.get("place"):
            continue
        house = by_name.get(link_target(e["place"]))
        if house not in out:
            continue
        d = dates.card_or_none(e.get("date"))
        who = [link_target(x) for x in as_list(e.get("persons")) or as_list(e.get("person"))]
        for stem in dict.fromkeys(who):
            if stem in by_stem:
                out[house].append(Resident(by_stem[stem], d, "ev_residence"))
    for p in people.values():
        if p.birth_place in out and p.id not in {r.person for r in out[p.birth_place]}:
            out[p.birth_place].append(Resident(p.id, p.born, "pp_born"))
    for house, rows in out.items():
        rows.sort(key=lambda r: (r.date.sort_key() or "9999") if r.date else "9999")
        if not rows:
            pl = places[house]
            problems.append(Problem(pl.card, 1, "в доме никто не жил — заведите событие «место жительства» "
                                                         "(event_type: residence, place: [[" + pl.stem + "]])",
                                    level="warning"))
    return out
