"""Два календаря: главная дата — по новому стилю, старый — рядом в скобках (правило 20.10.2026, шапка dates.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates as D  # noqa: E402


class JulianToGregorian(unittest.TestCase):
    def test_offsets_by_century(self):
        self.assertEqual(D.julian_to_gregorian(D.Day(1831, 7, 20)).iso(), "1831-08-01")    # XIX век: +12
        self.assertEqual(D.julian_to_gregorian(D.Day(1900, 2, 28)).iso(), "1900-03-12")    # ещё +12
        self.assertEqual(D.julian_to_gregorian(D.Day(1900, 3, 1)).iso(), "1900-03-14")     # с марта 1900: +13
        self.assertEqual(D.julian_to_gregorian(D.Day(1918, 1, 31)).iso(), "1918-02-13")    # последний день ст. ст.

    def test_round_trip(self):
        for d in (D.Day(1888, 6, 13), D.Day(1903, 4, 24), D.Day(1873, 12, 31)):
            self.assertEqual(D.gregorian_to_julian(D.julian_to_gregorian(d)), d)

    def test_only_full_date(self):
        with self.assertRaises(D.DateError):
            D.julian_to_gregorian(D.Day(1888, 6))


class LifelineCell(unittest.TestCase):
    def test_new_form(self):
        g = D.parse_ru("25.06.1888 (13.06.1888 ст. ст.)")
        self.assertEqual(g.card(), "1888-06-25")
        self.assertEqual(g.os, D.Day(1888, 6, 13))
        self.assertEqual(g.ru(), "25.06.1888 (13.06.1888 ст. ст.)")

    def test_words_kept(self):
        g = D.parse_ru("07.05.1903 (24.04.1903 ст. ст.; Лесогорск)")
        self.assertEqual((g.phrase, g.os_ru), ("Лесогорск", "24.04.1903 ст. ст."))

    def test_old_form_converts(self):
        g = D.parse_ru("12.02.1910 ст. ст. (Лесогорск)")
        self.assertTrue(g.julian)
        n = g.new_style()
        self.assertEqual(n.ru(), "25.02.1910 (12.02.1910 ст. ст.; Лесогорск)")
        self.assertFalse(n.julian)

    def test_mismatch_is_error(self):
        with self.assertRaises(D.DateError):
            D.parse_ru("25.06.1888 (12.06.1888 ст. ст.)")

    def test_year_only_not_moved(self):
        g = D.parse_ru("май 1888 ст. ст.")
        self.assertIs(g.new_style(), g)


if __name__ == "__main__":
    unittest.main()
