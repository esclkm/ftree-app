"""Куда выкладывать сайт и где хранить медиа (destinations.py, media.py) — только по настройкам дерева, без умолчаний.

Главное: новое дерево (rodo init + sample.ged) ничего никуда не отправляет — ни медиа, ни сайт, а команда объясняет,
что вписать. Плюс разбор [storage.*] и [[site.target]] и отправка в хранилища вида local и rclone crypt.
Запуск: python3 -m unittest discover tools/scripts/tests
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import destinations as d  # noqa: E402
import media  # noqa: E402
import paths  # noqa: E402

HAS_RCLONE = shutil.which("rclone") is not None


def cfg(text: str) -> dict:
    return tomllib.loads(text)


class StorageSettingsTest(unittest.TestCase):
    def test_nothing_set_means_nowhere(self):
        self.assertEqual(d.stores(cfg("")), {})
        self.assertEqual(d.stores(cfg("[storage]\npush_after_commit = true\n")), {})
        self.assertFalse(d.push_after_commit(cfg("[storage]\npush_after_commit = true\n")), "хранилища нет — слать некуда")
        self.assertEqual(d.stores(cfg('[storage.media]\nkind = "none"\n')), {})

    def test_rclone_and_local(self):
        s = d.stores(cfg('[storage]\npush_after_commit = true\n'
                         '[storage.media]\nkind = "rclone"\naddress = "box:Семья"\n'
                         '[storage.private]\nkind = "local"\naddress = "~/backup"\n'))
        self.assertEqual(s["media"].address, "box:Семья/")
        self.assertFalse(s["media"].encrypted)
        self.assertEqual(s["private"].address, str(Path.home() / "backup") + "/")
        self.assertTrue(d.push_after_commit(cfg('[storage]\npush_after_commit = true\n'
                                                '[storage.media]\nkind = "local"\naddress = "/x"\n')))

    def test_errors_in_plain_words(self):
        for text in ('[storage.media]\nkind = "ftp"\naddress = "x"\n',            # незнакомый вид
                     '[storage.media]\nkind = "rclone"\n',                          # нет адреса
                     '[storage.media]\nkind = "rclone"\naddress = "папка"\n',       # у rclone адрес «remote:»
                     '[storage.private]\nkind = "local"\naddress = "/x"\nencrypted = true\n',  # папка не шифрует
                     '[storage.media]\nkind = "local"\naddress = "/x"\nbucket = "y"\n'):       # незнакомый ключ
            with self.subTest(text=text), self.assertRaises(d.ConfigError):
                d.stores(cfg(text))


class SiteTargetsTest(unittest.TestCase):
    def test_no_targets_no_publish(self):
        self.assertEqual(d.site_targets(cfg("[site]\npublish_after_push = true\n")), [])
        self.assertFalse(d.publish_after_push(cfg("[site]\npublish_after_push = true\n")))

    def test_roles_follow_kind(self):
        t = d.site_targets(cfg('[site]\n'
                               '[[site.target]]\nkind = "cloudflare-pages"\nproject = "p"\nurl = "https://p.example"\n'
                               '[[site.target]]\nkind = "netlify"\nsite = "m"\n'
                               '[[site.target]]\nkind = "cloudflare-worker"\nname = "p"\nmanual = true\n'))
        self.assertEqual([(x["kind"], x["role"], x["name"]) for x in t],
                         [("cloudflare-pages", "main", "p"), ("netlify", "mirror", "m"), ("cloudflare-worker", "mirror", "p")])
        self.assertTrue(t[2]["manual"])

    def test_errors_in_plain_words(self):
        for text in ('[[site.target]]\nkind = "ftp"\nname = "x"\n',                         # незнакомый вид
                     '[[site.target]]\nkind = "cloudflare-pages"\n',                         # нет имени проекта
                     '[[site.target]]\nkind = "netlify"\nsite = "m"\nrole = "main"\n',       # netlify — только зеркало
                     '[[site.target]]\nkind = "netlify"\nsite = "m"\n',                      # зеркало без основного
                     '[[site.target]]\nkind = "cloudflare-pages"\nproject = "p"\nurl = "http://p"\n'):  # не https
            with self.subTest(text=text), self.assertRaises(d.ConfigError):
                d.site_targets(cfg("[site]\n" + text))

    def test_run_files_named_after_tree(self):
        self.assertEqual(d.run_file("media.log", cfg('[tree]\nname = "ясень"\n')), Path("/tmp/ftree_ясень_media.log"))
        self.assertEqual(d.tree_name(cfg('[tree]\nname = "a b/c"\n')), "a-b-c")


class FreshTreeSendsNothingTest(unittest.TestCase):
    """Дерево из rodo init + sample.ged: ни хранилища, ни целей — ничего никуда, и сказано, что вписать."""

    def test_fresh_tree_has_no_destinations(self):
        self.assertEqual(d.stores(), {})
        self.assertEqual(d.site_targets(), [])
        self.assertFalse(d.push_after_commit())
        self.assertFalse(d.publish_after_push())
        values = paths.as_dict()
        self.assertEqual((values["MEDIA_PUSH_AFTER_COMMIT"], values["SITE_PUBLISH_AFTER_PUSH"]), ("", ""))

    def test_media_push_explains_and_sends_nothing(self):
        photo = paths.PHOTOS_FAMILY / "Проба_1950.jpg"
        photo.parent.mkdir(parents=True, exist_ok=True)
        photo.write_bytes(b"photo")
        try:
            out = io.StringIO()
            with mock.patch.object(media, "rclone", side_effect=AssertionError("rclone звать нельзя")), \
                    mock.patch.dict(os.environ, {"MEDIA_REMOTE": "", "MEDIA_OPEN_REMOTE": ""}), \
                    contextlib.redirect_stdout(out):
                code = media.main(["push"])
            self.assertEqual(code, 0)
            self.assertIn("[storage.media]", out.getvalue())
            self.assertIn("никуда не отправляется", out.getvalue())
            self.assertFalse(any(r.get("pushed") for r in media.load(media.make_ctx()).values()))
        finally:
            photo.unlink()

    def test_hooks_do_nothing(self):
        """post-commit без настройки не отправляет; pre-push спрашивает настройку, а не выкладывает всегда."""
        hooks = paths.APP / "tools" / "githooks"
        self.assertIn("MEDIA_PUSH_AFTER_COMMIT", (hooks / "post-commit").read_text(encoding="utf-8"))
        self.assertIn("SITE_PUBLISH_AFTER_PUSH", (hooks / "pre-push").read_text(encoding="utf-8"))


@unittest.skipUnless(HAS_RCLONE, "нет rclone")
class StorageFromSettingsTest(unittest.TestCase):
    """Хранилища из ftree.toml дерева: local для фото, rclone crypt для PDF; пометка encrypted сторожит вид remote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dest_test_"))
        self.root = self.tmp / "tree"
        self.cloud, self.open = self.tmp / "cloud", self.tmp / "open"
        self.cloud.mkdir()
        pw = subprocess.run(["rclone", "obscure", "test-password"], capture_output=True, text=True).stdout.strip()
        conf = self.tmp / "rclone.conf"
        conf.write_text(f"[sealed]\ntype = crypt\nremote = {self.cloud}\npassword = {pw}\n"
                        f"[plain]\ntype = alias\nremote = {self.cloud}\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"RCLONE_CONFIG": str(conf), "MEDIA_NO_KEYCHAIN": "1",
                                                "MEDIA_CACHE": str(self.tmp / "cache"), "MEDIA_REMOTE": "",
                                                "MEDIA_OPEN_REMOTE": ""})
        self.env.start()
        for rel, data in ((f"{paths.rel(paths.PHOTOS_FAMILY)}/Проба_1950.jpg", b"photo"),
                          (f"{paths.rel(paths.FAMILY_ARCHIVE)}/Doc1.pdf", b"pdf-1")):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(data)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def push(self, private: str) -> tuple[int, str]:
        (self.root / "ftree.toml").write_text(
            f'[tree]\nname = "t"\n[storage.media]\nkind = "local"\naddress = "{self.open}"\n'
            f'[storage.private]\nkind = "rclone"\naddress = "{private}:"\nencrypted = true\n', encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = media.main(["--root", str(self.root), "push"])
        return code, out.getvalue()

    def test_local_photos_and_encrypted_private(self):
        code, out = self.push("sealed")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.open / paths.rel(paths.PHOTOS_FAMILY) / "Проба_1950.jpg").read_bytes(), b"photo")
        stored = [p for p in self.cloud.rglob("*") if p.is_file()]
        self.assertEqual(len(stored), 1)
        self.assertNotIn(b"pdf-1", stored[0].read_bytes(), "PDF в закрытом хранилище — зашифрован")

    def test_encrypted_mark_blocks_plain_remote(self):
        code, out = self.push("plain")
        self.assertEqual(code, 1)
        self.assertIn("encrypted = true", out)
        self.assertEqual([p for p in self.cloud.rglob("*") if p.is_file()], [], "PDF открытым не ушёл")
        self.assertTrue((self.open / paths.rel(paths.PHOTOS_FAMILY) / "Проба_1950.jpg").exists(), "фото ушли")


if __name__ == "__main__":
    unittest.main()
