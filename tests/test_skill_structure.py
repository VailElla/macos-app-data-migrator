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
        self.assertIn("## 中文流程", skill_text)
        self.assertIn("## English workflow", skill_text)
        self.assertTrue((SKILL_ROOT / "agents" / "openai.yaml").is_file())

        references = (
            "compatibility.zh-CN.md",
            "compatibility.en.md",
            "finder-handoff.zh-CN.md",
            "finder-handoff.en.md",
            "recovery.zh-CN.md",
            "recovery.en.md",
            "wuthering-waves.zh-CN.md",
            "wuthering-waves.en.md",
        )
        for reference in references:
            self.assertTrue((SKILL_ROOT / "references" / reference).is_file(), msg=reference)
            self.assertIn(f"references/{reference}", skill_text)

    def test_no_machine_specific_paths_or_identifiers(self) -> None:
        forbidden_patterns = (
            re.compile(r"/Users/[A-Za-z0-9._-]+"),
            re.compile(r"\b[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\b"),
            re.compile(r"/Volumes/(?:Apple|Personal|Private|My)[^/\s]*/Applications"),
            re.compile(r"com\.ella\b", re.IGNORECASE),
        )
        text_extensions = {".md", ".py", ".sh", ".swift", ".yaml", ".yml"}
        for root in (REPO_ROOT,):
            for path in root.rglob("*"):
                if ".git" in path.parts or not path.is_file() or path.suffix not in text_extensions:
                    continue
                content = path.read_text(encoding="utf-8")
                for pattern in forbidden_patterns:
                    self.assertIsNone(pattern.search(content), msg=f"{pattern.pattern!r} matched in {path}")

    def test_default_prompt_names_the_skill(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$migrate-macos-app-data", metadata)
        self.assertIsNotNone(re.search(r'(?m)^  short_description: ".{25,64}"$', metadata))

    def test_low_space_and_finder_safety_contract_is_present(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        migrator = (SKILL_ROOT / "scripts" / "migrate_app_data.py").read_text(encoding="utf-8")
        builder = (SKILL_ROOT / "scripts" / "build_wuthering_waves_launcher.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("不请求或接收管理员密码", skill)
        self.assertIn("Never request an administrator password", skill)
        self.assertIn("亲自在访达中", skill)
        self.assertIn("the user moves the internal app to Trash in Finder", skill)
        self.assertIn("运行时派生缓存", skill)
        self.assertIn("runtime-derived app caches", skill)
        self.assertIn("shared-pasteboard/archives", skill)
        self.assertIn("只处理本轮新生成", skill)
        self.assertIn("自动通过访达移到系统废纸篓", skill)
        self.assertIn("Never touch baseline entries", skill)
        self.assertIn("empty Trash automatically", skill)
        self.assertIn("应用名（外接版）", skill)
        self.assertIn("App Name (External)", skill)
        self.assertIn('b"com.apple.metadata:kMDItemFinderComment"', migrator)
        self.assertNotIn('add_parser("move"', migrator)
        self.assertNotIn('add_parser("restore"', migrator)
        self.assertNotIn("$HOME", builder)
        self.assertNotIn("${TMPDIR", builder)
        self.assertNotIn("--replace", builder)
        self.assertNotIn("--test-allow", builder)
        self.assertNotIn("--test-allow", migrator)
        self.assertIn('build_root="$(/usr/bin/mktemp -d "$output_parent/', builder)
        self.assertIn("--show-sdk-path", builder)
        self.assertIn('-sdk "$macos_sdk_path"', builder)

    def test_public_repository_materials_exist(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (REPO_ROOT / "REVIEW_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("## 中文说明", readme)
        self.assertIn("## English documentation", readme)
        self.assertIn("审查通过", checklist)
        self.assertTrue((REPO_ROOT / "LICENSE").is_file())
        self.assertTrue((REPO_ROOT / ".github" / "workflows" / "validate.yml").is_file())


if __name__ == "__main__":
    unittest.main()
