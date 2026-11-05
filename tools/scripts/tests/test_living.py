"""Кто живой (living.py): одно правило для сайта, сторожа личного и выгрузок; порог — [privacy] living_years."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates  # noqa: E402
import living  # noqa: E402

TODAY = date(2026, 11, 5)


class Living(unittest.TestCase):
    def alive(self, born, died=None, unknown=False):
        return living.is_living(born, died, unknown=unknown, today=TODAY)

    def test_threshold_110_years(self):
        self.assertTrue(self.alive("1971-03-05"))
        self.assertTrue(self.alive("1917"))           # 109 лет назад — ещё живой
        self.assertFalse(self.alive("1916"))          # 110 лет — уже нет
        self.assertFalse(self.alive("ABT 1890"))

    def test_death_means_not_living(self):
        self.assertFalse(self.alive("1971", "2020"))
        self.assertFalse(self.alive("1971", "(без даты)"))

    def test_unknown_birth_is_callers_choice(self):
        self.assertFalse(self.alive(None))
        self.assertTrue(self.alive("", unknown=True))

    def test_gdate_and_setting(self):
        self.assertTrue(self.alive(dates.parse_card("1971-03-08")))
        with mock.patch.object(living.paths, "tree_conf", return_value=50):
            self.assertFalse(self.alive("1964"))      # порог из ftree.toml



class SiteFollowsRule(unittest.TestCase):
    """Выгрузка сайта (site_export.living) — то же правило: документы живых — только по паролю."""

    def test_site_export_living(self):
        import site_export as b
        d = lambda born, died=None: {"f": {"born": born, "died": died}, "body": ""}  # noqa: E731
        with mock.patch.object(b, "lifespan", side_effect=lambda x: "–" if x["f"].get("died") else ""):
            self.assertTrue(b.living(d(f"{date.today().year - 40}-03-05")))
            self.assertFalse(b.living(d("1890")))            # без смерти, но 136 лет — не живой
            self.assertFalse(b.living(d("1971", "2020")))
            self.assertFalse(b.living(d(None)))              # год неизвестен — не закрываем паролем


if __name__ == "__main__":
    unittest.main()
