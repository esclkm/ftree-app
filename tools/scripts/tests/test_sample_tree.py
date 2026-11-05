"""Тесты идут на вымышленном образце (sample_tree.py), а не на живом дереве: каждый тест подключает образец до
первого скрипта, и paths.ROOT смотрит в образец."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cards  # noqa: E402
import paths  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS = {p.stem for p in HERE.parent.glob("*.py")} | {p.name for p in HERE.parent.iterdir() if p.is_dir()}


class SampleTreeTest(unittest.TestCase):
    def test_root_is_sample(self):
        self.assertEqual(paths.ROOT, sample_tree.ROOT)
        self.assertNotEqual(paths.ROOT, paths.APP.resolve())                 # не дерево, где лежит приложение
        self.assertEqual(len(cards.load().people), 30)

    def test_every_test_imports_sample_first(self):
        imp = re.compile(r"^(?:import|from)\s+([\w.]+)", re.M)
        for f in sorted(HERE.glob("test_*.py")):
            mods = [m.split(".")[0] for m in imp.findall(f.read_text(encoding="utf-8"))]
            ours = [m for m in mods if m in SCRIPTS or m == "sample_tree"]
            self.assertTrue(ours and ours[0] == "sample_tree", f"{f.name}: первым из своих — import sample_tree")


if __name__ == "__main__":
    unittest.main()
