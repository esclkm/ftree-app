"""Переводы мест, фактов и фото (tr_store.py): файл читается так же, как пишется; отпечатки не зависят от пробелов."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402
import tr_store as S  # noqa: E402
from cards.places import about_of, text_of  # noqa: E402


class TrStore(unittest.TestCase):
    def test_path_one_scheme(self):
        self.assertEqual(paths.tr_path("es", "places", "Вербичи"), paths.TRANSLATIONS / "es" / "places" / "Вербичи.md")

    def test_facts_round_trip(self):
        src = {"label": "смерть (дата)", "text": "26.03.1990 — *источник: [[Рукопись]], лист 1*", "reasoning": "",
               "locators": "лист 1 ¦ 54:39"}
        k = S.fact_key(src["label"], src["text"], src["reasoning"])
        body = S.facts_body([(k, src)])
        got = {key: S.field_lines(v) for key, v in S.sections(body).items()}
        self.assertEqual(got, {k: {f: v for f, v in src.items() if v}})

    def test_fact_key_changes_with_text(self):
        self.assertNotEqual(S.fact_key("смерть", "1990", ""), S.fact_key("смерть", "26.03.1990", ""))
        self.assertEqual(S.fact_key("смерть", "1990", ""), S.fact_key("смерть", "1990", None))

    def test_photo_round_trip(self):
        r = {"desc": "стадион, 1945", "whose": "семья жила рядом", "exact": "", "note": "", "section": "Лесогорск"}
        self.assertEqual(S.sections(S.photo_body(S.photo_source(r))), {k: v for k, v in r.items() if v})
        self.assertEqual(S.photo_hash(r), S.photo_hash({**r, "desc": "стадион,  1945"}))

    def test_place_translation_parts(self):
        tr = "## Sobre el lugar\n\nAldea.\n\n## Estados por año\n\n- x\n\n## Historia del lugar\n\n- 1921."
        self.assertEqual(about_of(tr), {"es": "Aldea."})
        self.assertEqual(text_of("# Вербичи\n\n## О месте\n\nДеревня.\n\n## Государства по годам\n\n- x\n\n## История\n\nТекст."),
                         "## История\n\nТекст.")
        self.assertIn("Historia del lugar", text_of(tr))


if __name__ == "__main__":
    unittest.main()
