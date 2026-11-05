"""Тесты media.py на временной папке и временном облаке (rclone crypt поверх локальной папки).

Запуск: python3 -m unittest discover tools/scripts/tests. Без rclone тесты пропускаются; без ffmpeg — только звук.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media  # noqa: E402
import paths  # noqa: E402
ARCHIVES_ONLINE = paths.rel(paths.ARCHIVES_ONLINE)
AUDIO = paths.rel(paths.AUDIO)
FAMILY_ARCHIVE = paths.rel(paths.FAMILY_ARCHIVE)
PEOPLE = paths.rel(paths.PEOPLE)
PHOTOS_FAMILY = paths.rel(paths.PHOTOS_FAMILY)
PHOTOS_HISTORY = paths.rel(paths.PHOTOS_HISTORY)
PHOTOS_PLACES = paths.rel(paths.PHOTOS_PLACES)
TRANSCRIPTS_AUDIO = paths.rel(paths.TRANSCRIPTS_AUDIO)

HAS_RCLONE = shutil.which("rclone") is not None
try:
    FFMPEG = media.ffmpeg()
except SystemExit:
    FFMPEG = None


def run(ctx, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = media.main(["--root", str(ctx.root), "--remote", ctx.remote, "--open-remote", ctx.open_remote, *argv])
    return code, out.getvalue()


@unittest.skipUnless(HAS_RCLONE, "нет rclone")
class MediaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="media_test_"))
        self.root = self.tmp / "proj"
        self.cloud = self.tmp / "cloud"
        self.cloud.mkdir()
        self.open = self.tmp / "open"  # открытое облако (фото): обычная папка
        pw = subprocess.run(["rclone", "obscure", "test-password"], capture_output=True, text=True).stdout.strip()
        conf = self.tmp / "rclone.conf"
        conf.write_text(f"[t]\ntype = crypt\nremote = {self.cloud}\npassword = {pw}\n", encoding="utf-8")
        self.env = {"RCLONE_CONFIG": str(conf), "MEDIA_NO_KEYCHAIN": "1", "MEDIA_CACHE": str(self.tmp / "cache"),
                    "MEDIA_TRASH": str(self.tmp / "trash")}
        self.old_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.write(f"{PHOTOS_FAMILY}/Сергей_1950.jpg", b"photo-1")
        self.write(f"{PHOTOS_PLACES}/Брест.png", b"place-1")
        self.write(f"{PHOTOS_PLACES}/копия_Бреста.png", b"place-1")  # то же содержимое
        self.write(f"{FAMILY_ARCHIVE}/Doc1.pdf", b"pdf-1")
        self.write(f"{FAMILY_ARCHIVE}/Doc1_копия.pdf", b"pdf-1")  # то же содержимое
        self.write(f"{ARCHIVES_ONLINE}/gaso_smolensk/ф48/001.jpg", b"raw")  # сырьё — не в облако
        self.write(f"{TRANSCRIPTS_AUDIO}/_raw_audio01/audio.wav", b"wav")                 # копия для распознавания
        self.write("web/public/logo.png", b"code")                                        # картинка кода
        self.write(f"{PEOPLE}/Сергей.md",
                   '---\nmedia:\n  - "[[Сергей_1950.jpg]]"\n---\nФото: [[Сергей_1950.jpg|снимок]]\n')
        self.ctx = media.make_ctx(str(self.root), "t:", str(self.open))

    def tearDown(self):
        for k, v in self.old_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode() if isinstance(data, str) else data)

    def rows(self):
        return media.load(self.ctx)

    def test_scan_skips_raw_code_and_recognition_copies(self):
        self.write(f"{PHOTOS_PLACES}/Брест 2.png", b"icloud")  # мусорная копия iCloud
        self.write(f"{AUDIO}/Lipowa 2.mp3", b"real")         # а это настоящий файл
        self.assertEqual(media.scan(self.ctx), [
            f"{AUDIO}/Lipowa 2.mp3",
            f"{FAMILY_ARCHIVE}/Doc1.pdf",
            f"{FAMILY_ARCHIVE}/Doc1_копия.pdf",
            f"{PHOTOS_FAMILY}/Сергей_1950.jpg",
            f"{PHOTOS_PLACES}/Брест.png",
            f"{PHOTOS_PLACES}/копия_Бреста.png",
        ])

    def test_push_photos_open_under_own_path_pdf_encrypted_and_deduplicated(self):
        code, out = run(self.ctx, "push")
        self.assertEqual(code, 0, out)
        rows = self.rows()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r.get("pushed") for r in rows.values()))
        self.assertEqual(rows[f"{PHOTOS_FAMILY}/Сергей_1950.jpg"]["kind"], "family")
        # фото — в открытом облаке, под своим путём: родня видит папки и имена как в проекте
        self.assertEqual((self.open / f"{PHOTOS_FAMILY}/Сергей_1950.jpg").read_bytes(), b"photo-1")
        self.assertEqual(len([p for p in self.open.rglob("*") if p.is_file()]), 3)
        # PDF — в шифрованном, одна копия на одинаковое содержимое; имена и содержимое не прочесть
        stored = [p for p in self.cloud.rglob("*") if p.is_file()]
        self.assertEqual(len(stored), 1, "одинаковое содержимое — один файл в облаке")
        for p in stored:
            self.assertNotIn("media", p.relative_to(self.cloud).as_posix())
            self.assertNotIn(b"pdf-1", p.read_bytes())
        self.assertEqual(run(self.ctx, "verify", "--deep")[0], 0)

    def test_names_match_whatever_unicode_form_the_cloud_uses(self):
        import unicodedata
        self.write(unicodedata.normalize("NFD", f"{PHOTOS_PLACES}/Чайка.jpg"), b"nfd")
        run(self.ctx, "push")  # на диске имя в NFD (как в macOS), в облаке rclone пишет NFC
        self.assertEqual(run(self.ctx, "verify")[0], 0)
        dest = self.tmp / "restore"
        self.assertEqual(run(self.ctx, "pull", "--all", "--dest", str(dest))[0], 0)

    def test_errors_never_show_passwords(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = run(media.make_ctx(str(self.root), ":crypt,remote=/nonexistent,password=SECRETX:", str(self.open)),
                            "verify")
        self.assertNotIn("SECRETX", err.getvalue() + out)

    def test_verify_catches_missing_and_changed(self):
        run(self.ctx, "push")
        self.write(f"{PHOTOS_PLACES}/Брест.png", b"place-2")
        code, out = run(self.ctx, "verify")
        self.assertEqual(code, 1)
        self.assertIn("изменился", out)
        for p in [*self.cloud.rglob("*"), *self.open.rglob("*")]:
            if p.is_file():
                p.unlink()
        code, out = run(self.ctx, "verify")
        self.assertEqual(code, 1)
        self.assertIn("нет в облаке", out)

    def test_push_is_idempotent_and_picks_up_new_files(self):
        run(self.ctx, "push")
        self.write(f"{PHOTOS_HISTORY}/1944.jpg", b"history-photo")
        code, out = run(self.ctx, "status")
        self.assertEqual(code, 1)
        self.assertIn("не в описи (новые): 1", out)
        run(self.ctx, "push")
        code, out = run(self.ctx, "status")
        self.assertEqual(code, 0, out)

    def test_pull_restores_with_checksum(self):
        run(self.ctx, "push")
        dest = self.tmp / "restore"
        code, out = run(self.ctx, "pull", "--all", "--dest", str(dest))
        self.assertEqual(code, 0, out)
        self.assertEqual((dest / f"{PHOTOS_FAMILY}/Сергей_1950.jpg").read_bytes(), b"photo-1")

    def test_pull_brings_back_missing_file_in_place(self):
        run(self.ctx, "push")
        (self.root / f"{PHOTOS_PLACES}/Брест.png").unlink()
        self.assertIn("нет локально", run(self.ctx, "status")[1])
        run(self.ctx, "pull", f"{PHOTOS_PLACES}/Брест.png")
        self.assertEqual((self.root / f"{PHOTOS_PLACES}/Брест.png").read_bytes(), b"place-1")

    def test_mv_moves_file_manifest_and_links(self):
        run(self.ctx, "push")
        new = f"{PHOTOS_FAMILY}/Сергей_Образцов_1950.jpg"
        code, _ = run(self.ctx, "mv", f"{PHOTOS_FAMILY}/Сергей_1950.jpg", new)
        self.assertEqual(code, 0)
        self.assertTrue((self.root / new).exists())
        self.assertIn(new, self.rows())
        card = (self.root / f"{PEOPLE}/Сергей.md").read_text(encoding="utf-8")
        self.assertIn('"[[Сергей_Образцов_1950.jpg]]"', card)
        self.assertIn("[[Сергей_Образцов_1950.jpg|снимок]]", card)
        self.assertTrue((self.open / new).exists(), "в открытом облаке — тоже новое имя")
        self.assertFalse((self.open / f"{PHOTOS_FAMILY}/Сергей_1950.jpg").exists())
        self.assertEqual(run(self.ctx, "verify")[0], 0, "опись и облако сходятся после переименования")

    def test_rm_family_needs_force(self):
        run(self.ctx, "push")
        with self.assertRaises(SystemExit):
            run(self.ctx, "rm", f"{PHOTOS_FAMILY}/Сергей_1950.jpg")
        code, _ = run(self.ctx, "rm", f"{PHOTOS_FAMILY}/Сергей_1950.jpg", "--force")
        self.assertEqual(code, 0)
        self.assertNotIn(f"{PHOTOS_FAMILY}/Сергей_1950.jpg", self.rows())
        card = (self.root / f"{PEOPLE}/Сергей.md").read_text(encoding="utf-8")
        self.assertNotIn('- "[[Сергей_1950.jpg]]"', card)
        self.assertTrue(any((self.tmp / "trash").iterdir()), "файл — в Корзину, не стёрт")
        self.assertFalse((self.open / f"{PHOTOS_FAMILY}/Сергей_1950.jpg").exists(), "родня его больше не видит")

    def test_check_staged_blocks_media_in_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "web/public/logo.png"], check=True)
        self.assertEqual(run(self.ctx, "check-staged")[0], 0,
                         "файлы на диске не в описи — не стоп: pre-commit вносит их сам (add); картинка кода в git — можно")
        subprocess.run(["git", "-C", str(self.root), "add", f"{PHOTOS_PLACES}/Брест.png"], check=True)
        code, out = run(self.ctx, "check-staged")
        self.assertEqual(code, 1)
        self.assertIn("медиа в коммите", out)

    def test_add_lists_without_upload(self):
        code, out = run(self.ctx, "add")
        self.assertEqual(code, 0)
        self.assertIn("в опись: 1_sources/found/photos_places/Брест.png", out)
        rows = self.rows()
        self.assertIn(f"{PHOTOS_PLACES}/Брест.png", rows)
        self.assertFalse(any(r.get("pushed") for r in rows.values()), "add в облако не отправляет")
        self.assertEqual([f for d in (self.cloud, self.open) if d.exists() for f in d.rglob("*.*")], [], "облако пустое")
        self.assertEqual(run(self.ctx, "add")[1], "", "второй раз — нечего вносить")

    def test_stub_never_replaces_real_row(self):   # пустышки (media.py stub) в копии без медиа: опись не портится
        run(self.ctx, "add")
        before = dict(self.rows()[f"{PHOTOS_PLACES}/Брест.png"])
        self.write(f"{PHOTOS_PLACES}/Брест.png", b"")
        self.assertEqual(run(self.ctx, "add")[1], "", "пустышка — не новое и не изменённое")
        self.assertEqual(self.rows()[f"{PHOTOS_PLACES}/Брест.png"], before)

    def test_history_media_not_on_disk(self):
        g = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(f"{PHOTOS_FAMILY}/старое.jpg", b"old-photo")
        self.write("tools/x.png", b"code-in-history")
        subprocess.run([*g, "add", "-A"], check=True)
        subprocess.run([*g, "commit", "-qm", "1"], check=True)
        (self.root / f"{PHOTOS_FAMILY}/старое.jpg").unlink()
        code, out = run(self.ctx, "push", "--history")
        self.assertEqual(code, 0, out)
        hist = [r for r in self.rows().values() if r["kind"] == "history"]
        self.assertEqual([r["path"] for r in hist], [f"{PHOTOS_FAMILY}/старое.jpg"])
        self.assertEqual(run(self.ctx, "verify", "--deep")[0], 0)
        dest = self.tmp / "restore"
        run(self.ctx, "pull", "--all", "--history", "--dest", str(dest))
        self.assertEqual((dest / f"{PHOTOS_FAMILY}/старое.jpg").read_bytes(), b"old-photo")

    @unittest.skipUnless(FFMPEG, "нет ffmpeg")
    def test_audio_goes_as_opus_copy(self):
        wav = self.root / f"{AUDIO}/Разговор.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([FFMPEG, "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        str(wav)], check=True)
        code, out = run(self.ctx, "push")
        self.assertEqual(code, 0, out)
        row = self.rows()[f"{AUDIO}/Разговор.wav"]
        self.assertEqual(row["kind"], "audio")
        self.assertTrue(row["remote"].endswith(".opus"))
        self.assertLess(row["copy"]["size"], row["size"])
        self.assertEqual(run(self.ctx, "verify", "--deep")[0], 0)
        dest = self.tmp / "restore"
        run(self.ctx, "pull", "--all", "--dest", str(dest))
        self.assertTrue((dest / f"{AUDIO}/Разговор.opus").exists())


if __name__ == "__main__":
    unittest.main()
