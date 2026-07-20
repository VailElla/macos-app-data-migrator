from __future__ import annotations

import hashlib
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "migrate-macos-app-data"
MIGRATOR = SKILL_ROOT / "scripts" / "migrate_app_data.py"
LAUNCHER_BUILDER = SKILL_ROOT / "scripts" / "build_wuthering_waves_launcher.sh"


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_snapshot(root: Path) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    stack = [(".", root)]
    while stack:
        relative, path = stack.pop()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
        elif stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
        else:
            kind = "special"
        record: Dict[str, Any] = {
            "type": kind,
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "mtime_ns": metadata.st_mtime_ns,
            "inode": metadata.st_ino,
            "device": metadata.st_dev,
            "nlink": metadata.st_nlink,
        }
        if kind == "file":
            record["size"] = metadata.st_size
            record["sha256"] = sha256(path)
        elif kind == "symlink":
            record["target"] = os.readlink(path)
        snapshot[relative] = record
        if kind == "directory":
            for entry in sorted(os.scandir(path), key=lambda item: item.name, reverse=True):
                child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
                stack.append((child_relative, Path(entry.path)))
    return snapshot


def copy_arguments(source: Path, destination: Path) -> list[str]:
    return [
        "copy",
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--test-allow-internal-destination",
    ]


