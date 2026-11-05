import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_family_sync as s  # noqa: E402
from cards.model import Fact  # noqa: E402


def fact(label, text, line=1):
    return Fact(line=line, text=text, refs=[], confidence="high", provenance="found", label=label)


def person(i, stem, spouses, facts, sex="M"):
    return SimpleNamespace(id=i, stem=stem, spouses=spouses, facts=facts, sex=sex)


class MarriageOnBothSides(unittest.TestCase):
    def tree(self, kazimierz_facts, olga_facts):
        b = person("b", "Kazimierz Wierzbowski", ["o"], kazimierz_facts)
        o = person("o", "Ольга Olga Jasieniew", ["b"], olga_facts, sex="F")
        return SimpleNamespace(people={"b": b, "o": o})

    def test_marriage_only_at_wife_is_error(self):
        t = self.tree([], [fact("брак (гражданская запись)", "23.09.1944, Лесогорск; муж — [[Kazimierz Wierzbowski]]")])
        fixes = []
        errs = s.card_problems(t, list(t.people.values()), fixes)
        self.assertEqual([e[0] for e in errs], ["Kazimierz Wierzbowski"])
        self.assertIn("23.09.1944", errs[0][1])
        self.assertEqual(len(fixes), 1)

    def test_same_date_on_both_sides_is_fine(self):
        t = self.tree([fact("брак", "23.09.1944, с [[Ольга Olga Jasieniew]]")],
                      [fact("брак", "23.09.1944, муж — [[Kazimierz Wierzbowski]]")])
        self.assertEqual(s.card_problems(t, list(t.people.values()), []), [])

    def test_unnamed_spouse_is_not_guessed(self):
        # Степан Ракитин: брак 1856 — вторым браком с Мелании, в дереве у него только Пелагея
        t = SimpleNamespace(people={
            "t": person("t", "Степан X", ["e"], [fact("брак", "22.01.1856 женился вторым браком на Мелании")]),
            "e": person("e", "Пелагея X", ["t"], [], sex="F")})
        self.assertEqual(s.card_problems(t, list(t.people.values()), []), [])

    def test_source_in_brackets_is_not_a_marriage(self):
        self.assertIsNone(s.kind_of("родилась на ст. Вербичи (анкета, свидетельство о браке)"))
        self.assertEqual(s.kind_of("расторжение брака"), "развод")


if __name__ == "__main__":
    unittest.main()
