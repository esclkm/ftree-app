import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from familysearch_export import alias_ok, STUB  # noqa: E402


class AliasTest(unittest.TestCase):
    NAMES = {"Прокоп", "Савва"}

    def test_name_and_surname(self):
        self.assertTrue(alias_ok("Петр Клёнюк", self.NAMES))
        self.assertTrue(alias_ok("Eustachij Brzozowski", self.NAMES))

    def test_no_patronymic_or_notes(self):
        self.assertFalse(alias_ok("Николай Сергеев Кленюк", self.NAMES))
        self.assertFalse(alias_ok("Agata żona Eustachia", self.NAMES))
        self.assertFalse(alias_ok("Пелагея Прокопьевна", self.NAMES))
        self.assertFalse(alias_ok("Александра Прокопова", self.NAMES))

    def test_stub(self):
        self.assertTrue(STUB.match("Первая жена Акима Ясенева"))
        self.assertTrue(STUB.match("Unknown I266"))
        self.assertFalse(STUB.match("Мария Ясенева"))


if __name__ == "__main__":
    unittest.main()
