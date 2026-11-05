"""Тесты чтения карточек (пакет cards) на выдуманном дереве. Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cards  # noqa: E402

SRC = "Аудио 04 — дед Вавила"


def write(folder, name, fm, body=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(f"---\n{textwrap.dedent(fm).strip()}\n---\n{textwrap.dedent(body)}", encoding="utf-8")


def fact_tree(*lines, places_extra=None):
    """Дерево: один источник, одна деревня, один человек с этими строками фактов."""
    root = Path(tempfile.mkdtemp())
    write(root / "sources", SRC, f"""
        cr_type: source
        cr_id: src-001-aaa-001
        title: "{SRC}"
        origin: "семья"
        """)
    write(root / "places", "Кленовка", """
        cr_type: place
        cr_id: plc-001-aaa-001
        name: Кленовка
        place_type: village
        """, "## Государства по годам\n\n- до 1915 — Российская империя\n- 1921–1939 — **Польша** (II Речь Посполитая)\n"
             "- 1939–1991 — СССР (БССР); 1941–1944 — немецкая оккупация; фронт прошёл дважды\n- с 1991 — Беларусь\n")
    for name, (fm, body) in (places_extra or {}).items():
        write(root / "places", name, fm, body)
    write(root / "people", "Вавила", """
        cr_id: ppl-001-aaa-001
        name: Вавила
        sex: male
        born: 1902
        birth_place: "[[Кленовка]]"
        sources:
          - "[[Аудио 04 — дед Вавила]]"
        """, ("## Факты и заметки\n\n### Факты (с источником)\n\n" + "\n".join(lines) + "\n") if lines else "")
    (root / "events").mkdir()
    return cards.load(root)


class Facts(unittest.TestCase):
    def test_full_line(self):
        t = fact_tree(f"- **1944 (осень, поздняя), 13 лет:** беженство — *источник: [[{SRC}]], 11:14–11:54; [[{SRC}]], "
                      f"фото [[Вавила_1944.jpg]] · уверенность: низкая (вывод проекта: по возрасту)*")
        self.assertEqual(t.errors, [])
        f = t.people["ppl-001-aaa-001"].facts[0]
        self.assertEqual(f.date.ru(), "1944 (осень, поздняя)")
        self.assertEqual(f.label, "13 лет")
        self.assertEqual([r.locator for r in f.refs], ["11:14–11:54", "фото [[Вавила_1944.jpg]]"])
        self.assertEqual((f.confidence, f.provenance, f.reasoning), ("low", "inference", "вывод проекта: по возрасту"))

    def test_several_places_in_one_source(self):
        # «;» внутри одного источника — места в нём; перед новой ссылкой — следующий источник
        t = fact_tree(f"- **рождение:** 1900 — *источник: [[{SRC}]], 02:20; 24:56–25:30; [[{SRC}]], стр. 3 "
                      f"· уверенность: обычная*",
                      f"- **смерть:** 1990 — *источник: [[{SRC}]] (Павел, 15.09.2026; записано в [[{SRC}]]) "
                      f"· уверенность: обычная*")
        self.assertEqual(t.errors, [])
        a, b = t.people["ppl-001-aaa-001"].facts
        self.assertEqual([r.locator for r in a.refs], ["02:20; 24:56–25:30", "стр. 3"])
        self.assertEqual(len(b.refs), 2)

    def test_label_without_date(self):
        t = fact_tree(f"- **Занятие:** машинист — *источник: [[{SRC}]] · уверенность: высокая*")
        f = t.people["ppl-001-aaa-001"].facts[0]
        self.assertEqual((f.date, f.label, f.provenance, f.confidence), (None, "Занятие", "family", "high"))

    def assertProblem(self, line, words):
        t = fact_tree(line)
        self.assertEqual(len(t.errors), 1, t.problems)
        self.assertIn(words, t.errors[0].message)
        self.assertEqual(t.people["ppl-001-aaa-001"].facts, [])

    def test_bad_date(self):
        self.assertProblem(f"- **~1971:** школа — *источник: [[{SRC}]] · уверенность: обычная*", "дата в подписи")

    def test_source_in_words(self):
        self.assertProblem("- **Занятие:** врач — *источник: web 2026-06-27 · уверенность: обычная*", "не ссылка на карточку")

    def test_unknown_source(self):
        self.assertProblem("- **Занятие:** врач — *источник: [[Нет такой]] · уверенность: обычная*", "нет такой карточки источника")

    def test_no_confidence(self):
        self.assertProblem(f"- **Занятие:** врач — *источник: [[{SRC}]]*", "уверенность")

    def test_facts_heading_of_wrong_level_is_an_error(self):
        root = Path(tempfile.mkdtemp())
        write(root / "people", "Евстафий", """
            cr_id: ppl-002-aaa-002
            name: Евстафий
            sex: male
            """, "## Факты (с источником)\n\n- **Смерть:** 1906 — *источник: [[Нет]] · уверенность: высокая*\n")
        for folder in ("sources", "places", "events"):
            (root / folder).mkdir()
        t = cards.load(root)
        self.assertTrue(any("уровня ###" in p.message for p in t.errors), t.errors)

    def test_broken_line(self):
        self.assertProblem(f"- **год 1983 — точно** — *источник: [[{SRC}]] · уверенность: высокая*", "не по формату")


class Places(unittest.TestCase):
    def test_states(self):
        t = fact_tree()
        st = t.places["plc-001-aaa-001"].states
        self.assertEqual([s.date.ru() for s in st], ["до 1915", "1921–1939", "1939–1991", "1941–1944", "с 1991"])
        self.assertEqual((st[1].label, st[1].main), ("Польша (II Речь Посполитая)", True))
        self.assertEqual(st[3].label, "немецкая оккупация; фронт прошёл дважды")  # хвост без «годы —» — продолжение
        self.assertEqual(t.people["ppl-001-aaa-001"].birth_place, "plc-001-aaa-001")

    def test_place_without_states(self):
        t = fact_tree(places_extra={"Москва": ("cr_type: place\ncr_id: plc-002-aaa-002\nname: Москва\nplace_type: city", "")})
        self.assertEqual(len(t.errors), 1)
        self.assertIn("эпох нет", t.errors[0].message)

    def test_place_inherits_states(self):
        t = fact_tree(places_extra={"Лужки": ('cr_type: place\ncr_id: plc-003-aaa-003\nname: Лужки\n'
                                                   'place_type: village\nparent_place: "[[Кленовка]]"', "")})
        self.assertEqual(t.errors, [])


class PlacePage(unittest.TestCase):
    """Страница места: «О месте», что внутри, что рядом, что похоже (site_data/export.py)."""

    def tree(self):
        pl = lambda i, name, kind, lat, lng, extra="": (  # noqa: E731
            f'cr_type: place\ncr_id: plc-{i}\nname: {name}\nplace_type: {kind}\nparent_place: "[[Кленовка]]"\n'
            f"coordinates:\n  lat: {lat}\n  long: {lng}{extra}", "")
        return fact_tree(places_extra={
            "Вербичи": (pl("010-aaa-010", "Вербичи", "village", 52.617, 24.188)[0],
                       "# Вербичи\n\n## О месте\n\nДеревня рода.\n\n## O miejscu\n\nOsada rodu.\n\n## Другое\n\nтекст\n"),
            "Лесогорск": pl("011-aaa-011", "Лесогорск", "town", 52.555, 24.215),
            "Простоквашино": pl("012-aaa-012", "Простоквашино", "village", 52.658, 24.171),
            "Минск": pl("013-aaa-013", "Минск", "city", 53.9, 27.56),
            "Вербичи — дом": ('cr_type: place\ncr_id: plc-014-aaa-014\nname: Вербичи — дом\nplace_type: house\n'
                             'parent_place: "[[Вербичи]]"', ""),
        })

    def test_about(self):
        from cards.places import about_of
        body = self.tree().places["plc-010-aaa-010"].body
        self.assertEqual(about_of(body), {"ru": "Деревня рода.", "pl": "Osada rodu."})

    def test_nearby_similar_inside(self):
        from site_data.export import Export
        e = Export(self.tree())
        ver = e.place(e.tree.places["plc-010-aaa-010"])
        self.assertEqual(ver["about"]["ru"], "Деревня рода.")
        self.assertEqual(ver["inside"], ["plc-014-aaa-014"])
        self.assertEqual([n["place"] for n in ver["nearby"]], ["plc-012-aaa-012", "plc-011-aaa-011"])  # Минск — за 150 км
        self.assertEqual(ver["nearby"][1]["km"], 7)
        self.assertNotIn("similar", ver)  # другая деревня под Кленовкой — Простоквашино, она уже «рядом»
        house = e.place(e.tree.places["plc-014-aaa-014"])
        self.assertNotIn("plc-010-aaa-010", [n["place"] for n in house["nearby"]])  # своя деревня — не «рядом»


class Biographies(unittest.TestCase):
    """Биография зовётся как карточка + « — биография» и носит номера человека в свойствах (cards/biographies.py)."""

    def tree(self, bio_fm, name="Вавила", line=True):
        root = Path(tempfile.mkdtemp())
        rel = f"{root.name}/tree/biographies/{name} — биография.md"
        write(root / "tree" / "people", "Вавила", """
            cr_id: ppl-001-aaa-001
            name: Вавила
            sex: male
            gedcom_id: I16
            """, f"## Факты и заметки\n\n**Биография:** [[{rel}]]\n" if line else "")
        for d in ("sources", "places", "events"):
            (root / "tree" / d).mkdir(parents=True)
        bio = root / "tree" / "biographies"
        bio.mkdir(parents=True)
        (bio / f"{name} — биография.md").write_text((f"---\n{bio_fm}\n---\n" if bio_fm else "") + "# Вавила\n", encoding="utf-8")
        import cards.notes as notes
        old = notes.paths.ROOT
        notes.paths.ROOT = root.parent  # путь биографии — от «корня проекта»
        try:
            return cards.load(root / "tree", research=root)
        finally:
            notes.paths.ROOT = old

    def test_no_ids(self):
        t = self.tree("")
        self.assertEqual(sorted(p.message.split(" ")[0] for p in t.errors), ["gedcom_id", "нет"])

    def test_ids_ok(self):
        self.assertEqual(self.tree("person_id: ppl-001-aaa-001\ngedcom_id: I16").errors, [])

    def test_wrong_gedcom(self):
        t = self.tree("person_id: ppl-001-aaa-001\ngedcom_id: I99")
        self.assertEqual(len(t.errors), 1)
        self.assertIn("I16", t.errors[0].message)

    def test_owner_by_name(self):
        t = self.tree("person_id: ppl-001-aaa-001\ngedcom_id: I16")
        self.assertEqual(list(t.biographies.values()), ["ppl-001-aaa-001"])

    def test_card_renamed(self):
        """Карточку переименовали, биография осталась со старым именем — узнаём человека по person_id."""
        t = self.tree("person_id: ppl-001-aaa-001\ngedcom_id: I16", name="Вавила Дубняк")
        self.assertEqual(len(t.errors), 1)
        self.assertIn("переименована", t.errors[0].message)

    def test_no_card_line(self):
        t = self.tree("person_id: ppl-001-aaa-001\ngedcom_id: I16", line=False)
        self.assertEqual(len(t.errors), 1)
        self.assertIn("нет строки", t.errors[0].message)


if __name__ == "__main__":
    unittest.main()


class FamilyOrder(unittest.TestCase):
    """Дети — по рождению, супруги — по порядку браков, как бы ни были записаны в карточке (cards.tree.order_family)."""

    def test_children_by_birth_spouses_by_marriage(self):
        root = Path(tempfile.mkdtemp())
        for d in ("sources", "places"):
            (root / d).mkdir()
        write(root / "people", "Отец", """
            cr_id: ppl-001-aaa-001
            name: Отец
            sex: male
            spouse_id: [ppl-001-aaa-003, ppl-001-aaa-002]
            children_id: [ppl-001-aaa-006, ppl-001-aaa-005, ppl-001-aaa-004]
            """)
        write(root / "people", "Первая", "cr_id: ppl-001-aaa-002\nname: Первая\nsex: female")
        write(root / "people", "Вторая", "cr_id: ppl-001-aaa-003\nname: Вторая\nsex: female")
        write(root / "people", "Старший", "cr_id: ppl-001-aaa-004\nname: Старший\nsex: male\nborn: 1958\nmother_id: ppl-001-aaa-002")
        write(root / "people", "Средний", "cr_id: ppl-001-aaa-005\nname: Средний\nsex: male\nborn: ABT 1961\nmother_id: ppl-001-aaa-003")
        write(root / "people", "Без даты", "cr_id: ppl-001-aaa-006\nname: Без даты\nsex: male")
        write(root / "events", "Брак", """
            cr_type: event
            event_type: marriage
            date: 1970
            persons: ["[[Отец]]", "[[Вторая]]"]
            """)
        p = cards.load(root).people["ppl-001-aaa-001"]
        self.assertEqual(p.children, ["ppl-001-aaa-004", "ppl-001-aaa-005", "ppl-001-aaa-006"])
        # с Первой брак не записан — по старшему общему ребёнку (1958), раньше брака со Второй (1970)
        self.assertEqual(p.spouses, ["ppl-001-aaa-002", "ppl-001-aaa-003"])
