"""Дата есть, факта нет (check_fact_dates.py): какие годы видит строка и как правится карточка события."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_fact_dates as c  # noqa: E402


class Spans(unittest.TestCase):
    def test_forms(self):
        self.assertIn((1935, 1944), c.spans("1935–1944"))
        self.assertIn((1950, 1955), c.spans("между 1950 и 1955"))
        self.assertIn((1930, 1939), c.spans("1930-е"))
        self.assertIn((1948, 1953), c.spans("после 1948"))
        self.assertIn((1936, 1941), c.spans("до 1941 (до войны)"))
        self.assertEqual(c.spans("ок. 1965", 2), [(1963, 1967)])

    def test_meet(self):
        self.assertTrue(c.meet(c.spans("1930-е"), c.spans("1934")))
        self.assertFalse(c.meet(c.spans("1958"), c.spans("1944, Лесогорск")))

    def test_words(self):
        self.assertTrue(c.DEATH.search("Умирает отец, Никита"))
        self.assertTrue(c.MARRIAGE.search("Женится на Соне Ясеневой"))
        self.assertFalse(c.BIRTH.search("свидетельство о рождении сына"))

    def test_precision(self):
        self.assertEqual(c.precision("1944-09-23"), "exact")
        self.assertEqual(c.precision("BET 2001 AND 2008"), "range")
        self.assertEqual(c.precision("CAL 1861"), "estimated")


class EventFile(unittest.TestCase):
    def test_set_fields_replaces_and_adds(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "e.md"
            p.write_text('---\ncr_type: event\nevent_type: marriage\ndate_precision: unknown\npersons:\n  - "[[A]]"\n---\n# E\n',
                         encoding="utf-8")
            c.set_fields(p, {"date": "1944-09-23", "date_precision": "exact", "place": '"[[Лесогорск]]"'})
            text = p.read_text(encoding="utf-8")
            self.assertIn("date_precision: exact\n", text)
            self.assertIn('date: 1944-09-23\nplace: "[[Лесогорск]]"\n---\n# E\n', text)
            self.assertNotIn("unknown", text)


if __name__ == "__main__":
    unittest.main()
