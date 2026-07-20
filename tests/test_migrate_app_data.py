from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "migrate-macos-app-data"
MIGRATOR = SKILL_ROOT / "scripts" / "migrate_app_data.py"
LAUNCHER_BUILDER = SKILL_ROOT / "scripts" / "build_wuthering_waves_launcher.sh"
CONFIRM = "MOVE_WITHOUT_FULL_BACKUP"


def run_migrator(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["/usr/bin/python3", str(MIGRATOR), *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class MigrationTests(unittest.TestCase):
    def test_stream_move_preserves_content_links_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-test-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Example Data"
            destination = root / "external" / "Example Data"
            source.mkdir(parents=True)
            destination.parent.mkdir(parents=True)

            first_data = b"first-file\n" * 128
            second_data = hashlib.sha256(b"deterministic").digest() * 4096
            write_file(source / "first.bin", first_data)
            write_file(source / "nested" / "资料.dat", second_data)
            os.link(source / "first.bin", source / "first-hardlink.bin")
            os.symlink("nested/资料.dat", source / "relative-link")
            os.symlink("nested", source / "directory-link")

            initial_files = 3
            initial_bytes = len(first_data) * 2 + len(second_data)
            destination.mkdir()
            write_file(destination / "first.bin", first_data)

            state_path = destination.parent / f".{destination.name}.migrate-macos-app-data.json"
            state = {
                "schema_version": 1,
                "migration_id": "resume1234567890",
                "source": str(source),
                "destination": str(destination),
                "strategy": "stream",
                "link_mode": "symlink",
                "status": "moving",
                "created_at": 1,
                "updated_at": 1,
                "initial_stats": {
                    "files": initial_files,
                    "directories": 2,
                    "symlinks": 2,
                    "special": 0,
                    "bytes": initial_bytes,
                    "largest_file": len(second_data),
                },
                "progress": {"files": 0, "symlinks": 0, "bytes": 0},
                "hardlinks": {},
                "per_file_sha256": True,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "stream",
                "--link-mode",
                "symlink",
                "--execute",
                "--confirm",
                CONFIRM,
            )

            self.assertTrue(source.is_symlink())
            self.assertEqual(source.resolve(), destination.resolve())
            self.assertEqual((destination / "first.bin").read_bytes(), first_data)
            self.assertEqual((destination / "nested" / "资料.dat").read_bytes(), second_data)
            self.assertEqual(os.readlink(destination / "relative-link"), "nested/资料.dat")
            self.assertEqual(os.readlink(destination / "directory-link"), "nested")
            self.assertEqual(
                (destination / "first.bin").stat().st_ino,
                (destination / "first-hardlink.bin").stat().st_ino,
            )

            verified = run_migrator(
                "verify",
                "--source",
                str(source),
                "--destination",
                str(destination),
            )
            self.assertIn("Verification passed", verified.stdout)

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            saved_state["status"] = "moving"
            state_path.write_text(json.dumps(saved_state), encoding="utf-8")
            finalized = run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "stream",
                "--link-mode",
                "symlink",
                "--execute",
                "--confirm",
                CONFIRM,
            )
            self.assertIn("already complete", finalized.stdout)
            self.assertEqual(json.loads(state_path.read_text())["status"], "linked")

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            saved_state["status"] = "moving"
            state_path.write_text(json.dumps(saved_state), encoding="utf-8")
            source.unlink()
            recovery_plan = run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "stream",
                "--link-mode",
                "symlink",
            )
            self.assertIn("would recreate the source link", recovery_plan.stdout)
            self.assertFalse(source.exists())
            run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "stream",
                "--link-mode",
                "symlink",
                "--execute",
                "--confirm",
                CONFIRM,
            )
            self.assertTrue(source.is_symlink())

            restore_plan = run_migrator(
                "restore",
                "--source-link",
                str(source),
                "--data",
                str(destination),
            )
            self.assertIn("Dry run only", restore_plan.stdout)
            self.assertTrue(source.is_symlink())
            run_migrator(
                "restore",
                "--source-link",
                str(source),
                "--data",
                str(destination),
                "--execute",
                "--confirm",
                "RESTORE_TO_ORIGINAL",
            )
            self.assertTrue(source.is_dir())
            self.assertFalse(source.is_symlink())
            self.assertFalse(destination.exists())
            self.assertEqual((source / "nested" / "资料.dat").read_bytes(), second_data)

    def test_atomic_move_and_verify(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-atomic-") as temporary:
            root = Path(temporary)
            source = root / "one" / "Data"
            destination = root / "two" / "Data"
            write_file(source / "hello.txt", b"hello")
            destination.parent.mkdir(parents=True)

            run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "atomic",
                "--execute",
            )
            self.assertTrue(source.is_symlink())
            self.assertEqual((source / "hello.txt").read_text(), "hello")
            run_migrator(
                "verify",
                "--source",
                str(source),
                "--destination",
                str(destination),
            )

    def test_dry_run_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-dry-") as temporary:
            root = Path(temporary)
            source = root / "one" / "Data"
            destination = root / "two" / "Data"
            write_file(source / "hello.txt", b"hello")
            destination.parent.mkdir(parents=True)
            result = run_migrator(
                "move",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--strategy",
                "stream",
            )
            self.assertIn("Dry run only", result.stdout)
            self.assertTrue((source / "hello.txt").exists())
            self.assertFalse(destination.exists())

    def test_broad_path_is_refused(self) -> None:
        result = run_migrator(
            "audit",
            "--source",
            str(Path.home() / "Library"),
            "--destination",
            "/Volumes/External/Example/Data",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing broad source path", result.stderr)

    def test_launcher_builds_from_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-launcher-test-") as temporary:
            root = Path(temporary)
            game = root / "Fake Game.app"
            resources = root / "external" / "Resources"
            output = root / "Applications" / "Test External Launcher.app"
            (game / "Contents").mkdir(parents=True)
            resources.mkdir(parents=True)
            with (game / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump(
                    {
                        "CFBundleIdentifier": "test.fake.game",
                        "CFBundleExecutable": "FakeGame",
                        "CFBundleName": "Fake Game",
                    },
                    handle,
                )

            build_command = [
                str(LAUNCHER_BUILDER),
                "--game-app",
                str(game),
                "--resources",
                str(resources),
                "--output-app",
                str(output),
                "--bundle-id",
                "test.migrate.launcher",
                "--display-name",
                "Test External Launcher",
                "--warning-delay",
                "15",
            ]
            result = subprocess.run(
                build_command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, msg=f"{result.stdout}\n{result.stderr}")
            self.assertTrue((output / "Contents" / "MacOS" / "WutheringWavesExternalLauncher").is_file())
            with (output / "Contents" / "Info.plist").open("rb") as handle:
                built_info = plistlib.load(handle)
            self.assertEqual(built_info["MigrationGamePath"], str(game))
            self.assertEqual(built_info["MigrationResourcesPath"], str(resources))

            replacement = subprocess.run(
                [*build_command, "--replace"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(replacement.returncode, 0, msg=replacement.stderr)

            wrong_id_command = [
                "test.migrate.other" if value == "test.migrate.launcher" else value
                for value in build_command
            ]
            refused = subprocess.run(
                [*wrong_id_command, "--replace"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("different bundle ID", refused.stderr)


if __name__ == "__main__":
    unittest.main()
