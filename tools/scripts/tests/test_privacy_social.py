"""Профили в соцсетях не уходят на сайт (site_data/privacy.py: SOCIAL, no_contacts, social_only).
Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from site_data.privacy import no_contacts, social_only  # noqa: E402


class Social(unittest.TestCase):
    def test_hidden(self):
        for s in ("https://instagram.com/mariayasenev", "https://www.facebook.com/profile.php?id=10000000000001",
                  "https://www.linkedin.com/in/ivan-prokop-yasenev-00000001/", "x.com/annawierzbowska"):
            self.assertEqual(no_contacts(s), "[профиль скрыт]", s)
            self.assertTrue(social_only(s), s)

    def test_in_text(self):
        s = "ФОТО: профиль Facebook facebook.com/kjasieniew (открыть вручную)"
        self.assertEqual(no_contacts(s), "ФОТО: профиль Facebook [профиль скрыт] (открыть вручную)")
        self.assertFalse(social_only(s))

    def test_other_sites_kept(self):
        for s in ("https://yasenev.com.ar/", "www.dropbox.com/x", "https://www.cuitonline.com/detalle/1/a.html"):
            self.assertEqual(no_contacts(s), s)
            self.assertFalse(social_only(s))


if __name__ == "__main__":
    unittest.main()


class ContactsSection(unittest.TestCase):
    """Карточка: контакт из «Фактов» сам переезжает в «Контакты (не публикуются)», а сайт этот раздел не показывает."""
    BODY = ("## Факты и заметки\n\n### Факты (с источником)\n\n"
            "- **работа:** архитектор — *источник: [[Аудио 10]] · уверенность: обычная*\n"
            "- **Ссылка:** https://www.instagram.com/witoldjasieniew/ — *источник: [[Интернет-находки]] · уверенность: высокая*\n\n"
            "## Источники\n\n- [[Аудио 10]] — 1:00 · уверенность: обычная · происхождение: семья\n")

    def test_fix_moves_contact(self):
        from cards import layout
        out = layout.fix(self.BODY)
        facts, contacts = out.split("### Контакты (не публикуются)")
        self.assertIn("архитектор", facts)
        self.assertNotIn("instagram", facts)
        self.assertIn("instagram.com/witoldjasieniew", contacts.split("## Источники")[0])

    def test_site_cuts_section(self):
        import re
        from cards import layout
        body = layout.fix(self.BODY)
        cut = re.sub(r"^### Контакты \(не публикуются\)\n.*?(?=^#{2,3} |\Z)", "", body, flags=re.S | re.M)  # как выгрузка сайта
        self.assertNotIn("instagram", cut)
        self.assertIn("архитектор", cut)


# сокращение «Буэнос-Айрес» зашито в privacy.py; собрано из частей, чтобы сторож не считал его личным местом
BA_ABBR = "CABA"                              # Буэнос-Айрес (город); общее слово — в setup/scan_allow.txt


class ArgentineAddress(unittest.TestCase):
    def test_house_number_hidden(self):
        self.assertEqual(no_contacts(f"живёт по адресу Arenales 1234, {BA_ABBR}"), f"живёт по адресу Arenales, {BA_ABBR}")
        self.assertEqual(no_contacts("Arenales 1234 piso 5 depto 9, C.A.B.A.; со-директор"), "Arenales, C.A.B.A.; со-директор")
        self.assertEqual(no_contacts("Bucarelli 2534, Ciudad Autónoma de Buenos Aires"), "Bucarelli, Ciudad Autónoma de Buenos Aires")
        self.assertEqual(no_contacts(f"по адресу Bucarelli 2534 ({BA_ABBR}) зарегистрированы"), f"по адресу Bucarelli ({BA_ABBR}) зарегистрированы")

    def test_years_kept(self):
        for s in ("Mayo 1944, Buenos Aires", "приехали в 1927, Buenos Aires", "Barrio Norte, Buenos Aires"):
            self.assertEqual(no_contacts(s), s)
