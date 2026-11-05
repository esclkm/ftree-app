"""«Память» — что было после смерти: своя таблица сразу за «Линией жизни», в линию жизни не попадает (навык biography)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site_export as b  # noqa: E402
import check_bio  # noqa: E402

BIO = """# Михаил Ольховский (род. 1871)

**В дереве:** [[Михаил Ольховский|@I144@]]

## Линия жизни

| Когда | Что | Где |
| --- | --- | --- |
| 1871 | родился | [[Лесогорск]] |
| после 1945 | там он умер | [[Верхние Дубки]] |

## Память

| Когда | Что | Где |
| --- | --- | --- |
| 1987 | вещи сданы в Музей революции | [[Москва]] |

## Каким он был

Кузнец.

## Открытые вопросы

- ❓ когда умер
"""


class Split(unittest.TestCase):
    def test_memory_not_in_lifeline(self):
        text, rows = b.split_lifeline(b.own_head(BIO))
        self.assertEqual([r[1] for r in rows], ["1871", "после 1945"])
        self.assertIn("## Память", text)  # её убирает только второй проход

    def test_memory_rows_and_text(self):
        text, rows = b.split_lifeline(b.split_lifeline(b.own_head(BIO))[0], memory=True)
        self.assertEqual([(r[1], r[2]) for r in rows], [("1987", "вещи сданы в Музей революции")])
        self.assertEqual(rows[0][3], [("Где", "[[Москва]]")])
        self.assertNotIn("Память", text)
        self.assertNotIn("Линия жизни", text)
        self.assertIn("## Каким он был", text)

    def test_translation_heading(self):
        es = BIO.replace("## Память", "## Memoria").replace("## Линия жизни", "## Línea de vida")
        self.assertEqual(len(b.split_lifeline(b.own_head(es))[1]), 2)
        self.assertEqual(len(b.split_lifeline(b.own_head(es), memory=True)[1]), 1)


class Order(unittest.TestCase):
    def errors(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x — биография.md"
            p.write_text(text, encoding="utf-8")
            return check_bio.check_file(p)[0]

    def test_right_after_lifeline(self):
        self.assertEqual(self.errors(BIO), [])

    def test_memory_after_theme(self):
        moved = BIO.replace("## Каким он был\n\nКузнец.\n\n", "")
        moved = moved.replace("## Память", "## Кузница\n\nКузнец.\n\n## Память")
        self.assertTrue(any("Память" in e for e in self.errors(moved)))


if __name__ == "__main__":
    unittest.main()
