"""Карточки мест и их «Государства по годам»."""
import re

import dates
from .houses import HOUSE, house_info
from .model import Place, Problem, State
from .notes import N, card_path, as_list, link_target, read_note, section

# У этих мест нет своих государств — они в любом случае внутри чего-то (улица, дом, участок кладбища) или вне границ
NO_STATES = {"river"}


def parse_states(body, note, card, problems):
    """«- 1921–1939 — **Польша** (II Речь Посполитая); 1941–1944 — оккупация» → [State, State].
    Кусок после «;» без «годы — » — продолжение подписи той же эпохи, а не новая эпоха."""
    text, start = section(body, "Государства по годам", level=2)
    states = []
    if start < 0:
        return states
    for m in re.finditer(r"^- (.+)$", text, re.M):
        line_no = note.line_of(start + m.start())
        for i, seg in enumerate(m[1].split("; ")):
            mm = re.match(r"(.+?) — (.+)", seg)
            date = None
            if mm:
                try:
                    date = dates.parse_ru(mm[1])
                except dates.DateError:
                    date = None
            if date is None:
                if i == 0 or not states:
                    problems.append(Problem(card, line_no, "эпоха не в виде «годы — государство» (1921–1939 — Польша, до 1915 — …, "
                                                           "с 1991 — …)", m[1]))
                else:
                    states[-1].label += "; " + seg.strip()
                continue
            label = mm[2].strip()
            states.append(State(date, re.sub(r"\*\*(.+?)\*\*", r"\1", label).strip(), "**" in label))
    return states


# «О месте» — вводный текст страницы места: что это, где, чем важно для семьи. Русский — «## О месте»; перевод — тем же
# разделом с заголовком на языке перевода (нет перевода — сайт показывает русский).
ABOUT = {"ru": "О месте", "pl": "O miejscu", "es": "Sobre el lugar", "en": "About the place"}


def about_of(body):
    """→ {язык: текст раздела «О месте»} — только непустые."""
    out = {}
    for lang, title in ABOUT.items():
        text = section(body, title, level=2)[0].strip()
        if text:
            out[lang] = text
    return out


def text_of(body):
    """Текст места на странице: без заголовка «# …», «О месте» на любом языке (оно — отдельным блоком), «Государств по
    годам» и блоков Charted Roots. Тот же разбор — у русской карточки и у её перевода (translations/<язык>/places/)."""
    import re
    body = re.sub(r"\A\s*# .*\n", "", body, count=1)
    titles = "|".join(["Государства по годам", *ABOUT.values()])
    body = re.sub(rf"^## ({titles})\n.*?(?=^## |\Z)", "", body, flags=re.S | re.M)
    body = re.sub(r"^```.*?^```[ \t]*$", "", body, flags=re.S | re.M)
    return body.strip() or None


def states_of(pl, places):
    """Эпохи места: свои, а если своих нет — ближайшего места выше (деревня → район → страна)."""
    seen = set()
    while pl and pl.id not in seen:
        if pl.states:
            return pl.states
        seen.add(pl.id)
        pl = places.get(pl.parent)
    return []


def read_places(folder, problems):
    """→ (cr_id → Place, имя или другое написание → cr_id). Место, которому эпохи не достаются ниоткуда, — ошибка: у людей
    оттуда пустые «Места и эпохи» (CLAUDE.md, «Ошибки»: новая страна без «Государств по годам»)."""
    places, by_name, parents = {}, {}, {}
    for p in sorted(folder.glob("*.md")):
        note, card = read_note(p), card_path(p)
        f = note.fm
        if f.get("cr_type") != "place" or not f.get("cr_id"):
            continue
        c = f.get("coordinates") or {}
        coords = (float(c["lat"]), float(c["long"])) if c.get("lat") is not None and c.get("long") is not None else None
        pl = Place(f["cr_id"], note.stem, N(str(f.get("name") or note.stem)), str(f.get("place_type") or ""),
                   f.get("place_category", "real") == "real", [N(str(a)) for a in as_list(f.get("aliases"))], None, coords,
                   parse_states(note.body, note, card, problems), f, note.body, card)
        if pl.type == HOUSE:
            pl.house = house_info(pl, problems)
        places[pl.id] = pl
        parents[pl.id] = (f.get("parent_place"), card)
        for k in [pl.stem, pl.name, *pl.aliases]:
            by_name.setdefault(k, pl.id)
    for pid, (par, card) in parents.items():
        if par:
            places[pid].parent = by_name.get(link_target(par))
            if not places[pid].parent:
                problems.append(Problem(card, 1, f"parent_place {par} — нет такой карточки места"))
    for pl in places.values():
        if not states_of(pl, places) and pl.type not in NO_STATES:
            problems.append(Problem(parents[pl.id][1], 1,
                                    "эпох нет ни своих («## Государства по годам»), ни у мест выше (parent_place) — у людей отсюда "
                                    "пустые «Места и эпохи»"))
    return places, by_name
