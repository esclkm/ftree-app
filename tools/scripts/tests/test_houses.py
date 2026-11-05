"""Дома (cards/houses.py) и открытый адрес дома (site_data/privacy.py, address_public) на выдуманном дереве."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from site_data.privacy import Privacy  # noqa: E402
import tempfile  # noqa: E402
import cards  # noqa: E402
from test_cards import write  # noqa: E402


def fact_tree(places_extra=None):
    """Дерево: одна деревня и один человек, плюс дома из places_extra (своё, чтобы не зависеть от чужих имён)."""
    root = Path(tempfile.mkdtemp())
    write(root / "sources", "Аудио 04 — дед Прокоп", """
        cr_type: source
        cr_id: src-001-aaa-001
        title: "Аудио 04 — дед Прокоп"
        origin: "семья"
        """)
    write(root / "places", "Вербичи", """
        cr_type: place
        cr_id: plc-001-aaa-001
        name: Вербичи
        place_type: village
        """, "## Государства по годам\n\n- до 1915 — Российская империя\n- 1921–1939 — **Польша** (II Речь Посполитая)\n"
             "- 1939–1991 — СССР (БССР); 1941–1944 — немецкая оккупация; фронт прошёл дважды\n- с 1991 — Беларусь\n")
    for name, (fm, body) in (places_extra or {}).items():
        write(root / "places", name, fm, body)
    write(root / "people", "Прокоп", """
        cr_id: ppl-001-aaa-001
        name: Прокоп
        sex: male
        born: 1902
        birth_place: "[[Вербичи]]"
        sources:
          - "[[Аудио 04 — дед Прокоп]]"
        """)
    (root / "events").mkdir()
    return cards.load(root)

HOUSE = ("""
    cr_type: place
    cr_id: hse-001-aaa-001
    name: Вербичи — хата Прокопа
    place_type: house
    house_kind: hut
    parent_place: "[[Вербичи]]"
    gone: BET 1941 AND 1943
    """, "## О месте\n\nХата.\n")


def with_event(events, title, persons, date):
    """Событие «место жительства» в этом доме."""
    events.mkdir(parents=True, exist_ok=True)
    ps = "".join(f'\n  - "[[{p}]]"' for p in persons)
    (events / f"{title}.md").write_text(f"---\ncr_type: event\ncr_id: evt-001-aaa-001\nevent_type: residence\ndate: {date}\n"
                                        f'persons:{ps}\nplace: "[[Вербичи — хата Прокопа]]"\n---\n', encoding="utf-8")


class Houses(unittest.TestCase):
    def test_house_without_residents_warns(self):
        t = fact_tree(places_extra={"Вербичи — хата Прокопа": HOUSE})
        self.assertEqual(t.errors, [])
        h = t.places["hse-001-aaa-001"]
        self.assertEqual(h.house["kind"], "hut")
        self.assertEqual(h.house["gone"].ru(), "между 1941 и 1943")
        self.assertIn("никто не жил", " ".join(p.message for p in t.problems if p.level == "warning"))

    def test_residents_from_events(self):
        t = fact_tree(places_extra={"Вербичи — хата Прокопа": HOUSE})
        root = Path(t.places["hse-001-aaa-001"].card).parents[1]  # карточка лежит в <дерево>/places/
        with_event(root / "events", "Жил в хате", ["Прокоп"], "FROM 1920 TO 1941")
        t = cards.load(root)
        rs = t.residents["hse-001-aaa-001"]
        self.assertEqual([(r.person, r.date.ru(), r.what) for r in rs], [("ppl-001-aaa-001", "1920–1941", "ev_residence")])
        self.assertFalse([p for p in t.problems if "никто не жил" in p.message])

    def test_bad_kind_and_no_parent(self):
        fm = HOUSE[0].replace("house_kind: hut", "house_kind: castle").replace('    parent_place: "[[Вербичи]]"\n', "")
        t = fact_tree(places_extra={"Вербичи — хата Прокопа": (fm, "")})
        msgs = " ".join(p.message for p in t.errors)
        self.assertIn("castle", msgs)
        self.assertIn("parent_place", msgs)


class PublicAddress(unittest.TestCase):
    def test_only_the_open_house_keeps_its_number(self):
        p = Privacy(["Гродно — Луговая, 5", "Лесогорск — Садовая, 12"], ["Гродно — Луговая, 5"])
        self.assertEqual(p.text("умерла дома, на Луговой, 5, на кухне"), "умерла дома, на Луговой, 5, на кухне")
        self.assertEqual(p.text("г. Гродно, ул. Луговая, 5"), "г. Гродно, ул. Луговая, 5")
        self.assertEqual(p.text("соседи с Луговой, 12"), "соседи с Луговой")
        self.assertEqual(p.text("на Садовой, 12-34"), "на Садовой")

    def test_closed_by_default(self):
        p = Privacy(["Гродно — Луговая, 5"])
        self.assertEqual(p.text("на Луговой, 5"), "на Луговой")


if __name__ == "__main__":
    unittest.main()
