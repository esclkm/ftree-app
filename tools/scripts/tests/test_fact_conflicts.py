import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates  # noqa: E402
import fact_conflicts as fc  # noqa: E402
from cards.model import Fact  # noqa: E402


def fact(label, text):
    return Fact(1, text, [], "normal", "found", None, label, "")


class Classify(unittest.TestCase):
    def test_own_event_only(self):
        self.assertEqual(fc.classify(fact("рождение (расчёт)", "…")), ("birth", ""))
        self.assertIsNone(fc.classify(fact("рождение сына", "…")))
        self.assertIsNone(fc.classify(fact("", "умер отец")))
        self.assertIsNone(fc.classify(fact("", "смерть жены воспринял тяжело")))
        self.assertEqual(fc.classify(fact("", "умер; в больнице …")), ("death", ""))
        self.assertIsNone(fc.classify(fact("смерть (кандидат)", "…")))


class TextDate(unittest.TestCase):
    def test_conclusion_wins(self):
        self.assertEqual(fc.date_from_text("20 лет в октябре 1891 — родился около 1871").card(), "ABT 1871")
        self.assertEqual(fc.date_from_text("рак в 47 → между 2012 и 2013").card(), "BET 2012 AND 2013")
        self.assertEqual(fc.date_from_text("1957, «в 74 годика» → родилась между 1882 и 1883", "death").card(), "1957")
        self.assertIsNone(fc.date_from_text("19 лет в октябре 1891"))


class Compare(unittest.TestCase):
    def test_spans(self):
        g = dates.parse_card
        self.assertEqual(fc.years_apart(g("ABT 1835"), g("1836")), 0)
        self.assertEqual(fc.years_apart(g("1999"), g("2002")), 2)
        self.assertTrue(fc.style_pair(g("1905-03-01"), g("1905-03-14")))
        self.assertFalse(fc.style_pair(g("1925-03-01"), g("1925-03-14")))


if __name__ == "__main__":
    unittest.main()
