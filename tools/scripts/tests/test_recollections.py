"""«Воспоминания» — сценки, которые кто-то помнит о человеке: свой блок на сайте, из текста биографии убираются
(навык biography)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site_export as b  # noqa: E402
import check_bio  # noqa: E402

BIO = """# Василий Jasieniew (1909–1990)

**В дереве:** [[Василий Prokop Jasieniew|@I1@]]

## Линия жизни

| Когда | Что | Где |
| --- | --- | --- |
| 1909 | родился | [[Вербичи]] |

## Каким он был

Высокий и худой.

## Воспоминания

### Внуки и война
*Вспоминает [[Анна Jasieniew|Анна]], внучка · А08, 53:25*

> «Он очень любил рассказывать и забывал, что хотел уйти.»

### Сорок человек на Рождество
*Вспоминает Мария, внучка · А08, 51:45*

Каждое Рождество вся семья собиралась у него.

## Открытые вопросы

- ❓ где служил
"""


class Split(unittest.TestCase):
    def test_items_and_text(self):
        text, items = b.split_recollections(b.own_head(BIO))
        self.assertEqual([i[0] for i in items], ["Внуки и война", "Сорок человек на Рождество"])
        self.assertEqual(items[0][1], "Вспоминает [[Анна Jasieniew|Анна]], внучка · А08, 53:25")
        self.assertTrue(items[0][2].startswith("> «Он очень"))
        self.assertNotIn("Воспоминания", text)
        self.assertNotIn("Рождество", text)
        self.assertIn("## Открытые вопросы", text)
        self.assertIn("## Каким он был", text)

    def test_translation_heading(self):
        pl = BIO.replace("## Воспоминания", "## Wspomnienia").replace("*Вспоминает", "*Wspomina")
        self.assertEqual(len(b.split_recollections(b.own_head(pl))[1]), 2)

    def test_none(self):
        text, items = b.split_recollections("## Линия жизни\n\nтекст\n")
        self.assertEqual(items, [])


class Questions(unittest.TestCase):
    def test_questions_out_sources_stay(self):
        text, qs = b.split_questions(b.own_head(BIO + "\n> Источники: [[Аудио 06]]\n"))
        self.assertEqual(qs, "- ❓ где служил")
        self.assertNotIn("Открытые вопросы", text)
        self.assertIn("> Источники: [[Аудио 06]]", text)
        self.assertIn("## Воспоминания", text)

    def test_translation(self):
        es = b.own_head(BIO.replace("## Открытые вопросы", "## Preguntas abiertas"))
        self.assertEqual(b.split_questions(es)[1], "- ❓ где служил")


class Check(unittest.TestCase):
    def errors(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x — биография.md"
            p.write_text(text, encoding="utf-8")
            return check_bio.check_file(p)[0]

    def test_ok(self):
        self.assertEqual(self.errors(BIO), [])

    def test_no_teller(self):
        bad = BIO.replace("*Вспоминает Мария, внучка · А08, 51:45*\n", "")
        self.assertTrue(any("кто вспоминает" in e for e in self.errors(bad)))

    def test_text_without_title(self):
        bad = BIO.replace("### Внуки и война\n", "")
        self.assertTrue(any("до первой сценки" in e for e in self.errors(bad)))

    def test_before_character(self):
        moved = BIO.replace("## Каким он был\n\nВысокий и худой.\n\n", "")
        moved = moved.replace("## Открытые вопросы", "## Каким он был\n\nВысокий.\n\n## Открытые вопросы")
        self.assertTrue(any("порядок" in e for e in self.errors(moved)))


if __name__ == "__main__":
    unittest.main()
