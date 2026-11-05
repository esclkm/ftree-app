"""Подсказка «кто это из дерева» не должна находить человека в книге, если он тогда ещё не родился или уже умер."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metric_review as mr  # noqa: E402


def person(born=None, died=None):
    y = lambda v: SimpleNamespace(first_year=v, last_year=v) if v else None
    return SimpleNamespace(born=y(born), died=y(died))


class FitsYears(unittest.TestCase):
    def setUp(self):
        self.k = mr.Kin.__new__(mr.Kin)
        self.k.t = SimpleNamespace(people={"внук": person(1964, 2020), "прапрадед": person(1860),
                                           "сын": person(1894), "умер": person(1850, 1880), "?": person()})
        self.book = mock.patch("form_template.book_by_id", return_value={"title": "МК 1893–1897"})
        self.book.start()

    def tearDown(self):
        self.book.stop()

    def test_not_yet_born(self):
        self.assertFalse(self.k.fits_years("внук", "x"))          # 1964 — в книге 1890-х быть не мог

    def test_adult_needs_age(self):
        self.assertTrue(self.k.fits_years("прапрадед", "x"))
        self.assertFalse(self.k.fits_years("сын", "x"))           # крёстным в 1893–1897 — ребёнок 1894 года не мог
        self.assertTrue(self.k.fits_years("сын", "x", adult=False))

    def test_dead_before_and_unknown(self):
        self.assertFalse(self.k.fits_years("умер", "x"))
        self.assertTrue(self.k.fits_years("?", "x"))


if __name__ == "__main__":
    unittest.main()
