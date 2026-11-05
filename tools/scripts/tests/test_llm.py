import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm

FAKE = """#!{python}
import json, os, sys
args = sys.argv[1:]
text = sys.stdin.read()
open(os.environ["FAKE_ARGS"], "w").write(json.dumps({{"args": args, "cwd": os.getcwd()}}))
if "ЛИМИТ" in text:
    print(json.dumps({{"is_error": True, "result": "Claude AI usage limit reached"}})); sys.exit(1)
print(json.dumps({{"is_error": False, "result": "ответ: " + text.strip(),
                  "usage": {{"input_tokens": 3, "output_tokens": 5, "cache_creation_input_tokens": 600}}}}))
"""


class LlmTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fake = self.root / "claude"
        fake.write_text(FAKE.format(python=sys.executable))
        fake.chmod(0o755)
        self.args = self.root / "args.json"
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        cache = self.root / "cache"
        for name, value in (("CACHE", cache), ("WORK", cache / "cwd"), ("ANSWERS", cache / "answers"),
                            ("LOG", cache / "llm_calls.jsonl")):
            stack.enter_context(patch.object(llm, name, value))
        stack.enter_context(patch.dict(os.environ, {"LLM_CLI": str(fake), "FAKE_ARGS": str(self.args),
                                                    "LLM_DAILY_CAP": "1"}))

    def test_light_call_from_empty_folder_is_logged_and_cached(self):
        self.assertEqual(llm.ask("перевод", "привет", "system"), "ответ: привет")
        call = json.loads(self.args.read_text())
        for flag in ("--setting-sources", "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, call["args"])
        self.assertEqual(call["args"][call["args"].index("--tools") + 1], "")
        self.assertEqual(Path(call["cwd"]).resolve(), (self.root / "cache" / "cwd").resolve())
        self.assertEqual(llm.ask("перевод", "привет", "system"), "ответ: привет")  # из кэша, потолок не тронут
        rows = [json.loads(line) for line in llm.LOG.read_text().splitlines()]
        self.assertEqual([r["cached"] for r in rows], [False, True])
        self.assertEqual(rows[0]["output_tokens"], 5)

    def test_daily_cap_stops_before_calling(self):
        llm.ask("перевод", "раз", "system")
        self.args.unlink()
        with self.assertRaisesRegex(llm.Limit, "потолок"):
            llm.ask("перевод", "два", "system")
        self.assertFalse(self.args.exists())

    def test_subscription_limit_is_not_retried(self):
        with self.assertRaisesRegex(llm.Limit, "лимит подписки"):
            llm.ask("перевод", "ЛИМИТ", "system")
        self.assertFalse(any(llm.ANSWERS.glob("*.json")) if llm.ANSWERS.exists() else False)

    def test_image_goes_through_read_tool_only(self):
        image = self.root / "scan.jpg"
        image.write_bytes(b"jpg")
        llm.ask("распознавание", "что на картинке", "system", image=image)
        args = json.loads(self.args.read_text())["args"]
        self.assertEqual(args[args.index("--tools") + 1], "Read")

    def test_copilot_model_goes_to_copilot_with_attachment_and_own_cap(self):
        fake = self.root / "copilot"
        fake.write_text(COPILOT_FAKE.format(python=sys.executable))
        fake.chmod(0o755)
        image = self.root / "scan.jpg"
        image.write_bytes(b"jpg")
        with patch.dict(os.environ, {"LLM_COPILOT_CLI": str(fake), "LLM_COPILOT_CAP": "1"}):
            llm.ask("перевод", "раз", "system")                     # Claude: его потолок занят
            self.assertEqual(llm.ask("ocr", "что там", "system", model="copilot:gemini-3.8-flash", image=image),
                             "Варшава")
            call = json.loads(self.args.read_text())
            self.assertEqual(call["args"][call["args"].index("--model") + 1], "gemini-3.8-flash")
            self.assertIn("--available-tools=", call["args"])
            self.assertIn("--attachment", call["args"])
            self.assertIn("system", call["stdin"])
            with self.assertRaisesRegex(llm.Limit, "потолок Copilot"):
                llm.ask("ocr", "другое", "system", model="copilot:gemini-3.8-flash")
        row = [json.loads(line) for line in llm.LOG.read_text().splitlines()][-1]
        self.assertEqual(row["premium"], 14)


COPILOT_FAKE = """#!{python}
import json, os, sys
args = sys.argv[1:]
text = sys.stdin.read()
open(os.environ["FAKE_ARGS"], "w").write(json.dumps({{"args": args, "stdin": text}}))
json.dump({{"totalPremiumRequestCost": 14, "tokenDetails": {{"input": {{"tokenCount": 3000}}}}}},
          open(args[args.index("--usage-output-file") + 1], "w"))
print(json.dumps({{"type": "assistant.message", "data": {{"content": "Варшава"}}}}))
print(json.dumps({{"type": "result", "exitCode": 0}}))
"""


class TranslateLinksTests(unittest.TestCase):
    def test_link_targets_never_reach_the_model(self):
        import bio_autotranslate as t
        seen = {}

        def fake(task, text, system, model):
            seen["text"] = text
            return text.replace("Жил", "Vivió").replace("⟦L1⟧", "⟦L1⟧")

        with patch.object(t.llm, "ask", side_effect=fake):
            out = t.translate("S", "Жил в [[Лесогорск (Подгорье)|Лесогорске]].")
        self.assertNotIn("Лесогорск (Подгорье)", seen["text"])
        self.assertEqual(out, "Vivió в [[Лесогорск (Подгорье)|Лесогорске]].")


if __name__ == "__main__":
    unittest.main()
