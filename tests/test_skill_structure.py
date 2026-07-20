from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "migrate-macos-app-data"


class SkillStructureTests(unittest.TestCase):
    def test_required_files_and_metadata(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill_text, r"(?m)^name: migrate-macos-app-data$")
        self.assertRegex(skill_text, r"(?m)^description: .{80,}$")
        self.assertNotIn("TO" + "DO", skill_text)
        self.assertTrue((SKILL_ROOT / "agents" / "openai.yaml").is_file())

    def test_no_machine_specific_paths_or_identifiers(self) -> None:
        forbidden_patterns = (
            re.compile(r"/Users/[A-Za-z0-9._-]+"),
            re.compile(r"\b[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\b"),
            re.compile(r"/Volumes/(?:Personal|Private|My)[^/\s]*/Applications"),
        )
        text_extensions = {".md", ".py", ".sh", ".swift", ".yaml", ".yml"}
        for path in SKILL_ROOT.rglob("*"):
            if path.is_file() and path.suffix in text_extensions:
                content = path.read_text(encoding="utf-8")
                for pattern in forbidden_patterns:
                    self.assertIsNone(pattern.search(content), msg=f"{pattern.pattern!r} matched in {path}")

    def test_default_prompt_names_the_skill(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$migrate-macos-app-data", metadata)
        self.assertIsNotNone(re.search(r'(?m)^  short_description: ".{25,64}"$', metadata))


if __name__ == "__main__":
    unittest.main()
