"""load() — всё дерево разом, в порядке зависимостей: источники → места → люди → события → биографии."""
import dates
import paths
from .biographies import read_biographies
from .houses import residents
from .model import Tree
from .notes import as_list, link_target, read_note, year
from .people import read_people
from .places import read_places
from .sources import read_sources


def load(root=paths.TREE, research=None):
    """research — папка 3_research, где биографии; по умолчанию — если читаем дерево проекта (в тестах — нет)."""
    research = research or (paths.RESEARCH if root == paths.TREE else None)
    problems = []
    sources, source_by_name = read_sources(root / "sources", problems)
    places, place_by_name = read_places(root / "places", problems)
    people, stems = read_people(root / "people", place_by_name, source_by_name, sources, problems)
    events = [n.fm for n in map(read_note, sorted((root / "events").glob("*.md"))) if n.fm.get("cr_type") == "event"]
    divorces = {}
    for e in events:
        if e.get("event_type") == "divorce":
            pair = [stems[t] for t in {link_target(x) for x in as_list(e.get("persons"))} if t in stems]
            if len(pair) == 2:
                divorces[frozenset(pair)] = year(e.get("date"))
    order_family(people, stems, events)
    bios = read_biographies(research, people, problems) if research else {}
    tree = Tree(people, places, sources, events, divorces, problems, bios)
    tree.residents = residents(places, people, events, problems)
    return tree


LATE = (9999, 0, 0)  # даты нет — в конец, между собой в прежнем порядке


def _key(gd):
    return gd.first.key() if gd and gd.first else LATE


def order_family(people, stems, events):
    """Дети — по дате рождения, супруги — по порядку браков (дата брака, иначе рождение старшего общего ребёнка).
    Этот порядок видит посетитель: дерево ставит детей слева направо, а номер брака красит линии второго брака."""
    wed = {}  # пара → самая ранняя дата брака
    for e in events:
        if e.get("event_type") != "marriage":
            continue
        pair = frozenset(stems[t] for t in {link_target(x) for x in as_list(e.get("persons"))} if t in stems)
        try:
            k = _key(dates.parse_card(e.get("date")))
        except dates.DateError:
            k = LATE
        if len(pair) == 2:
            wed[pair] = min(wed.get(pair, LATE), k)
    for p in people.values():
        p.children.sort(key=lambda c: _key(people[c].born))

    def mar(p, s):
        k = wed.get(frozenset((p.id, s)), LATE)
        if k != LATE:
            return k
        common = [_key(people[c].born) for c in p.children if c in people[s].children]
        return min(common, default=LATE)
    for p in people.values():
        if len(p.spouses) > 1:
            p.spouses.sort(key=lambda s: mar(p, s))