class MigrationTests(unittest.TestCase):
    def test_copy_verify_resume_and_links_preserve_source_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-copy-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Example Data"
            destination = root / "external" / "Example Data"
            source.mkdir(parents=True)
            destination.parent.mkdir(parents=True)

            first_data = b"first-file\n" * 128
            second_data = hashlib.sha256(b"deterministic").digest() * 4096
            write_file(source / "first.bin", first_data)
            write_file(source / "nested" / "资料.dat", second_data)
            write_file(source / "resume-me.bin", b"resume" * 2048)
            os.link(source / "first.bin", source / "first-hardlink.bin")
            os.symlink("nested/资料.dat", source / "relative-link")
            os.symlink("nested", source / "directory-link")

            before = source_snapshot(source)
            run_migrator(*copy_arguments(source, destination), "--execute")
            self.assertEqual(source_snapshot(source), before)
            self.assertFalse(source.is_symlink())
            self.assertTrue((source / "resume-me.bin").is_file())

            state_path = destination.parent / f".{destination.name}.migrate-macos-app-data.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["status"], "copied")
            self.assertFalse(state["source_deleted_by_tool"])

            # Simulate an interruption after a normal file and one hardlink
            # representative disappeared from the destination-owned copy.
            (destination / "resume-me.bin").unlink()
            hardlink_representative = next(iter(state["hardlinks"].values()))
            (destination / hardlink_representative).unlink()
            state_path.write_text(json.dumps(state), encoding="utf-8")
            run_migrator(*copy_arguments(source, destination), "--execute")
            self.assertEqual(source_snapshot(source), before)

            verified = run_migrator(
                "verify",
                "--source",
                str(source),
                "--destination",
                str(destination),
            )
            self.assertIn("Full verification passed", verified.stdout)
            self.assertEqual(source_snapshot(source), before)
            self.assertEqual((destination / "nested" / "资料.dat").read_bytes(), second_data)
            self.assertEqual(os.readlink(destination / "relative-link"), "nested/资料.dat")
            self.assertEqual(os.readlink(destination / "directory-link"), "nested")
            self.assertEqual(
                (destination / "first.bin").stat().st_ino,
                (destination / "first-hardlink.bin").stat().st_ino,
            )

    def test_finder_handoff_requires_manual_rename_before_link(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-finder-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "App Data"
            destination = root / "external" / "App Data"
            write_file(source / "content.bin", b"safe content")
            destination.parent.mkdir(parents=True)

            run_migrator(*copy_arguments(source, destination), "--execute")
            run_migrator("verify", "--source", str(source), "--destination", str(destination))

            refused = run_migrator(
                "link", "--source", str(source), "--destination", str(destination), "--execute", check=False
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Rename it manually in Finder", refused.stderr)
            self.assertTrue(source.is_dir())

            reveal = run_migrator(
                "reveal",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--print-only",
            )
            self.assertIn("Finder handoff", reveal.stdout)

            # The test rename stands in for the explicit Finder action performed by a user.
            backup = source.with_name(f"{source.name}.internal-backup")
            os.rename(source, backup)
            dry_run = run_migrator(
                "link", "--source", str(source), "--destination", str(destination)
            )
            self.assertIn("Dry run only", dry_run.stdout)
            self.assertFalse(os.path.lexists(source))

            run_migrator(
                "link", "--source", str(source), "--destination", str(destination), "--execute"
            )
            self.assertTrue(source.is_symlink())
            self.assertEqual(source.resolve(), destination.resolve())
            self.assertTrue(backup.is_dir())
            self.assertEqual((backup / "content.bin").read_bytes(), b"safe content")

            backup_reveal = run_migrator(
                "reveal",
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--path",
                str(backup),
                "--print-only",
            )
            self.assertIn(str(backup), backup_reveal.stdout)

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-dry-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = root / "external" / "Data"
            write_file(source / "hello.txt", b"hello")
            destination.parent.mkdir(parents=True)
            before = source_snapshot(source)

            result = run_migrator(*copy_arguments(source, destination))
            self.assertIn("Dry run only", result.stdout)
            self.assertEqual(source_snapshot(source), before)
            self.assertFalse(destination.exists())
            self.assertFalse(
                (destination.parent / f".{destination.name}.migrate-macos-app-data.json").exists()
            )

    def test_internal_destination_requires_hidden_test_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-volume-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = root / "external" / "Data"
            write_file(source / "hello.txt", b"hello")
            destination.parent.mkdir(parents=True)
            result = run_migrator(
                "copy", "--source", str(source), "--destination", str(destination), check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"not confirmed as an external volume|canonical path")
            self.assertFalse(destination.exists())

    def test_broad_source_path_is_refused(self) -> None:
        unsafe_sources = (
            Path.home() / "Library",
            Path.home() / "Library" / "Containers" / "com.example.app",
            Path("/Applications/Example.app/Contents/Resources"),
            Path("/System/Applications/Finder.app"),
        )
        for unsafe_source in unsafe_sources:
            with self.subTest(source=unsafe_source):
                result = run_migrator(
                    "audit",
                    "--source",
                    str(unsafe_source),
                    "--destination",
                    "/Volumes/External/Example/Data",
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("Safety stop", result.stderr)

    def test_verify_detects_destination_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-tamper-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = root / "external" / "Data"
            write_file(source / "hello.txt", b"original")
            destination.parent.mkdir(parents=True)
            before = source_snapshot(source)
            run_migrator(*copy_arguments(source, destination), "--execute")
            (destination / "hello.txt").write_bytes(b"tampered")
            result = run_migrator(
                "verify", "--source", str(source), "--destination", str(destination), check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"SHA-256 mismatch|Metadata differs")
            self.assertEqual(source_snapshot(source), before)

    def test_launcher_and_app_copy_are_built_and_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-launcher-test-") as temporary:
            root = Path(temporary)
            game = root / "Fake Game.app"
            resources = root / "external" / "Resources"
            output_parent = root / "external" / "Applications"
            output = output_parent / "Test External Launcher.app"
            copied_parent = root / "second-external" / "Applications"
            copied_app = copied_parent / output.name
            (game / "Contents").mkdir(parents=True)
            resources.mkdir(parents=True)
            output_parent.mkdir(parents=True)
            copied_parent.mkdir(parents=True)
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
                "--game-bundle-id",
                "test.fake.game",
                "--display-name",
                "Test External Launcher",
                "--warning-delay",
                "15",
                "--test-allow-internal-output",
            ]
            result = subprocess.run(
                build_command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, msg=f"{result.stdout}\n{result.stderr}")
            executable = output / "Contents" / "MacOS" / "WutheringWavesExternalLauncher"
            self.assertTrue(executable.is_file())
            with (output / "Contents" / "Info.plist").open("rb") as handle:
                built_info = plistlib.load(handle)
            self.assertEqual(built_info["MigrationGamePath"], str(game))
            self.assertEqual(built_info["MigrationResourcesPath"], str(resources))
            self.assertFalse(any(output_parent.glob(".migrate-launcher-build.*")))

            refused = subprocess.run(
                build_command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Refusing to replace existing output", refused.stderr)

            before = source_snapshot(output)
            run_migrator(
                "copy",
                "--source",
                str(output),
                "--destination",
                str(copied_app),
                "--kind",
                "app",
                "--test-allow-internal-destination",
                "--execute",
            )
            verified = run_migrator(
                "verify", "--source", str(output), "--destination", str(copied_app)
            )
            self.assertIn("Full verification passed", verified.stdout)
            self.assertEqual(source_snapshot(output), before)
            signature = subprocess.run(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(copied_app)],
                check=False,
            )
            self.assertEqual(signature.returncode, 0)

    def test_migrator_exposes_no_source_deletion_command(self) -> None:
        source = MIGRATOR.read_text(encoding="utf-8")
        for forbidden in (
            "source.unlink(",
            "source.rename(",
            "source.rmdir(",
            "shutil.rmtree",
            "os.unlink(",
            "os.remove(",
            ".unlink(",
            'add_parser("move"',
            'add_parser("restore"',
            '"/bin/rm"',
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('add_parser("reveal"', source)
        self.assertIn('add_parser("link"', source)


if __name__ == "__main__":
    unittest.main()
