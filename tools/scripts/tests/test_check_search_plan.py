import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_search_plan import check  # noqa: E402

PLAN = """Обновлено: 08.10.2026.
Следующий свободный номер: О3, П1, Р1, Н1, А2, С1.
"""
OPEN = """| № | Ветка | Что найти | Где | Шаг | Отчёт |
|---|---|---|---|---|---|
| О1 | Ясеневы | чей сын [[Роман Jasieniew\\|Роман]] | Заречье | смотреть | — |
| О2 | Дубняки | дворы | Лужки | смотреть | — |
| А1 | Дубняки | крещение | НИАБ Гродно (пакет 7) | 🟢 | — |
"""
DONE = """| Дата | Было | Ветка | Что | Итог | Отчёт |
|---|---|---|---|---|---|
| 08.10.2026 | О0 | Вика | Лесогорск | ⛔ пусто | — |
| — | — | все ветки | Matricula | ⛔ пусто | — |
"""


class CheckSearchPlan(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(check(PLAN, OPEN, DONE, [("_x_2026-10-08.md", ("2026", "10", "08"))]), [])

    def test_closed_still_open(self):
        errs = check(PLAN, OPEN, DONE.replace("| О0 |", "| О2 |"), [])
        self.assertTrue(any("О2 закрыт" in e for e in errs))

    def test_done_mark_in_open(self):
        errs = check(PLAN, OPEN.replace("| Заречье |", "| Заречье ✅ |"), DONE, [])
        self.assertTrue(any("О1: в открытой" in e for e in errs))

    def test_columns(self):
        errs = check(PLAN, OPEN.replace("| дворы |", "| дворы | лишняя |"), DONE.replace("| Лесогорск |", "|"), [])
        self.assertTrue(any("О2: колонок 7" in e for e in errs))
        self.assertTrue(any("«Сделано»: колонок 5" in e for e in errs))

    def test_duplicate_and_next(self):
        errs = check(PLAN.replace("О3, П1", "О1, П1"), OPEN.replace("| О2 |", "| О1 |"), DONE, [])
        self.assertTrue(any("повторяется" in e for e in errs))
        self.assertTrue(any("Следующий свободный" in e for e in errs))

    def test_letter_numbers(self):
        errs = check(PLAN.replace("А2", "А1"), OPEN, DONE, [])
        self.assertTrue(any("для А" in e for e in errs))

    def test_newer_findings(self):
        errs = check(PLAN, OPEN, DONE, [("_new_2026-10-09.md", ("2026", "10", "09"))])
        self.assertTrue(any("_new_2026-10-09.md" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
