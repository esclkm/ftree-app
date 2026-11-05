"""Год из возраста, оценка по родне, Пасха и праздники (dates.py; правила — навык dates)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates as D  # noqa: E402


class Age(unittest.TestCase):
    def test_birth_from_age(self):
        exact, loose = D.birth_from_age(45, 1897)
        self.assertEqual(exact.card(), "BET 1851 AND 1852")
        self.assertEqual(loose.card(), "BET 1849 AND 1854")
        self.assertEqual(D.birth_from_age("84", D.Day(2005, 3, 1))[0].card(), "BET 1920 AND 1921")

    def test_ages_agree(self):
        self.assertEqual(D.ages_agree((45, 1897), (50, 1905)), (3, "норма"))
        self.assertEqual(D.ages_agree((30, 1880), (60, 1900)), (10, "перечитать"))
        self.assertEqual(D.ages_agree((20, 1880), (60, 1900)), (20, "тёзки"))


class Estimate(unittest.TestCase):
    def test_intersection(self):
        g, why = D.estimate_birth(father=1850, eldest_child=1895, siblings=[1870])
        self.assertEqual(g.card(), "BET 1868 AND 1877")
        self.assertIn("старший ребёнок 1895", why)

    def test_wide_window_is_est(self):
        self.assertEqual(D.estimate_birth(father=1850)[0].card(), "EST 1881")

    def test_conflict(self):
        with self.assertRaises(D.DateError):
            D.estimate_birth(father=1850, eldest_child=1860)
        with self.assertRaises(D.DateError):
            D.estimate_birth()


class Easter(unittest.TestCase):
    def test_orthodox(self):   # по старому стилю; новый — julian_to_gregorian
        for y, new in ((1888, "1888-05-06"), (1910, "1910-05-01"), (2024, "2024-05-05"), (2026, "2026-04-12")):
            self.assertEqual(D.julian_to_gregorian(D.orthodox_easter(y)).iso(), new)

    def test_catholic(self):
        for y, iso in ((1888, "1888-04-01"), (1910, "1910-03-27"), (2024, "2024-03-31"), (2025, "2025-04-20")):
            self.assertEqual(D.catholic_easter(y).iso(), iso)




class Feasts(unittest.TestCase):
    def test_fixed_orthodox(self):
        self.assertEqual(D.feast_date("на Покров", 1888).ru(), "13.10.1888 (01.10.1888 ст. ст.)")
        self.assertEqual(D.feast_date("на Николу зимнего", 1890).card(), "1890-12-18")
        self.assertEqual(D.feast_date("Дмитриева дня", 1890).os, D.Day(1890, 10, 26))   # «… дня» = «… день»

    def test_movable_orthodox(self):
        self.assertEqual(D.feast_date("на Троицу", 2024).card(), "2024-06-23")
        self.assertEqual(D.feast_date("Вербное воскресенье", 1900).os, D.Day(1900, 4, 2))

    def test_catholic(self):
        self.assertEqual(D.feast_date("na Boże Ciało", 1925, "catholic").card(), "1925-06-11")
        self.assertEqual(D.feast_date("św. Michała", 1925, "catholic").card(), "1925-09-29")
        self.assertIsNone(D.feast_date("Zaduszki", 1925, "catholic").os)

    def test_unknown(self):
        with self.assertRaises(D.DateError):
            D.feast_date("на Масленицу в среду", 1900)
        with self.assertRaises(D.DateError):   # «вознесение» и «воздвижение» не путаются
            D.feast_date("воз", 1900)


if __name__ == "__main__":
    unittest.main()
