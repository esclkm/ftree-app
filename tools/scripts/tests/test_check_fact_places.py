"""Место в факте — ссылкой (check_fact_places.py): падежи, отчества, догадки в скобках, ссылки с «[?]» внутри."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_fact_places as c  # noqa: E402


def place(pid, stem, type_="village", aliases=()):
    return NS(id=pid, stem=stem, type=type_, real=True, aliases=list(aliases))


TREE = NS(places={p.id: p for p in (place("p1", "Вербичи"), place("p2", "Лесогорск", "city"),
                                    place("p3", "Кириллов", "city"), place("p4", "Липки"), place("p5", "Беларусь", "country"),
                                    place("p6", "Buenos Aires", "city", ["Буэнос-Айрес"]), place("p7", "Брест", "city"))})


def found(text):
    c._by_name.clear()
    return [(text[a:b], pl.stem) for a, b, pl in c.unlinked(NS(text=text), c.patterns(TREE), TREE)]


class FactPlaces(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(found("откуда: из Вербичей; потом в Буэнос-Айресе"),
                         [("Вербичей", "Вербичи"), ("Буэнос-Айресе", "Buenos Aires")])
        self.assertEqual(found("брак: 23.09.1944, г. Лесогорск (Подгорье)"), [("Лесогорск", "Лесогорск")])

    def test_adjective_is_not_place(self):
        self.assertEqual(found("Брестский уезд, Брестская обл."), [])

    def test_patronymic_after_name(self):
        """«Ксения Кириллова» — дочь Кирилла; «из Кириллова» — город."""
        self.assertEqual(found("крёстная — Ксения Кириллова"), [])
        self.assertEqual(found("переехал из Кириллова"), [("Кириллова", "Кириллов")])

    def test_reading_guess_in_brackets(self):
        self.assertEqual(found("«Той же волости и деревни [Липок] крестьянинъ»"), [])

    def test_inside_link_with_question_mark(self):
        self.assertEqual(found("сын [[Евстафий (Липки)|Евстафий[?]]], крёстный"), [])

    def test_country_skipped_and_linked_skipped(self):
        self.assertEqual(found("жил в Беларуси"), [])
        self.assertEqual(found("из [[Вербичи|Вербичей]], потом снова Вербичи"), [])


if __name__ == "__main__":
    unittest.main()
