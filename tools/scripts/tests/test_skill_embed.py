"""Строка подгрузки заметок дерева в навыках: ровно одна, своё имя навыка, без кавычек и ${…:-…} (так её узнаёт правило
разрешения), и нигде больше в тексте навыка восклицательного знака перед обратной кавычкой — Claude Code выполнит его."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец

SKILLS = Path(__file__).resolve().parents[3] / ".claude" / "skills"
LINE = "!`${{CLAUDE_PLUGIN_ROOT}}/tools/rodo skill-notes --embed {n} 2>/dev/null || rodo skill-notes --embed {n} 2>/dev/null || true`"


class SkillEmbed(unittest.TestCase):
    def test_every_skill_has_one_line_of_its_own(self):
        files = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertTrue(files)
        for f in files:
            text = f.read_text(encoding="utf-8")
            with self.subTest(skill=f.parent.name):
                self.assertEqual(len(re.findall(r"!`", text)), 1)
                self.assertIn("\n" + LINE.format(n=f.parent.name) + "\n", text)


if __name__ == "__main__":
    unittest.main()
