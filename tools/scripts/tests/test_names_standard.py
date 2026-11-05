"""Тесты стандарта имени (check_names.py), подписи годов жизни (site_data.life) и замороженных адресов страниц
(site_data.names.assign_slugs с keep). Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_names import problems  # noqa: E402
from site_data.life import lifespan  # noqa: E402
from site_data.names import assign_slugs  # noqa: E402


class Names(unittest.TestCase):
    def test_good(self):
        for n in ("Иван Дубняк", "Агата Jasieniew", "Ewa Helena Wierzbowska", "Witold K. Prokop", "Анна", "Ясенев",
                  "Unknown", "А. Ракитин", "Jan van Dijk", "Савва Осокин"):
            self.assertEqual(problems(n), [], n)

    def test_bad(self):
        for n in ("Иван Дубняк (1935)", "Марина Клёнова (жена Прокопа Ракитина)", "Unknown (I12)", "Вера 2",
                  "Мелания?", "Первая жена Прокопа Дубняка", "Anna Prokopovna Липская", "Наталья Саввична Осокина",
                  "Вера Прокоповна", "witold Prokop"):
            self.assertTrue(problems(n), n)


class Life(unittest.TestCase):
    def test_signs(self):
        self.assertEqual(lifespan("BEF 1857", "AFT 1913"), "<1857–>1913")
        self.assertEqual(lifespan("ABT 1823", "BET 1855 AND 1857"), "~1823–~1855")
        self.assertEqual(lifespan("1902", "1986"), "1902–1986")


class Slugs(unittest.TestCase):
    def test_keep(self):
        s = assign_slugs([("a", "Prokop Dubniak", 1935), ("b", "Prokop Dubniak", 1922)], {"a": "prokop-dubniak-1935"})
        self.assertEqual(s["a"], "prokop-dubniak-1935")
        self.assertEqual(s["b"], "prokop-dubniak")


if __name__ == "__main__":
    unittest.main()
