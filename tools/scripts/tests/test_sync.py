import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import datetime  # noqa: E402

from sync import familio_note, fs_note, mh_note, mh_others_note, plan_note, split_touched  # noqa: E402
import paths  # noqa: E402
BIOS = paths.rel(paths.BIOS)
FINDINGS = paths.rel(paths.FINDINGS)
PEOPLE = paths.rel(paths.PEOPLE)
PHOTO_CATALOG = paths.rel(paths.PHOTO_CATALOG)
RESEARCH_NEXT = paths.rel(paths.RESEARCH_NEXT)
TREE_DATA = paths.rel(paths.TREE_DATA)

D = datetime.date


class SplitTouched(unittest.TestCase):
    def test_only_derived_outputs_go_into_commit(self):
        ours, foreign = split_touched({
            f"{PEOPLE}/Иван Дубняк.md",
            f"{BIOS}/Иван Дубняк — биография.md",
            PHOTO_CATALOG,
            RESEARCH_NEXT,                    # соседняя сессия правит план — не наш пересчёт
            f"{FINDINGS}/отчёт_2026-10-14.md",
            "tools/scripts/sync.py",
        })
        self.assertEqual(ours, [f"{BIOS}/Иван Дубняк — биография.md",
                                f"{PEOPLE}/Иван Дубняк.md", PHOTO_CATALOG])
        self.assertEqual(foreign, [f"{FINDINGS}/отчёт_2026-10-14.md", RESEARCH_NEXT,
                                   "tools/scripts/sync.py"])

    def test_lookalike_prefix_is_foreign(self):
        self.assertEqual(split_touched({f"{TREE_DATA}/enriched.ged"}), ([], [f"{TREE_DATA}/enriched.ged"]))

    def test_empty(self):
        self.assertEqual(split_touched(set()), ([], []))



class LagNotes(unittest.TestCase):
    """Строки «что отстало» при старте сессии: только когда есть что делать."""

    def test_myheritage_counts_work(self):
        plan = {"snapshot": "2026-10-21T10:46:31Z",
                "to_site": [{"action": "field"}] * 35 + [{"action": "link"}] * 5 + [{"action": "person"}] * 52}
        self.assertEqual(mh_note(plan, False), "MyHeritage: снимок сайта 21.10, на сайт — правок полей 35, связей 5, "
                                               "новых людей 52 — tools/mh push")
        self.assertIn("план устарел", mh_note(plan, True))

    def test_myheritage_nothing_to_do(self):
        self.assertIsNone(mh_note({"snapshot": "2026-10-21T00:00:00Z", "to_site": []}, False))
        self.assertIn("плана нет", mh_note(None, False))

    def test_mh_others(self):
        d = datetime.date
        self.assertIn("не на учёте", mh_others_note(None, d(2026, 10, 30)))
        self.assertIsNone(mh_others_note(d(2026, 10, 20), d(2026, 10, 30)))
        self.assertIn("снимок 01.09", mh_others_note(d(2026, 9, 1), d(2026, 10, 30)))

    def test_familio(self):
        self.assertEqual(familio_note(D(2026, 10, 15), 34, 169), "Familio: перенос 15.10, после — карточек новых 34, "
                                                                  "изменённых 169 (грузим только связанных) — familio_sync.py")
        self.assertIsNone(familio_note(D(2026, 10, 15), 0, 0))

    def test_familysearch_due_after_two_weeks(self):
        self.assertIsNone(fs_note(D(2026, 10, 17), D(2026, 10, 31), 0))
        self.assertIn("пора проверить", fs_note(D(2026, 10, 17), D(2026, 11, 1), 0))
        note = fs_note(D(2026, 10, 17), D(2026, 10, 24), 3)
        self.assertNotIn("пора проверить", note)
        self.assertIn("ближней родни: 3", note)

    def test_search_plan(self):
        today = D(2026, 10, 24)
        self.assertIsNone(plan_note(D(2026, 10, 24), D(2026, 10, 20), [D(2026, 10, 24), D(2026, 10, 1)], today))
        self.assertEqual(plan_note(D(2026, 10, 21), D(2026, 10, 20), [D(2026, 10, 22), D(2026, 10, 24)], today),
                         "план поиска отстал от находок: отчётов findings/ новее «Обновлено»: 2 — ПОИСК_ДАЛЬШЕ.md")
        self.assertIn("«Дальше по порядку» на 13.10", plan_note(D(2026, 10, 24), D(2026, 10, 13), [], today))


if __name__ == "__main__":
    unittest.main()
