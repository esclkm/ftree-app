import argparse
import contextlib
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gaso_flow as flow


class GasoFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for obj, name, value in (
            (flow, "ROOT", self.root),
            (flow, "JOBS", self.root / "jobs"),
            (flow, "LEDGER", self.root / "jobs" / "calls.jsonl"),
            (flow, "TREE", self.root / "tree"),
            (flow.finder, "CACHE", self.root / "cache"),
            (flow.finder, "RESPONSES", self.root / "responses"),
        ):
            self.stack.enter_context(patch.object(obj, name, value))

        def scan(book, number):
            image = self.root / f"scan-{book}-{number}.jpg"
            image.write_bytes(f"{book}-{number}".encode())
            return image

        self.stack.enter_context(patch.object(flow.finder, "scan_path", side_effect=scan))
        flow.create(argparse.Namespace(
            job="sergei-test", book=597, pages=[185, 186], crop=None,
            objective="Сергей, отец Александр, Вербичи",
            range_evidence="Отдел рождений, год проверить на оригинале",
        ))
        self.job = flow.load("sergei-test")

    def fake_call(self, job_id, scan, crop):
        response = "СЕРГЕЙ: ДА" if scan.name.endswith(("246.jpg", "247.jpg", "185.jpg")) else "СЕРГЕЙ: НЕТ"
        cache = flow.finder.cache_path(scan, crop)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "sha256": hashlib.sha256(scan.read_bytes()).hexdigest(), "response": response,
        }))
        return response

    def test_controls_must_pass_before_pages(self):
        with (
            patch.object(flow, "model_call", return_value="СЕРГЕЙ: НЕТ") as call,
            patch.object(flow, "used_today", return_value=0),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Контроль провален"):
                flow.run(self.job, 2)
        call.assert_called_once()
        self.assertEqual(flow.load("sergei-test")["pages"]["185"]["state"], "queued")

    def test_blocked_job_does_not_call_model(self):
        self.job["blocked_reason"] = "кроп не проверен"
        with patch.object(flow, "model_call") as call:
            with self.assertRaisesRegex(RuntimeError, "кроп не проверен"):
                flow.run(self.job, 1)
        call.assert_not_called()

    def test_previous_local_calls_do_not_block_new_batch(self):
        with (
            patch.object(flow, "used_today", return_value=10000),
            patch.object(flow, "model_call", side_effect=self.fake_call) as call,
            patch("builtins.print"),
        ):
            flow.run(self.job, 2)
        self.assertEqual(call.call_count, 4)
        self.assertEqual(flow.load("sergei-test")["pages"]["185"]["state"], "candidate")

    def test_resume_review_and_curator_gate(self):
        with (
            patch.object(flow, "model_call", side_effect=self.fake_call) as call,
            patch.object(flow, "used_today", return_value=0),
            patch("builtins.print"),
        ):
            flow.run(self.job, 1)
            self.assertEqual(flow.load("sergei-test")["pages"]["185"]["state"], "candidate")
            cache = flow.finder.RESPONSES / f"{flow.load('sergei-test')['pages']['185']['cache_key']}.json"
            cache.unlink()
            with patch("builtins.print") as display:
                flow.inspect(flow.load("sergei-test"), 185)
            self.assertIn("СЕРГЕЙ: ДА", str(display.call_args_list))
            flow.run(flow.load("sergei-test"), 2)
            self.assertEqual(flow.load("sergei-test")["pages"]["186"]["state"], "screened_unverified")
            flow.run(flow.load("sergei-test"), 2)
        self.assertEqual(call.call_count, 6)  # 2 controls + 1 page in each of two runs
        job = flow.load("sergei-test")
        with self.assertRaisesRegex(ValueError, "подтверждённую"):
            flow.curated(job, argparse.Namespace(page=185, person="Сергей Ясенев"))
        with self.assertRaisesRegex(ValueError, "шифр источника"):
            flow.review(job, argparse.Namespace(page=185, decision="confirmed",
                                                source=None, evidence="отец Александр"))
        flow.review(job, argparse.Namespace(page=185, decision="confirmed",
                                            source="ГАСО ф48 оп6 д597 л.?", evidence="отец Александр"))
        flow.review(job, argparse.Namespace(page=186, decision="not-match",
                                            source=None, evidence="на оригинале другой отец"))
        card = self.root / "tree" / "people" / "Сергей Ясенев.md"
        card.parent.mkdir(parents=True)
        card.write_text("ГАСО ф48 оп6 д597 л.?")
        flow.curated(job, argparse.Namespace(page=185, person="Сергей Ясенев"))
        self.assertEqual(flow.load("sergei-test")["pages"]["185"]["state"], "curated")

    def test_ledger_counts_attempt_before_model_call(self):
        scan = flow.finder.scan_path(597, 185)
        with (
            patch.object(flow.finder, "screen", side_effect=RuntimeError("model error")),
            patch.object(flow.finder, "check_memory_pressure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "model error"):
                flow.model_call("sergei-test", scan, flow.finder.CROPS[597])
        self.assertEqual(flow.used_today(), 1)
        rows = [json.loads(line) for line in flow.LEDGER.read_text().splitlines()]
        self.assertEqual(rows[0]["usd"], 0)
        self.assertEqual(rows[1]["kind"], "model_error")

    def test_model_error_is_saved_without_hiding_failure(self):
        scan = flow.finder.scan_path(597, 185)
        with (
            patch.object(flow.finder, "screen", side_effect=RuntimeError("model error")),
            patch.object(flow.finder, "check_memory_pressure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "model error"):
                flow.model_call("sergei-test", scan, flow.finder.CROPS[597])
        rows = [json.loads(line) for line in flow.LEDGER.read_text().splitlines()]
        self.assertEqual([row["kind"] for row in rows], ["model_attempt", "model_error"])
        self.assertEqual(rows[1]["error"], "model error")

    def test_changed_original_blocks_review(self):
        with (
            patch.object(flow, "model_call", side_effect=self.fake_call),
            patch.object(flow, "used_today", return_value=0),
            patch("builtins.print"),
        ):
            flow.run(self.job, 1)
        (self.root / "scan-597-185.jpg").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "Скан изменился"):
            flow.review(flow.load("sergei-test"), argparse.Namespace(
                page=185, decision="not-match", source=None, evidence="другой отец",
            ))

    def test_range_is_limited(self):
        self.assertEqual(flow.page_range("185-186"), [185, 186])
        with self.assertRaises(argparse.ArgumentTypeError):
            flow.page_range("1-51")


if __name__ == "__main__":
    unittest.main()
