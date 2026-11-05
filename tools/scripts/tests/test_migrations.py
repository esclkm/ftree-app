"""Тесты migrations.py (переезды без объяснения) на выдуманных местах. Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrations as M  # noqa: E402
from cards import Place  # noqa: E402


def pl(pid, typ, parent=None, coords=None):
    return Place(pid, pid, pid, typ, True, [], parent, coords, [])


TREE = SimpleNamespace(places={p.id: p for p in [
    pl("BY", "country"), pl("PL", "country"),
    pl("Брест", "city", "BY", (52.09, 23.69)),
    pl("кладбище", "cemetery", "Брест"),
    pl("Вербичи", "village", "BY", (52.17, 23.58)),       # ≈11 км от Бреста
    pl("Лужки", "village", "BY", (52.20, 23.60)),    # ≈4 км от Вербичей
    pl("Варшава", "city", "PL"),
    pl("Ольшанка", "river", "BY"),
]})


class Moves(unittest.TestCase):
    def test_near_village_is_not_a_move(self):
        self.assertFalse(M.moved(TREE, "Вербичи", "Лужки"))

    def test_far_or_nested(self):
        self.assertTrue(M.moved(TREE, "Вербичи", "Брест"))
        self.assertFalse(M.moved(TREE, "Брест", "кладбище"))       # кладбище внутри города
        self.assertTrue(M.moved(TREE, "Брест", "Варшава"))         # без координат — разные страны

    def test_settle(self):
        self.assertEqual(M.settle(TREE, "кладбище"), "Брест")
        self.assertIsNone(M.settle(TREE, "Ольшанка"))
        self.assertIsNone(M.settle(TREE, "BY"))

    def test_gaps_reason_and_same_line(self):
        pts = {"x": [(1902, "Вербичи", "рождение", ""),
                     (1934, "Брест", "линия жизни", "1934: переехал в Брест"),
                     (1939, "Варшава", "факт", "Брест, Варшава"), (1939, "Брест", "факт", "Брест, Варшава")]}
        rows = M.gaps(TREE, pts)["x"]
        self.assertEqual(rows[0][4], "переех")                    # причина записана
        self.assertEqual(len(rows), 2)                            # Варшава → Брест из той же строки — не дыра


if __name__ == "__main__":
    unittest.main()
