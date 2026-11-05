"""Лента «Что нового»: что считается правкой при сравнении двух снимков дерева (site_data/progress.py: changes).
Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from site_data.progress import changes  # noqa: E402


def person(**kw):
    return {"name": "Прокоп Ясенев", "life": "1909–?", "ln": ["Ясеневы"], "lm": [], "facts": 3, "pics": 0, "bio": "",
            "parents": [], "spouses": [], **kw}


class Changes(unittest.TestCase):
    def test_new_and_removed(self):
        items, removed = changes({"a": person(), "gone": person()}, {"a": person(), "b": person()})
        self.assertEqual(items, [{"id": "b", "new": True}])
        self.assertEqual(removed, 1)

    def test_what_changed(self):
        old = {"a": person()}
        new = {"a": person(life="1909–1993", facts=10, pics=1, bio="abc", parents=["f"], spouses=["s"])}
        self.assertEqual(changes(old, new)[0], [{"id": "a", "life": ["1909–?", "1909–1993"], "facts": 7, "bio": "new",
                                                 "pics": 1, "parents": ["f"], "spouses": ["s"]}])
        self.assertEqual(changes({"a": person(bio="abc")}, {"a": person(bio="def")})[0], [{"id": "a", "bio": "edit"}])

    def test_quiet(self):
        """Ничего не поменялось, факты убрали, человек без имени — строки в ленте нет."""
        self.assertEqual(changes({"a": person()}, {"a": person()})[0], [])
        self.assertEqual(changes({"a": person(facts=5)}, {"a": person(facts=4)})[0], [])
        self.assertEqual(changes({}, {"u": person(name="Unknown (I603)")})[0], [])


if __name__ == "__main__":
    unittest.main()
