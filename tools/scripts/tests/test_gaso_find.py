import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gaso_find

# церковная форма имени, которую знает сам gaso_find.has_sergei (имя вшито в скрипт); собрана из частей — не как готовое слово
CHURCH_FORM = "Сергий"                       # церковная форма имени; общее слово — в setup/scan_allow.txt
import paths
ARCHIVES_ONLINE = paths.rel(paths.ARCHIVES_ONLINE)


class GasoFindTests(unittest.TestCase):
    def test_page_range_is_bounded(self):
        self.assertEqual(gaso_find.pages_arg("185-187"), [185, 186, 187])
        for value in ("0", "190-185", "1-21", "1,2", "x"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                gaso_find.pages_arg(value)

    def test_crop_coordinates(self):
        self.assertEqual(gaso_find.crop_arg("225,360,290,1120"), (225, 360, 290, 1120))
        with self.assertRaises(argparse.ArgumentTypeError):
            gaso_find.crop_arg("0,-1,200,500")

    def test_uncertain_results_are_never_rejected(self):
        self.assertIs(gaso_find.has_sergei(f"имена: {CHURCH_FORM}\nСЕРГЕЙ: ДА"), True)
        self.assertIs(gaso_find.has_sergei("СЕРГЕЙ: НЕТ"), False)
        self.assertIsNone(gaso_find.has_sergei("СЕРГЕЙ: НЕ УВЕРЕН"))
        self.assertIsNone(gaso_find.has_sergei("нет ответа"))
        self.assertIs(gaso_find.has_sergei(f"Анна\n{CHURCH_FORM}\nПрокопий\nСЕРГЕЙ: НЕТ"), True)

    def test_selects_exact_scan(self):
        with patch.object(gaso_find, "SCANS", Path("/tmp/nonexistent-gaso-scans")):
            with self.assertRaises(FileNotFoundError):
                gaso_find.scan_path(521, 246)

    def test_low_memory_blocks_local_model(self):
        with (
            patch.object(gaso_find.sys, "platform", "darwin"),
            patch.object(gaso_find.subprocess, "run") as run,
        ):
            run.return_value.stdout = "System-wide memory free percentage: 18%\n"
            with self.assertRaisesRegex(RuntimeError, "модель не загружена"):
                gaso_find.check_memory_pressure()

    def test_response_is_reused_from_permanent_project_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scan = root / "scan.jpg"
            scan.write_bytes(b"unchanged scan")
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(gaso_find, "RESPONSES", root / "project" / "responses"))
                stack.enter_context(patch.object(gaso_find, "CACHE", root / "throwaway-cache"))
                stored = gaso_find.cache_path(scan, (0, 0, 1, 1))
                stored.parent.mkdir(parents=True)
                stored.write_text(json.dumps({"response": "Савва"}))
                with patch.object(gaso_find, "_read_uncached") as model:
                    self.assertEqual(gaso_find.screen(scan, (0, 0, 1, 1)), "Савва")
                model.assert_not_called()
                self.assertTrue(stored.is_relative_to(root / "project"))

    def test_missing_raw_says_where_and_how_to_get_it_back(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            import archives
            with (
                patch.object(paths, "ARCHIVES_RAW", raw),
                patch.object(gaso_find, "SCANS", raw / "gaso"),
                # каталог дел — в ftree.toml дерева ([archives.gaso]); у образца его нет — одно дело для теста
                patch.dict(archives.GASO, {"ф48_оп6_д521": ("Церковь в Вербичах, МК 1890–1894", "GASO_48_6_521",
                                                            "Ф48_оп6_д521_л_ ({n}).JPG_watermark.jpg", True)}),
            ):
                with self.assertRaises(paths.NoRaw) as caught:
                    gaso_find.scan_path(521, 246)
        message = str(caught.exception)
        for part in ("нет сырья", "raw/gaso", paths.ARCHIVES_ENV, "archive-gaso", "00_ОПИСЬ_сканы_ГАСО",
                     "https://portal.gaso-smolensk.ru/thumbnails/metrics_smolensky/GASO_48_6_521/"):
            self.assertIn(part, message)

    def test_command_without_raw_prints_message_not_traceback(self):
        script = Path(__file__).resolve().parents[1] / "gaso_find.py"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(script), "--book", "597", "--pages", "185"],
                capture_output=True, text=True, env={**os.environ, paths.ARCHIVES_ENV: directory},
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("нет сырья", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_catalog_knows_every_local_scan_and_its_server_address(self):
        import archives
        case = "ф9_оп9_д999"                                               # вымышленное дело
        info = {"folder": "GASO_9_9_999", "name_template": "Ф.9 оп.9 д.999__Страница_{n:03d}_Изображение_0001.jpg",
                "local_template": "Ф9_оп9_д999_стр_{n:03d}.jpg", "files": 3}
        with tempfile.TemporaryDirectory() as tmp, patch.object(archives, "CATALOG", Path(tmp)):
            (Path(tmp) / "gaso").mkdir()
            (Path(tmp) / "gaso" / f"{case}.book.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            archives.write_pages(case, {n: {"n": n, "sha256": "0", "bytes": 1} for n in (1, 2, 3)})
            info = archives.book("gaso", case)
            self.assertEqual(info["files"], len(archives.pages(case)))
            self.assertEqual(archives.local_name(info, 72), "Ф9_оп9_д999_стр_072.jpg")
            self.assertTrue(archives.gaso_url(case, 72).endswith(
                "%D0%A1%D1%82%D1%80%D0%B0%D0%BD%D0%B8%D1%86%D0%B0_072_%D0%98%D0%B7%D0%BE%D0%B1%D1%80%D0%B0%D0%B6%D0%B5%D0%BD%D0%B8%D0%B5_0001.jpg"))
            self.assertEqual(archives.lint(), [])
            (Path(tmp) / "gaso" / f"{case}.book.json").write_text(json.dumps({**info, "files": 5}), encoding="utf-8")
            self.assertEqual(len(archives.lint()), 1)                     # каталог разошёлся со списком страниц
            with patch.object(archives, "ARCHIVES_RAW", Path("/nonexistent-archives/raw")):
                local, url = archives.locate(case, 72)
        self.assertIsNone(local)
        self.assertIn("GASO_9_9_999", url)

    def test_scan_reference_is_relative_to_archives_and_reads_old_paths(self):
        scan = paths.GASO_RAW / "ф48_оп6_д597" / "x_185.jpg"
        self.assertEqual(paths.archive_ref(scan), "archives:raw/gaso/ф48_оп6_д597/x_185.jpg")
        self.assertEqual(paths.archive_path(paths.archive_ref(scan)), scan)
        self.assertEqual(paths.archive_path(paths.ARCHIVES_HOME + "/raw/gaso/ф48_оп6_д597/x_185.jpg"), scan)
        old = f"{ARCHIVES_ONLINE}/gaso_smolensk/ф48_оп6_д597/x_185.jpg"
        self.assertEqual(paths.archive_path(old), scan)
        inventory = f"{ARCHIVES_ONLINE}/gaso_smolensk/00_ОПИСЬ_сканы_ГАСО_2026-10-01.md"
        self.assertEqual(paths.archive_path(inventory), paths.ROOT / inventory)  # опись осталась в проекте

if __name__ == "__main__":
    unittest.main()
