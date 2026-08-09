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
            "apfs-container-consolidation.zh-CN.md",
            "apfs-container-consolidation.en.md",
            "docker-desktop.zh-CN.md",
            "docker-desktop.en.md",
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
        recovery_en = (SKILL_ROOT / "references" / "recovery.en.md").read_text(encoding="utf-8")
        recovery_zh = (SKILL_ROOT / "references" / "recovery.zh-CN.md").read_text(encoding="utf-8")
        finder_en = (SKILL_ROOT / "references" / "finder-handoff.en.md").read_text(encoding="utf-8")
        finder_zh = (SKILL_ROOT / "references" / "finder-handoff.zh-CN.md").read_text(encoding="utf-8")
        wuthering_en = (SKILL_ROOT / "references" / "wuthering-waves.en.md").read_text(
            encoding="utf-8"
        )
        wuthering_zh = (SKILL_ROOT / "references" / "wuthering-waves.zh-CN.md").read_text(
            encoding="utf-8"
        )
        consolidation_en = (
            SKILL_ROOT / "references" / "apfs-container-consolidation.en.md"
        ).read_text(encoding="utf-8")
        consolidation_zh = (
            SKILL_ROOT / "references" / "apfs-container-consolidation.zh-CN.md"
        ).read_text(encoding="utf-8")
        docker_en = (SKILL_ROOT / "references" / "docker-desktop.en.md").read_text(
            encoding="utf-8"
        )
        docker_zh = (SKILL_ROOT / "references" / "docker-desktop.zh-CN.md").read_text(
            encoding="utf-8"
        )
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (REPO_ROOT / "REVIEW_CHECKLIST.md").read_text(encoding="utf-8")
        builder = (SKILL_ROOT / "scripts" / "build_wuthering_waves_launcher.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("不请求或接收管理员密码", skill)
        self.assertIn("Never request an administrator password", skill)
        self.assertIn("亲自在访达中", skill)
        self.assertIn("the user moves the internal app to Trash in Finder", skill)
        self.assertIn("直接指向内置 `.app` 的可点击本地文件链接", skill)
        self.assertIn("[在访达中选择内置 App.app](/Applications/App.app)", skill)
        self.assertIn("clickable local-file link", skill)
        self.assertIn("[Select the internal App.app in Finder](/Applications/App.app)", skill)
        self.assertIn("默认在用户明确授权后", skill)
        self.assertIn("由 Codex 通过访达界面", skill)
        self.assertIn("after explicit user authorization", skill)
        self.assertIn("use the Finder UI", skill)
        self.assertIn("移到系统废纸篓，但绝不清空废纸篓", skill)
        self.assertIn("move the exact internal source directory to system Trash without emptying Trash", skill)
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
        self.assertIn('kind == "app" and relative == "."', migrator)
        self.assertIn("根目录上脚本明确列出的 macOS 实例属性（包括 `com.apple.provenance`）属于实例元数据", skill)
        self.assertIn("应用包内部条目只允许目标端新增的受保护 `com.apple.provenance`", skill)
        self.assertIn("destination-only protected `com.apple.provenance`", skill)
        self.assertIn("source-present provenance and every other xattr must still match exactly", skill)
        self.assertIn("至少记录一个相关进程", skill)
        self.assertIn("at least one app, updater, or helper process", skill)
        self.assertIn("外接 APFS 容器整合流程", skill)
        self.assertIn("External APFS container consolidation workflow", skill)
        self.assertIn("容器 UUID", consolidation_zh)
        self.assertIn("container UUID", consolidation_en)
        self.assertIn("Device not configured", consolidation_zh)
        self.assertIn("Device not configured", consolidation_en)
        self.assertIn("`._`", consolidation_zh)
        self.assertIn("`._`", consolidation_en)
        self.assertIn("明确接受", consolidation_zh)
        self.assertIn("explicit user acceptance", consolidation_en)
        self.assertIn("resizeContainer", consolidation_zh)
        self.assertIn("resizeContainer", consolidation_en)
        self.assertIn("Docker Desktop 稀疏虚拟磁盘流程", skill)
        self.assertIn("Docker Desktop sparse VM-disk migration", skill)
        self.assertIn("Disk image location", docker_zh)
        self.assertIn("Disk image location", docker_en)
        self.assertIn("字节级完整性未证明", docker_zh)
        self.assertIn("byte integrity unproven", docker_en)
        self.assertIn("不要由本 Skill 重新创建", docker_zh)
        self.assertIn("must not recreate one", docker_en)
        self.assertIn('"sparse_files": 0', migrator)
        self.assertIn('"sparse_detection_unavailable_files": 0', migrator)
        self.assertIn("Sparse files require a dedicated app-native adapter", migrator)
        self.assertIn("refuses to treat an unknown result as non-sparse", migrator)
        self.assertIn("allocate their holes", migrator)
        self.assertNotIn("--skip-hash", migrator)
        self.assertIn("写入 `verified` 状态前", skill)
        self.assertIn("before committing `verified` state", skill)
        self.assertIn("应用内部条目只允许目标端新增的受保护 provenance", checklist)
        self.assertIn("descendants allow only destination-only protected provenance", checklist)
        self.assertIn("默认在用户明确授权后由 Codex 通过访达", readme)
        self.assertIn("after explicit authorization Codex normally moves", readme)
        self.assertNotIn("用户先在访达中把源目录改名", readme)
        self.assertNotIn("the user first renames the source", readme)
        self.assertIn("数据目录默认经访达移入废纸篓", checklist)
        self.assertIn("A data directory normally stays in Trash", checklist)
        self.assertIn("准确恢复路径", checklist)
        self.assertIn("exact recovery path", checklist)
        self.assertIn("--finder-handoff-verified", migrator)
        self.assertIn("--recovery-path", migrator)
        self.assertIn("choosing Put Back", recovery_en)
        self.assertIn("执行“放回原处”", recovery_zh)
        self.assertIn("is already in Trash", finder_en)
        self.assertIn("已在废纸篓中", finder_zh)
        self.assertIn("Trash by default", wuthering_en)
        self.assertIn("only when explicitly selected", wuthering_en)
        self.assertIn("默认移到废纸篓", wuthering_zh)
        self.assertIn("只有明确选择时才使用", wuthering_zh)
        self.assertIn("move it to Trash by default", migrator)
        self.assertNotIn("Rename it manually in Finder first", migrator)
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
