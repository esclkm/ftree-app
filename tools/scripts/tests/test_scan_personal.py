"""Сторож личного (scan_personal.py): на вымышленном словаре — что ловит и что пропускает; хуки клона ftree-app."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan_personal as sp  # noqa: E402

FAKE = sp.Dictionary(
    words={"Пупкин": "имя", "Простоквашино": "место", "Kotowski": "имя", "Заречец": "место"},
    exact={"abc-123-def-456": "номер карточки", "123456789": "телефон", "Тайная": "запрет (scan_deny)",
           **{f: "дата живого" for f in sp.date_forms(sp.dates.parse_card("1971-03-05"))}},
    allow={"Минск", "ул. Луговая, 5", "Pan Kotowski", "~высокий"},
    low={"Пупкин", "Kotowski", "Простоквашино", "Заречец", "Высокое", "Kleniuk", "Савелий"},
    addresses={"Садовая 12": "Лесогорск — Садовая, 12"},
    given={"Савелий", "Иван"},
)


class ScanPersonal(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sp, "dictionary", return_value=FAKE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def kinds(self, text):
        return sorted(h.kind for h in sp.scan_text("x", text))

    def test_names_places_and_numbers(self):
        self.assertEqual(self.kinds("Иван Пупкин из Простоквашино"), ["имя", "место"])
        self.assertEqual(self.kinds("person = 'abc-123-def-456'"), ["номер карточки"])
        self.assertEqual(self.kinds("Kotowski"), ["имя"])

    def test_fictional_card_number_passes(self):
        self.assertEqual(self.kinds("cr_id: ppl-001-aaa-001"), [])                 # вымышленный вид: «aaa» в середине
        self.assertEqual(self.kinds("cr_id: ppl-001-" "abc-001"), ["номер карточки"])

    def test_surname_inside_link_or_handle(self):  # ник склеен с именем: границ слова нет
        self.assertIn("в ссылке", self.kinds("https://instagram.com/annapupkin"))
        self.assertIn("в ссылке", self.kinds("facebook.com/ivpupkin"))
        self.assertTrue(self.kinds("x.com/kotowskiadam"))          # начало слова — ловит и «строчными»
        self.assertEqual(self.kinds("https://example.com/kotik"), [])                   # ссылка без слов дерева
        self.assertEqual(self.kinds("Pupkinsky"), ["латиницей"])                         # транслит — в любом регистре

    def test_any_case_and_ending(self):   # основа от 5 букв, любое окончание, любой регистр
        for text in ("о Пупкиных", "ПУПКИНА", "пупкинский переулок", "из Простоквашина", "в Заречце", "Заречца"):
            self.assertTrue(any(k.startswith("основа") for k in self.kinds(text)), text)
        self.assertEqual(self.kinds("Пупок и пупырышки"), [])                       # короче основы — не слово дерева

    def test_latin_card_found_in_cyrillic(self):   # «Kleniuk» в карточке — «Кленюки» в тексте
        self.assertTrue(self.kinds("о Кленюках"))

    def test_common_lower_word_and_name_forms(self):
        self.assertEqual(self.kinds("высокое качество"), [])   # «~высокий» в scan_allow: строчными — общее
        self.assertTrue(self.kinds("город Высокое"))
        self.assertEqual(self.kinds("сын Савелия, Савельевич"), [])                 # падеж имени и отчество — не фамилия

    def test_living_birth_date_any_spelling(self):
        for text in ("born 1971-03-05", "род. 05.03.1971", "5 марта 1971 г.", "5 MAR 1971", "03/05/1971"):
            self.assertIn("дата живого", self.kinds(text), text)
        self.assertEqual(self.kinds("15.03.1971 и 1971-03-15"), [])                 # другой день — не он

    def test_street_and_house_from_place_card(self):
        for text in ("Садовая, 12", "Лесогорск_Садовая-12.jpg", "ул. Садовая д. 12", "садовая_12"):
            self.assertIn("адрес из карточки", self.kinds(text), text)
        self.assertEqual(self.kinds("Садовая, 125"), [])

    def test_escape_before_word(self):   # «\tПупкин» в строке кода
        self.assertTrue(self.kinds("x = 'a\\tПупкин'"))

    def test_underscore_separates_words(self):  # имена в именах файлов: «Иван_Пупкин_1950.jpg»
        self.assertEqual(self.kinds("Иван_Пупкин_1950.jpg"), ["имя"])

    def test_phone_in_any_spelling(self):
        self.assertIn("телефон", self.kinds("звонить 123 456 789"))
        self.assertIn("телефон", self.kinds("+48 {} 000 111".format(600)))

    def test_contacts_and_documents_by_shape(self):
        self.assertEqual(self.kinds("пишите на kto" "@mail.ru"), ["почта"])
        self.assertIn("адрес с номером", self.kinds("г. Минск, ул. Кленовая, 7-12"))
        self.assertEqual(self.kinds("паспорт MP1234567"), ["номер документа"])
        self.assertEqual(self.kinds("Тайная тропа"), ["запрет (scan_deny)"])

    def test_allowed_and_service_addresses_pass(self):
        self.assertEqual(self.kinds("Минск, ул. Луговая, 5; noreply@anthropic.com; git@github.com:x/y"), [])

    def test_allowed_phrase_only_whole(self):   # автор приложения в LICENSE — да, та же фамилия при другом имени — нет
        self.assertEqual(self.kinds("Copyright (c) 2026 Pan Kotowski"), [])
        self.assertEqual(self.kinds("Jan Kotowski"), ["имя"])

    def test_file_name_is_checked(self):
        self.assertEqual([h.kind for h in sp.scan_blob("docs/Пупкин_1950.jpg", b"\x89PNG\0")], ["имя файла: имя"])


class Hooks(unittest.TestCase):
    """Хуки, которые `install` ставит в клон ftree-app: на словаре дерева-образца (FTREE_ROOT = образец)."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="ftree-app-hooks-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.assertEqual(sp.cmd_install(str(self.repo)), 0)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)

    def commit(self, name, text, message):
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", name)
        return self.git("commit", "-q", "-m", message)

    def test_clean_commit_passes(self):
        if not shutil.which("gitleaks"):
            self.skipTest("нет gitleaks")
        r = self.commit("a.py", "x = 1\n", "Первый коммит")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_personal_word_in_message_stops_commit(self):   # сторож message — в хуке commit-msg
        if not shutil.which("gitleaks"):
            self.skipTest("нет gitleaks")
        r = self.commit("a.py", "x = 1\n", "Правка для Прокопа Ясенева")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("текст коммита", r.stdout + r.stderr)

    def test_push_checks_again(self):   # pre-push: личное и gitleaks по всем уходящим коммитам, и после --no-verify
        if not shutil.which("gitleaks"):
            self.skipTest("нет gitleaks")
        remote = Path(tempfile.mkdtemp(prefix="ftree-app-remote-"))
        self.addCleanup(shutil.rmtree, remote, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.assertEqual(self.commit("a.py", "x = 1\n", "Первый").returncode, 0)
        r = self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (self.repo / "b.py").write_text("# Ясенев\n", encoding="utf-8")
        self.git("add", "b.py")
        self.git("commit", "-q", "--no-verify", "-m", "мимо pre-commit")
        self.assertNotEqual(self.git("push", "-q", "origin", "HEAD:refs/heads/main").returncode, 0)

    def test_personal_word_in_file_stops_commit(self):
        r = self.commit("a.py", "# пример: Ясенев\n", "Правка")
        self.assertNotEqual(r.returncode, 0)

    def test_secret_stops_commit(self):
        if not shutil.which("gitleaks"):
            self.skipTest("нет gitleaks")
        token = "ghp_" + "aZ3kQ9mX7pL2" + "vB8nR4tY6wE1" + "sD5fG0hJ2uI7"   # вымышленный токен GitHub; кусками — чтобы
        # gitleaks не нашёл его в самом этом файле
        r = self.commit("a.py", f'token = "{token}"\n', "Правка")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gitleaks", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
