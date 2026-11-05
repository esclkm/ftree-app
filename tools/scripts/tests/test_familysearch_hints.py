import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import familysearch_hints as h  # noqa: E402

LESOGORSK = {"type": "HISTORICAL_RECORD", "id": "1:1:ZZ3C-QQ3", "name": "Прокоп", "life": "1861–Deceased",
           "place": "Лесогорский"}
COPY = dict(LESOGORSK, id="1:1:ZZ4D-QQ4")
EDIT = {"date": "March 1, 2024", "who": "Editor4720", "type": "CREATE_PERSON"}


class News(unittest.TestCase):
    def test_known_hint_is_not_news(self):
        before = {"ZZ1A-QQ1": {"hints": [LESOGORSK], "edits": []}}
        self.assertEqual(h.news({"ZZ1A-QQ1": {"hints": [LESOGORSK], "edits": []}}, before), [])

    def test_second_copy_of_record_is_news(self):
        before = {"ZZ1A-QQ1": {"hints": [LESOGORSK], "edits": []}}
        got = h.news({"ZZ1A-QQ1": {"hints": [LESOGORSK, COPY], "edits": []}}, before)
        self.assertEqual([(fs, kind) for fs, kind, _ in got], [("ZZ1A-QQ1", "подсказка")])
        self.assertIn("ZZ4D-QQ4", got[0][2])

    def test_person_absent_from_snapshot_shows_everything(self):
        got = h.news({"ZZ2B-QQ2": {"hints": [], "edits": [EDIT]}}, {})
        self.assertEqual(got, [("ZZ2B-QQ2", "правка", "March 1, 2024 Editor4720 CREATE_PERSON")])

    def test_known_edit_is_not_news(self):
        before = {"ZZ2B-QQ2": {"hints": [], "edits": [EDIT]}}
        self.assertEqual(h.news({"ZZ2B-QQ2": {"hints": [], "edits": [EDIT]}}, before), [])


if __name__ == "__main__":
    unittest.main()
