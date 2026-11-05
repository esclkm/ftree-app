"""Настройщик (setup.py): разбор setup.toml, файл путей env и порядок, в котором берутся настройки (paths.py).

Запуск: python3 -m unittest discover tools/scripts/tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402
import setup  # noqa: E402

DATA = Path("/tmp/ftree-test-data")


class ParseConfigTest(unittest.TestCase):
    def parse(self, text):
        return setup.parse_config(text, DATA)

    def test_dev_mode_dot_is_data_itself(self):
        cfg = self.parse('[app]\npath = "."\n')
        self.assertEqual(cfg.mode, "dev")
        self.assertEqual(cfg.app_dir, DATA.resolve())

    def test_dev_mode_home_path(self):
        cfg = self.parse('[app]\npath = "~/apps/tree-app"\n')
        self.assertEqual(cfg.app_dir, (Path.home() / "apps/tree-app").resolve())

    def test_version_mode(self):
        cfg = self.parse('[app]\nrepo = "https://example.invalid/app"\ntag = "v1.4"\ndir = "/opt/tree-app"\n')
        self.assertEqual((cfg.mode, cfg.tag, cfg.repo), ("version", "v1.4", "https://example.invalid/app"))
        self.assertEqual(cfg.app_dir, Path("/opt/tree-app").resolve())

    def test_errors_are_plain_words(self):
        for text in ('[app]\npath = "."\ntag = "v1"\n',                       # оба режима сразу
                     '[app]\nrepo = "r"\ntag = "v1"\n',                         # версия без dir
                     '',                                                         # нет [app]
                     '[app]\npath = "."\n[features]\nfax = true\n',             # незнакомая возможность
                     '[app]\npath = "."\n[features]\nsite_publish = []\n',  # куда выкладывать — в ftree.toml, не здесь
                     '[app]\npath = "."\n[features]\nasr = "yes"\n',             # не true/false
                     '[app]\npath = "."\n[places]\nhome = "/x"\n',               # незнакомая папка
                     '[app\n'):                                                  # не TOML
            with self.subTest(text=text), self.assertRaises(setup.SetupError):
                self.parse(text)

    def test_defaults(self):
        cfg = self.parse('[app]\npath = "."\n[features]\nasr = true\n')
        self.assertTrue(cfg.on("asr"))
        self.assertFalse(cfg.on("photo_restore"))
        self.assertIsNone(cfg.on("site_publish"), "куда выкладывать — в ftree.toml дерева ([[site.target]])")
        self.assertEqual(cfg.keychain["crypt_salt"], "rclone-crypt-salt")
        self.assertEqual(cfg.keychain_named, frozenset(), "записи Связки ключей не названы — их не проверяем")
        self.assertIn("photo_restore", setup.off_features(cfg))

    def test_data_setup_toml_parses(self):
        cfg = setup.load_config(paths.ROOT)
        self.assertIn(cfg.mode, ("dev", "version"))


class EnvFileTest(unittest.TestCase):
    def test_app_inside_data_writes_only_root(self):
        cfg = setup.parse_config('[app]\npath = "."\n[places]\narchives = "/srv/archives"\n', DATA)
        self.assertEqual(setup.desired_env(cfg), {"FTREE_ROOT": str(DATA), "ARCHIVES_LOCAL": "/srv/archives"})

    def test_separate_app_writes_app(self):
        cfg = setup.parse_config('[app]\npath = "/srv/tree-app"\n', DATA)
        self.assertEqual(setup.desired_env(cfg)["FTREE_APP"], str(Path("/srv/tree-app").resolve()))

    def test_diff_missing_and_changed(self):
        missing, differ = setup.env_diff({"FTREE_ROOT": "/old", "X": "1"}, {"FTREE_ROOT": "/new", "FTREE_APP": "/a"})
        self.assertEqual(missing, {"FTREE_APP": "/a"})
        self.assertEqual(differ, {"FTREE_ROOT": ("/old", "/new")})
        self.assertEqual(setup.env_diff({"A": "~/x"}, {"A": str(Path.home() / "x")}), ({}, {}))

    def test_merge_keeps_foreign_lines_and_is_idempotent(self):
        old = "# мой комментарий\nCDP_PORT=9444\nexport FTREE_ROOT=/old\n"
        new = setup.merge_env(old, {"FTREE_ROOT": "/new", "FTREE_APP": "/app"})
        self.assertEqual(new, "# мой комментарий\nCDP_PORT=9444\nFTREE_ROOT=/new\nFTREE_APP=/app\n")
        self.assertEqual(setup.merge_env(new, {"FTREE_ROOT": "/new", "FTREE_APP": "/app"}), new)

    def test_new_file_has_header_and_reads_back(self):
        text = setup.merge_env("", {"FTREE_ROOT": "/data"})
        self.assertTrue(text.startswith("#"))
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "env").write_text(text, encoding="utf-8")
        self.assertEqual(paths._read_env_file(tmp / "env"), {"FTREE_ROOT": "/data"})


class SettingOrderTest(unittest.TestCase):
    """ключ команды > переменная окружения > файл env > ftree.toml > значение по умолчанию."""

    def setUp(self):
        for patcher in (mock.patch.dict(paths._OVERRIDES, {}, clear=True),
                        mock.patch.dict(paths._ENV_FILE_VALUES, {}, clear=True),
                        mock.patch.dict(os.environ, {}, clear=False),
                        mock.patch.object(paths, "CONFIG", {"demo": {"key": "из toml"}})):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("FTREE_DEMO", None)

    def value(self):
        return paths.setting("FTREE_DEMO", "по умолчанию", toml="demo.key")

    def test_order(self):
        paths.CONFIG = {}
        self.assertEqual(self.value(), "по умолчанию")
        paths.CONFIG = {"demo": {"key": "из toml"}}
        self.assertEqual(self.value(), "из toml")
        paths._ENV_FILE_VALUES["FTREE_DEMO"] = "из файла env"
        self.assertEqual(self.value(), "из файла env")
        os.environ["FTREE_DEMO"] = "из окружения"
        self.assertEqual(self.value(), "из окружения")
        paths.override("FTREE_DEMO", "из ключа")
        self.assertEqual(self.value(), "из ключа")

    def test_empty_values_do_not_win(self):
        os.environ["FTREE_DEMO"] = ""
        paths.override("FTREE_DEMO", None)
        self.assertEqual(self.value(), "из toml")


class RootOrderTest(unittest.TestCase):
    """Папка данных: переменная > дерево, внутри которого стоишь > FTREE_ROOT из файла env > дерево самого скрипта."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ftree_setup_")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("inside", "fromfile"):
            (self.tmp / name).mkdir()
            (self.tmp / name / "ftree.toml").write_text("[tree]\n", encoding="utf-8")
        (self.tmp / "outside").mkdir()
        env = {k: v for k, v in os.environ.items() if k != paths.ROOT_ENV}
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.dict(paths._ENV_FILE_VALUES, {paths.ROOT_ENV: str(self.tmp / "fromfile")},
                                        clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_inside_a_tree_beats_env_file(self):
        self.assertEqual(paths.find_root(self.tmp / "inside"), self.tmp / "inside")

    def test_outside_any_tree_uses_env_file(self):
        self.assertEqual(paths.find_root(self.tmp / "outside"), self.tmp / "fromfile")

    def test_variable_beats_everything(self):
        os.environ[paths.ROOT_ENV] = str(self.tmp / "outside")
        self.assertEqual(paths.find_root(self.tmp / "inside"), self.tmp / "outside")


if __name__ == "__main__":
    unittest.main()


class DestinationItemsTest(unittest.TestCase):
    """rodo setup проверяет то, что задано в ftree.toml дерева, а не облако и хостинг вообще."""

    def test_nothing_set_nothing_required(self):
        cfg = setup.parse_config('[app]\npath = "."\n', DATA)
        got = list(setup.storage_items(cfg, {}, full=False)) + list(setup.site_items(cfg, {}))
        self.assertTrue(all(i.ok and i.group == setup.TASK for i in got), [i.what for i in got])

    def test_checks_named_remote_and_hosting(self):
        import destinations
        cfg = setup.parse_config('[app]\npath = "."\n', DATA)
        tree = {"tree": {"name": "t"},
                "storage": {"media": {"kind": "rclone", "address": "box:Фото/"},
                            "private": {"kind": "rclone", "address": "box-crypt:", "encrypted": True}},
                "site": {"target": [{"kind": "cloudflare-pages", "project": "p", "url": "https://p.example"},
                                    {"kind": "netlify", "site": "m"}]}}
        with mock.patch.object(setup, "rclone_remotes", return_value={"box:": "drive", "box-crypt:": "drive"}), \
                mock.patch.object(setup.shutil, "which", return_value="/usr/bin/rclone"):
            got = {i.what: i.ok for i in setup.storage_items(cfg, destinations.stores(tree), full=False)}
        self.assertTrue(got["медиа: rclone видит box: ([storage.media])"])
        self.assertFalse(got["медиа: box-crypt: шифрует ([storage.private] encrypted = true)"])
        whats = [i.what for i in setup.site_items(cfg, tree)]
        self.assertIn("сайт: вход в Cloudflare (wrangler)", whats)
        self.assertIn("сайт: вход в Netlify", whats)
        self.assertTrue(any("секрет зеркала" in w and "/t/proxy_key" in w for w in whats), whats)

