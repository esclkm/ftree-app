import argparse
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gaso_index as index


class GasoIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for obj, name, value in (
            (index.archives, "CATALOG", self.root / "catalog"),
            (index.archives, "ARCHIVES_RAW", self.root / "raw"),
            (index.finder, "SCANS", self.root / "raw" / "gaso"),
            (index, "TEXT", self.root / "text" / "gaso"),
        ):
            self.stack.enter_context(patch.object(obj, name, value))
        self.stack.enter_context(patch("builtins.print"))
        # каталог дел живёт в ftree.toml дерева ([archives.gaso]); у образца его нет — одно дело для теста
        self.stack.enter_context(patch.dict(index.archives.GASO, {"ф48_оп6_д581": (
            "Церковь в Вербичах, МК 1893–1897", "GASO_48_6_581",
            "Ф.48 оп.6 д.581__Страница_{n:03d}_Изображение_0001.jpg_watermark.jpg", True)}))
        self.directory = index.scan_dir(581)
        self.directory.mkdir(parents=True)
        for n in (2, 3, 5):
            (self.directory / f"Ф48_оп6_д581_стр_{n:03}.jpg").write_bytes(str(n).encode())

    def test_catalog_preserves_absent_numbers_without_inventing_pages(self):
        data = index.catalog(581)
        self.assertEqual(list(data["files"]), ["2", "3", "5"])
        self.assertEqual(len(data["files"]), 3)
        self.assertEqual(data["anchors"], {})
        self.assertEqual(index.sample(data, 2), [2, 5])
        self.assertEqual(index.selected("2,2,5"), [2, 5])

    def test_probe_is_only_proposal_and_requires_manual_verification(self):
        index.catalog(581)
        with (
            patch.object(index, "full_crop", return_value=(0, 0, 2000, 1500)),
            patch.object(index.flow, "used_today", return_value=0),
            patch.object(index.flow, "model_call", return_value="ГОД: 1894; РАЗДЕЛ: рождения") as call,
            patch("builtins.print"),
        ):
            index.probe(581, 6, [3], False)
            call.assert_not_called()
            index.probe(581, 6, [3], True)
        record = index.load(581)["anchors"]["3"]
        self.assertEqual(record["state"], "proposed")
        self.assertIn("1894", record["response"])
        args = argparse.Namespace(
            book=581, opis=6, page=3, year=1894, section="births", month=7,
            folio=None, acts=None, evidence="original", checked_original=False,
        )
        with self.assertRaisesRegex(ValueError, "checked-original"):
            index.verify(args)
        args.checked_original = True
        index.verify(args)
        self.assertEqual(index.load(581)["anchors"]["3"]["state"], "verified")

    def test_catalog_keeps_labels_and_text_keeps_model_words(self):
        index.catalog(581)
        with (
            patch.object(index, "full_crop", return_value=(0, 0, 2000, 1500)),
            patch.object(index.flow, "used_today", return_value=0),
            patch.object(index.flow, "model_call",
                         return_value="ГОД: 1894; РАЗДЕЛ: родившихся; МЕСЯЦ: Июль; АКТЫ: 30-34; ЛИСТ: 71 об. Иван Пупкин"),
        ):
            index.probe(581, 6, [3], True)
        line = (self.root / "catalog" / "gaso" / "ф48_оп6_д581.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("Иван", line)
        row = index.archives.pages("ф48_оп6_д581")[3]
        self.assertEqual(row["check"]["state"], "proposed")
        self.assertEqual(row["check"]["proposed"], {"year": 1894, "section": "births", "month": 7, "acts": "30-34"})
        probes = json.loads(index.probes_path(581).read_text(encoding="utf-8"))
        self.assertIn("Иван", probes["3"]["response"])
        self.assertEqual(index.load(581)["anchors"]["3"]["response"], probes["3"]["response"])

    def test_changed_scan_refuses_to_rewrite_index(self):
        index.catalog(581)
        data = index.load(581)
        data["anchors"]["3"] = {
            "sha256": index.fingerprint(self.directory / data["files"]["3"]),
            "state": "proposed",
        }
        index.store(581, 6, data)
        (self.directory / data["files"]["3"]).write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "изменён"):
            index.catalog(581)


if __name__ == "__main__":
    unittest.main()
