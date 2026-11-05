"""Тесты возможных связей (maybe_same, maybe_kin) и проверенного «нет» (not_same, not_kin) — на выдуманном дереве.
Запуск: python3 -m unittest discover tools/scripts/tests"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cards  # noqa: E402
import check_tree  # noqa: E402
import find_duplicates  # noqa: E402
import merge_cards  # noqa: E402
import paths  # noqa: E402
import possible  # noqa: E402
import tree as T  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tree_cli import SRC, person  # noqa: E402
from test_cards import write  # noqa: E402

FACT = (f"## Факты и заметки\n\n### Факты (с источником)\n\n- **1894:** родился — *источник: [[{SRC}]], 1:00 · "
        f"уверенность: средняя*\n\n### Открытые вопросы\n\n")


def tree_with(**cards_kw):
    """Наш Еремей (с отцом Александром), найденный Иеремия, сосед Вавила, однофамилец Михаил; поля — из cards_kw."""
    root = Path(tempfile.mkdtemp())
    write(root / "sources", SRC, f'cr_type: source\ncr_id: src-001-aaa-001\ntitle: "{SRC}"\norigin: "семья"')
    write(root / "places", "Вербичи", "cr_type: place\ncr_id: plc-001-aaa-001\nname: Вербичи\nplace_type: village",
          "## Государства по годам\n\n- до 1917 — Российская империя\n")
    base = {
        "Еремей Дубняк": dict(cid="se", sex="male", born=1894, birth_place="[[Вербичи]]", gedcom_id="I60",
                               father="[[Александр Дубняк]]", father_id="al"),
        "Александр Дубняк": dict(cid="al", sex="male", born=1860, children=["[[Еремей Дубняк]]"], children_id=["se"]),
        "Иеремия (1894)": dict(cid="sg", sex="male", born=1894, birth_place="[[Вербичи]]"),
        "Вавила Дубняк": dict(cid="gr", sex="male", birth_place="[[Вербичи]]"),
        "Михаил Дубняк (1933)": dict(cid="mi", sex="male", born=1933),
    }
    for name, kw in base.items():
        kw = dict(kw, **cards_kw.get(name, {}))
        person(root, name, kw.pop("cid"), kw.pop("sex"), **kw)
    (root / "events").mkdir()
    return root, cards.load(root)


SAME = {"Иеремия (1894)": dict(maybe_same="[[Еремей Дубняк]]", maybe_same_id="se",
                              body=FACT + "- Он ли [[Еремей Дубняк]]? Совпали год, имя, деревня.\n")}
KIN = {"Вавила Дубняк": dict(maybe_kin="[[Александр Дубняк]] — брат?", maybe_kin_id="al",
                                body=FACT + "- Брат ли ему [[Александр Дубняк]]? Оба из Вербичей.\n")}
NO = {"Михаил Дубняк (1933)": dict(not_kin="[[Еремей Дубняк]]", not_kin_id="se",
                                    body=FACT + "- ✅ ~~[[Еремей Дубняк]] — его отец?~~ Нет: другой отец.\n")}


class Read(unittest.TestCase):
    def test_same_both_sides(self):
        _, t = tree_with(**SAME)
        mine, back = t.people["sg"].possible, t.people["se"].possible
        self.assertEqual([(x.kind, x.person, x.back) for x in mine], [("same", "se", False)])
        self.assertEqual([(x.kind, x.person, x.back) for x in back], [("same", "sg", True)])
        self.assertIn("Совпали год", back[0].reason)
        self.assertFalse([p for p in t.problems if "maybe" in p.message])

    def test_kin_relation_turns_around(self):
        _, t = tree_with(**KIN)
        self.assertEqual(t.people["gr"].possible[0].relation, "sibling")
        _, t = tree_with(**{"Вавила Дубняк": dict(maybe_kin="[[Александр Дубняк]] — отец?", maybe_kin_id="al",
                                                    body=FACT + "- Отец ли [[Александр Дубняк]]?\n")})
        self.assertEqual(t.people["gr"].possible[0].relation, "parent")
        self.assertEqual(t.people["al"].possible[0].relation, "child")

    def test_no_both_ways(self):
        _, t = tree_with(**NO)
        self.assertTrue(t.ruled_out("mi", "se") and t.ruled_out("se", "mi", "kin"))
        self.assertFalse(t.ruled_out("se", "mi", "same"))
        self.assertFalse([p for p in t.problems if "not_" in p.message])

    def test_no_without_reason_warns(self):
        _, t = tree_with(**{"Михаил Дубняк (1933)": dict(not_kin="[[Еремей Дубняк]]", not_kin_id="se")})
        self.assertTrue([p for p in t.problems if "почему «нет»" in p.message and p.level == "warning"])

    def test_bad_role_self_and_missing(self):
        _, t = tree_with(**{"Вавила Дубняк": dict(maybe_kin=["[[Александр Дубняк]] — кум?", "[[Вавила Дубняк]]",
                                                               "[[Никто]] — брат?"])})
        msgs = " | ".join(p.message for p in t.problems)
        self.assertIn("кем приходится", msgs)
        self.assertIn("ссылка на себя", msgs)
        self.assertIn("нет такой карточки", msgs)
        self.assertEqual(t.people["gr"].possible, [])

    def test_written_on_both_cards_shows_once(self):
        _, t = tree_with(**SAME, **{"Еремей Дубняк": dict(maybe_same="[[Иеремия (1894)]]", maybe_same_id="sg",
                                                           father="[[Александр Дубняк]]", father_id="al")})
        self.assertEqual(len(t.people["se"].possible), 1)
        self.assertFalse(t.people["se"].possible[0].back)

    def test_not_a_link_for_lineage(self):
        _, t = tree_with(**KIN)
        self.assertEqual(t.people["gr"].father, [])
        self.assertNotIn("gr", t.people["al"].children)


class Candidates(unittest.TestCase):
    """Кто предлагает кандидатов, пропускает пары из not_* — в обе стороны."""
    CONFLICT = {"Иеремия (1894)": dict(maybe_same="[[Еремей Дубняк]]", maybe_same_id="se",
                                      body=FACT + "- Он ли [[Еремей Дубняк]]?\n"),
                "Еремей Дубняк": dict(not_same="[[Иеремия (1894)]]", not_same_id="sg", father="[[Александр Дубняк]]",
                                       father_id="al", body=FACT + "- ✅ ~~[[Иеремия (1894)]] — тот же?~~ Нет.\n")}

    def test_merge_candidates(self):
        _, t = tree_with(**SAME)
        self.assertEqual(len(merge_cards.candidates(t)), 1)
        _, t = tree_with(**self.CONFLICT)   # «нет» записано у второй карточки — пары всё равно нет
        self.assertEqual(merge_cards.candidates(t), [])

    def test_find_for(self):
        _, t = tree_with(**NO)
        out = "\n".join(T.find(t, "Дубняк", t.people["se"]))
        self.assertNotIn("Михаил", out)
        self.assertIn("Вавила", out)
        out = "\n".join(T.find(t, "Дубняк", t.people["mi"]))   # с другой стороны — тоже
        self.assertNotIn("Еремей Дубняк", out)
        self.assertIn("Михаил", "\n".join(T.find(t, "Дубняк")))   # без --for — все

    def test_find_for_marks_maybe(self):
        _, t = tree_with(**SAME)
        self.assertIn("возможно, тот же", "\n".join(T.run(["find", "Иеремия", "--for", "Еремей Дубняк"], t)))

    def test_targets_for(self):
        root, t = tree_with(**{"Вавила Дубняк": dict(not_kin="[[Еремей Дубняк]]", not_kin_id="se", born=1890,
                                                        body=FACT + "- ✅ ~~[[Еремей Дубняк]] — родня?~~ Нет.\n")})
        args = ["targets", "--place", "Вербичи", "--years", "1880-1900"]
        self.assertIn("Вавила", "\n".join(T.run(args, t, root)))
        self.assertNotIn("Вавила", "\n".join(T.run(args + ["--for", "Еремей Дубняк"], t, root)))

    def test_find_duplicates(self):
        _, t = tree_with(**{"Иеремия (1894)": dict(gedcom_id="I90", not_same="[[Еремей Дубняк]]", not_same_id="se",
                                                  body=FACT + "- ✅ ~~[[Еремей Дубняк]] — тот же?~~ Нет.\n")})
        self.assertTrue(find_duplicates.ruled_out(t, "@I60@", "@I90@"))
        self.assertTrue(find_duplicates.ruled_out(t, "I90", "I60"))
        self.assertFalse(find_duplicates.ruled_out(t, "I60", "I1"))

    def test_who_shows_both_sides(self):
        _, t = tree_with(**KIN, **NO)
        out = "\n".join(T.who(t, "Александр Дубняк"))
        self.assertIn("возможно, брат / сестра: Вавила Дубняк", out)
        self.assertIn("проверено — нет: не родня: Михаил", "\n".join(T.who(t, "Еремей Дубняк")))


class CheckTree(unittest.TestCase):
    def run_on(self, root):
        out = io.StringIO()
        with mock.patch.object(paths, "TREE", root), mock.patch.object(paths, "ROOT", root), \
                contextlib.redirect_stdout(out):
            code = check_tree.main()
        return code, out.getvalue()

    def test_clean(self):
        root, _ = tree_with(**SAME, **KIN, **NO)
        self.assertEqual(self.run_on(root), (0, "Проверка дерева: людей 5, ошибок 0\n"))

    def test_broken_maybe_kin(self):
        root, _ = tree_with(**{"Вавила Дубняк": dict(maybe_kin="[[Александр Дубнак]] — брат?", maybe_kin_id="al")})
        code, out = self.run_on(root)
        self.assertEqual(code, 1)
        self.assertIn("maybe_kin → [[Александр Дубнак]] — нет такой карточки", out)

    def test_wrong_id_and_self(self):
        root, _ = tree_with(**{"Вавила Дубняк": dict(maybe_kin="[[Александр Дубняк]] — брат?", maybe_kin_id="se",
                                                        not_same="[[Вавила Дубняк]]")})
        _, out = self.run_on(root)
        self.assertIn("а номер se — это [[Еремей Дубняк]]", out)
        self.assertIn("ссылка на себя", out)

    def test_pair_in_maybe_and_no(self):
        root, _ = tree_with(**Candidates.CONFLICT)
        _, out = self.run_on(root)
        self.assertIn("Еремей Дубняк ↔ Иеремия (1894): пара сразу в maybe_same и not_same", out)


class Decide(unittest.TestCase):
    def setUp(self):
        self.root, self.tree = tree_with(**SAME, **KIN)
        self.patch = mock.patch.object(possible, "PEOPLE", self.root / "people")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_no_writes_not_and_closes_question(self):
        changes, _ = possible.decide_no(self.tree, "Иеремия (1894)", "Еремей Дубняк", "другой отец в д. 600", None, True)
        t = cards.load(self.root)
        self.assertTrue(t.ruled_out("se", "sg", "same"))
        self.assertEqual(t.people["sg"].possible, [])
        text = (self.root / "people" / "Иеремия (1894).md").read_text(encoding="utf-8")
        self.assertIn("not_same_id: se", text)
        self.assertNotIn("maybe_same", text)
        self.assertIn("- ✅ ~~[[Еремей Дубняк]] — тот же человек?~~ Нет: другой отец в д. 600", text)
        self.assertFalse([p for p in t.problems if "not_" in p.message])
        self.assertEqual(merge_cards.candidates(t), [])

    def test_yes_makes_a_real_link(self):
        possible.decide_yes(self.tree, "Вавила Дубняк", "Александр Дубняк", "отец",
                            f"[[{SRC}]], 2:00: «сын Александра»", True)
        t = cards.load(self.root)
        self.assertEqual(t.people["gr"].father, ["al"])
        self.assertIn("gr", t.people["al"].children)
        self.assertEqual(t.people["gr"].possible, [])
        self.assertTrue(any(f.label == "Родство" for f in t.people["gr"].facts))
        code, _ = CheckTree().run_on(self.root)
        self.assertEqual(code, 0)

    def test_yes_refuses_sibling_and_wrong_sex(self):
        with self.assertRaises(SystemExit):
            possible.decide_yes(self.tree, "Вавила Дубняк", "Александр Дубняк", "брат", f"[[{SRC}]]", False)
        with self.assertRaises(SystemExit):
            possible.decide_yes(self.tree, "Вавила Дубняк", "Александр Дубняк", "мать", f"[[{SRC}]]", False)

    def test_page_lists_pairs(self):
        lines, n = possible.page(self.tree)
        self.assertEqual(n, 2)
        page = "\n".join(lines)
        self.assertIn("Иеремия (1894) ↔ Еремей Дубняк — возможно, тот же человек", page)
        self.assertIn('merge-cards "Иеремия (1894)" "Еремей Дубняк"', page)   # остаётся карточка с gedcom_id


if __name__ == "__main__":
    unittest.main()


class Auto(unittest.TestCase):
    """Похожие пары, которых никто не отмечал: Иеремия из метрики ↔ наш Еремей (тот же год, деревня, отец Александр)."""
    def tree(self, **kw):
        base = {"Иеремия (1894)": dict(father="[[Александр (отец Иеремии)]]", father_id="as")}
        root, _ = tree_with(**{**base, **kw})
        person(root, "Александр (отец Иеремии)", "as", "male", children=["[[Иеремия (1894)]]"], children_id=["sg"])
        return root, cards.load(root)

    def test_finds_church_form_of_name(self):
        _, t = self.tree()
        found = [(a.id, b.id, why) for a, b, why, _ in possible.auto(t)]
        self.assertEqual([(a, b) for a, b, _ in found], [("sg", "se")])   # найденная — слева, с gedcom_id — справа
        self.assertIn("год рождения 1894", found[0][2])
        self.assertIn("отец Александр", found[0][2])

    def test_skips_marked_and_ruled_out(self):
        _, t = self.tree(**{"Иеремия (1894)": dict(father="[[Александр (отец Иеремии)]]", father_id="as",
                                                  maybe_same="[[Еремей Дубняк]]", maybe_same_id="se")})
        self.assertEqual(possible.auto(t), [])
        _, t = self.tree(**{"Иеремия (1894)": dict(father="[[Александр (отец Иеремии)]]", father_id="as",
                                                  not_same="[[Еремей Дубняк]]", not_same_id="se",
                                                  body=FACT + "- ✅ ~~[[Еремей Дубняк]] — тот же?~~ Нет.\n")})
        self.assertEqual(possible.auto(t), [])

    def test_different_fathers_are_different_people(self):
        root, _ = tree_with(**{"Иеремия (1894)": dict(father="[[Пётр (отец Иеремии)]]", father_id="pt")})
        person(root, "Пётр (отец Иеремии)", "pt", "male", children=["[[Иеремия (1894)]]"], children_id=["sg"])
        self.assertEqual(possible.auto(cards.load(root)), [])

    def test_mark_command(self):
        root, t = self.tree()
        with mock.patch.object(possible, "PEOPLE", root / "people"):
            possible.decide_maybe(t, "Иеремия (1894)", "Еремей Дубняк", "совпали год, деревня, отец", "", True)
        t = cards.load(root)
        self.assertEqual([(x.kind, x.person) for x in t.people["sg"].possible], [("same", "se")])
        self.assertIn("совпали год", t.people["se"].possible[0].reason)
        self.assertEqual(possible.auto(t), [])


class BioOrder(unittest.TestCase):
    def test_range_start_is_an_anchor(self):
        import check_bio
        import dates
        self.assertEqual(check_bio.earliest(dates.parse_ru("между 1937 и 1938"))[0], 1937)
        self.assertEqual(check_bio.earliest(dates.parse_ru("ок. 1934"))[0], 1932)
        self.assertEqual(check_bio.earliest(dates.parse_ru("до 1941")), (0, 0, 0))
        # «06.11.1934» после «между 1937 и 1938» — наверняка раньше: не по времени
        self.assertTrue(check_bio.earlier(check_bio.latest(dates.parse_ru("06.11.1934")),
                                          check_bio.earliest(dates.parse_ru("между 1937 и 1938"))))
