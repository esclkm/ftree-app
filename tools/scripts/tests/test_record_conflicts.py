import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import record_conflicts as rc  # noqa: E402

# имена вымышленные
BIRTH = lambda child, mom, mom_f, num: {"part": "рождение", "number": num, "village": "Липовка",
                                        "child": {"given": child}, "father": {"given": "Иеремия", "father": "Пахом"},
                                        "mother": {"given": mom, "father": mom_f}}


class Same(unittest.TestCase):
    def test_forms_and_misreads(self):
        self.assertEqual(rc.same("Иеремия", "Еремей"), "да")
        self.assertEqual(rc.same("Мануил", "Мануила?"), "похоже")
        self.assertEqual(rc.same("Евстафий", "Евмений"), "нет")
        self.assertEqual(rc.same("", "Евстафий"), "")


class Checks(unittest.TestCase):
    def setUp(self):
        self.parsed = {"кн:1:10#0": BIRTH("Роман", "Ирина", "Евмений", "5"),
                       "кн:2:10#0": BIRTH("Мелания", "Ирина", "Евмений", "9"),
                       "кн:3:10#0": BIRTH("Пётр", "Ирина", "Евстафий", "3"),
                       "кн:4:10#0": {"part": "брак", "village": "Липовка",
                                     "groom": {"given": "Еремей", "father": "Пахом", "age": 24},
                                     "bride": {"given": "Ирина", "father": "Евстафий", "age": 18}}}

    def test_mother_and_bride(self):
        fam = rc.families(self.parsed)
        self.assertEqual(len(rc.check_mothers(fam)), 1)          # одна семья — один пункт: Евстафий ≠ Евмений
        self.assertEqual(len(rc.check_weddings(self.parsed, fam)), 2)

    def test_age(self):
        years = {"кн": (1900, 1900), "смерть": (1950, 1950)}
        parsed = {"кн:1:1#0": BIRTH("Роман", "Ирина", "Евмений", "5"),
                  "смерть:1:1#0": {"part": "смерть", "village": "Липовка",
                                   "deceased": {"given": "Роман", "father": "Еремей", "age": 70}}}
        with mock.patch.object(rc, "book_years", lambda b: years[b]):
            self.assertEqual(len(rc.check_ages(parsed)), 1)       # 70 лет, а по годам выходит 49–50
            parsed["смерть:1:1#0"]["deceased"]["age"] = 52
            self.assertEqual(len(rc.check_ages(parsed)), 0)       # ±3 года — не расхождение


if __name__ == "__main__":
    unittest.main()
