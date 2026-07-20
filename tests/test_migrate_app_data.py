from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "migrate-macos-app-data"
MIGRATOR = SKILL_ROOT / "scripts" / "migrate_app_data.py"
LAUNCHER_BUILDER = SKILL_ROOT / "scripts" / "build_wuthering_waves_launcher.sh"


def load_migrator_module() -> Any:
    spec = importlib.util.spec_from_file_location("migrate_app_data_for_tests", MIGRATOR)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to import migrator: {MIGRATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATOR_MODULE = load_migrator_module()


class ExternalAPFSTestVolume:
    """A disposable external APFS RAM volume with no internal-disk payload."""

    def __init__(self) -> None:
        self.device: str | None = None
        self.mount_path: Path | None = None

    def create(self) -> Path:
        attach = subprocess.run(
            ["/usr/bin/hdiutil", "attach", "-nomount", "ram://1048576"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        match = re.search(r"/dev/disk\d+", attach.stdout)
        if match is None:
            raise AssertionError(f"RAM disk device not found: {attach.stdout!r}")
        self.device = match.group(0)
        volume_name = f"MigratorTests-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        subprocess.run(
            ["/usr/sbin/diskutil", "eraseVolume", "APFS", volume_name, self.device],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        info = subprocess.run(
            ["/usr/sbin/diskutil", "info", "-plist", volume_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = plistlib.loads(info.stdout)
        if payload.get("Internal") is not False or payload.get("FilesystemType") != "apfs":
            raise AssertionError(f"Unexpected RAM volume policy: {payload}")
        self.mount_path = Path(payload["MountPoint"])
        return self.mount_path

    def close(self) -> None:
        if self.device is None:
            return
        device = self.device
        result = subprocess.run(
            ["/usr/bin/hdiutil", "detach", self.device],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise AssertionError(f"Unable to detach test RAM volume {device}: {result.stderr}")
        self.device = None
        self.mount_path = None


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
    ]


def write_xattr(path: Path, name: str, value: bytes, symlink: bool = False) -> None:
    command = ["/usr/bin/xattr"]
    if symlink:
        command.append("-s")
    command.extend(["-w", "-x", name, value.hex(), str(path)])
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_xattr(path: Path, name: str, symlink: bool = False) -> bytes:
    command = ["/usr/bin/xattr"]
    if symlink:
        command.append("-s")
    command.extend(["-p", "-x", name, str(path)])
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return bytes.fromhex("".join(result.stdout.split()))


def add_acl(path: Path, entry: str) -> None:
    command = ["/bin/chmod", "+a", entry, str(path)]
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def acl_entries_for_test(path: Path) -> list[str]:
    result = subprocess.run(
        ["/bin/ls", "-lde", str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    entries: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        match = re.match(r"^\s*\d+:\s*(.+)$", line)
        if match:
            entries.append(match.group(1))
    return entries


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_volume = ExternalAPFSTestVolume()
        cls.addClassCleanup(cls.test_volume.close)
        cls.external_root = cls.test_volume.create()

    def external_parent(self, label: str) -> Path:
        path = self.external_root / f"{label}-{uuid.uuid4().hex}"
        path.mkdir()
        return path

    def test_state_writes_never_follow_temporary_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-state-victim-") as temporary:
            victim = Path(temporary) / "must-remain-unchanged.txt"
            victim.write_text("keep me", encoding="utf-8")
            state_parent = self.external_parent("state-symlink")
            state_path = state_parent / ".Data.migrate-macos-app-data.json"
            migration_id = "a" * 32
            state = {
                "schema_version": 3,
                "migration_id": migration_id,
            }

            old_predictable_temporary = state_parent / f".{state_path.name}.{migration_id}.tmp"
            old_predictable_temporary.symlink_to(victim)
            MIGRATOR_MODULE.write_state(state_path, state)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")
            self.assertTrue(old_predictable_temporary.is_symlink())
            self.assertTrue(state_path.is_file())

            write_nonce = "b" * 32
            exact_temporary = state_parent / f".{state_path.name}.{migration_id}.{write_nonce}.tmp"
            exact_temporary.symlink_to(victim)
            fake_uuid = mock.Mock(hex=write_nonce)
            with mock.patch.object(MIGRATOR_MODULE.uuid, "uuid4", return_value=fake_uuid):
                with self.assertRaises(MIGRATOR_MODULE.MigrationError):
                    MIGRATOR_MODULE.write_state(state_path, state)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")

    def test_full_verify_rejects_extra_destination_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-hardlink-topology-") as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            for name in ("a.bin", "b.bin"):
                write_file(source / name, b"identical payload")
            fixed_ns = 1_700_000_000_000_000_000
            for path in (source / "a.bin", source / "b.bin"):
                os.utime(path, ns=(fixed_ns, fixed_ns))
            shutil.copy2(source / "a.bin", destination / "a.bin")
            os.link(destination / "a.bin", destination / "b.bin")
            MIGRATOR_MODULE.copy_directory_metadata(source, destination)

            with self.assertRaisesRegex(
                MIGRATOR_MODULE.MigrationError,
                "Hardlink topology differs",
            ):
                MIGRATOR_MODULE.full_verify(source, destination)

    def test_full_verify_rejects_changes_after_a_file_was_checked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-verify-race-") as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            for name, payload in (("a.bin", b"A-original"), ("b.bin", b"B-original")):
                write_file(source / name, payload)
                shutil.copy2(source / name, destination / name)
            MIGRATOR_MODULE.copy_directory_metadata(source, destination)

            original_sha256 = MIGRATOR_MODULE.sha256_file
            mutated = False

            def mutate_after_first_file(path: Path) -> str:
                nonlocal mutated
                candidate = Path(path)
                if not mutated and candidate == source / "b.bin":
                    (destination / "a.bin").write_bytes(b"A-tampered-after-check")
                    mutated = True
                return original_sha256(candidate)

            with mock.patch.object(
                MIGRATOR_MODULE,
                "sha256_file",
                side_effect=mutate_after_first_file,
            ):
                with self.assertRaisesRegex(
                    MIGRATOR_MODULE.MigrationError,
                    "Destination changed during verification",
                ):
                    MIGRATOR_MODULE.full_verify(source, destination)
            self.assertNotEqual(
                (source / "a.bin").read_bytes(),
                (destination / "a.bin").read_bytes(),
            )

    def test_app_bundle_cannot_be_downgraded_to_data_kind(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-kind-app-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Example.app"
            info_path = source / "Contents" / "Info.plist"
            info_path.parent.mkdir(parents=True)
            with info_path.open("wb") as handle:
                plistlib.dump(
                    {
                        "CFBundleIdentifier": "test.example.app",
                        "CFBundleExecutable": "Example",
                    },
                    handle,
                )
            result = run_migrator(
                "audit",
                "--source",
                str(source),
                "--destination",
                "/Volumes/External/Applications/Example.app",
                "--kind",
                "data",
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("conflicts with detected kind app", result.stderr)

            info_path.unlink()
            invalid_bundle = run_migrator(
                "audit",
                "--source",
                str(source),
                "--destination",
                "/Volumes/External/Applications/Example.app",
                check=False,
            )
            self.assertEqual(invalid_bundle.returncode, 2)
            self.assertIn("not a valid app bundle", invalid_bundle.stderr)

    def test_copy_verify_resume_and_links_preserve_source_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-copy-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Example Data"
            destination = self.external_parent("copy") / "Example Data"
            source.mkdir(parents=True)

            first_data = b"first-file\n" * 128
            second_data = hashlib.sha256(b"deterministic").digest() * 4096
            write_file(source / "first.bin", first_data)
            write_file(source / "nested" / "资料.dat", second_data)
            write_file(source / "resume-me.bin", b"resume" * 2048)
            os.link(source / "first.bin", source / "first-hardlink.bin")
            os.symlink("nested/资料.dat", source / "relative-link")
            os.symlink("nested", source / "directory-link")

            before = source_snapshot(source)
            run_migrator(
                *copy_arguments(source, destination),
                "--process-name",
                "NoSuchMigratorProcess",
                "--execute",
            )
            self.assertEqual(source_snapshot(source), before)
            self.assertFalse(source.is_symlink())
            self.assertTrue((source / "resume-me.bin").is_file())

            state_path = destination.parent / f".{destination.name}.migrate-macos-app-data.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], 3)
            self.assertEqual(state["status"], "copied")
            self.assertEqual(state["process_names"], ["NoSuchMigratorProcess"])
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

    def test_finder_handoff_requires_source_path_to_be_free_before_link(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-finder-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "App Data"
            destination = self.external_parent("finder") / "App Data"
            write_file(source / "content.bin", b"safe content")

            run_migrator(*copy_arguments(source, destination), "--execute")
            run_migrator("verify", "--source", str(source), "--destination", str(destination))

            refused = run_migrator(
                "link", "--source", str(source), "--destination", str(destination), "--execute", check=False
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Complete the authorized Finder handoff first", refused.stderr)
            self.assertIn("move it to Trash by default", refused.stderr)
            self.assertIn("explicitly selected sibling backup", refused.stderr)
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
            self.assertIn("move the source to Trash", reveal.stdout)
            self.assertIn("do not empty Trash", reveal.stdout)

            # This test covers the explicitly selected sibling-backup fallback.
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

    def test_finder_trash_handoff_allows_link_with_recoverable_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-finder-trash-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "App Data"
            destination = self.external_parent("finder-trash") / "App Data"
            write_file(source / "content.bin", b"recoverable source")

            run_migrator(*copy_arguments(source, destination), "--execute")
            run_migrator("verify", "--source", str(source), "--destination", str(destination))

            simulated_trash = root / "Trash"
            simulated_trash.mkdir()
            trashed_source = simulated_trash / source.name
            os.rename(source, trashed_source)

            dry_run = run_migrator("link", "--source", str(source), "--destination", str(destination))
            self.assertIn("does not empty Trash", dry_run.stdout)
            self.assertFalse(os.path.lexists(source))

            run_migrator(
                "link", "--source", str(source), "--destination", str(destination), "--execute"
            )
            self.assertTrue(source.is_symlink())
            self.assertEqual(source.resolve(), destination.resolve())
            self.assertEqual((trashed_source / "content.bin").read_bytes(), b"recoverable source")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-dry-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = self.external_parent("dry-run") / "Data"
            write_file(source / "hello.txt", b"hello")
            before = source_snapshot(source)

            result = run_migrator(*copy_arguments(source, destination))
            self.assertIn("Dry run only", result.stdout)
            self.assertEqual(source_snapshot(source), before)
            self.assertFalse(destination.exists())
            self.assertFalse(
                (destination.parent / f".{destination.name}.migrate-macos-app-data.json").exists()
            )

    def test_internal_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-volume-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = root / "internal-destination" / "Data"
            write_file(source / "hello.txt", b"hello")
            destination.parent.mkdir(parents=True)
            result = run_migrator(
                "copy", "--source", str(source), "--destination", str(destination), check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"not confirmed as an external volume|canonical path")
            self.assertFalse(destination.exists())

    def test_destination_symlink_ancestor_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-symlink-parent-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            write_file(source / "hello.txt", b"hello")
            real_parent = self.external_parent("real-parent")
            (real_parent / "Nested").mkdir()
            alias_parent = self.external_root / f"alias-{uuid.uuid4().hex}"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            destination = alias_parent / "Nested" / "Data"

            result = run_migrator(
                "copy",
                "--source",
                str(source),
                "--destination",
                str(destination),
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("canonical path", result.stderr)
            self.assertFalse(destination.exists())
            self.assertFalse(
                (destination.parent / f".{destination.name}.migrate-macos-app-data.json").exists()
            )

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
            destination = self.external_parent("tamper") / "Data"
            write_file(source / "hello.txt", b"original")
            before = source_snapshot(source)
            run_migrator(*copy_arguments(source, destination), "--execute")
            (destination / "hello.txt").write_bytes(b"tampered")
            result = run_migrator(
                "verify", "--source", str(source), "--destination", str(destination), check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"SHA-256 mismatch|Metadata differs")
            self.assertEqual(source_snapshot(source), before)

    def test_xattrs_are_copied_and_tampering_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-xattr-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = self.external_parent("xattr") / "Data"
            write_file(source / "payload.bin", b"xattr payload")
            os.symlink("payload.bin", source / "payload-link")
            directory_value = b"directory metadata\x00with binary"
            file_value = b"file metadata\xff"
            symlink_value = b"symlink metadata"
            write_xattr(source, "com.example.migrator-directory", directory_value)
            write_xattr(source / "payload.bin", "com.example.migrator-file", file_value)
            write_xattr(
                source / "payload-link",
                "com.example.migrator-symlink",
                symlink_value,
                symlink=True,
            )

            run_migrator(*copy_arguments(source, destination), "--execute")

            # Simulate an interruption after the destination symlink was created
            # but before its extended attributes and ACL were applied.
            (destination / "payload-link").unlink()
            os.symlink("payload.bin", destination / "payload-link")
            run_migrator(*copy_arguments(source, destination), "--execute")

            verified = run_migrator(
                "verify", "--source", str(source), "--destination", str(destination)
            )
            self.assertIn("Full verification passed", verified.stdout)
            self.assertEqual(
                read_xattr(destination, "com.example.migrator-directory"),
                directory_value,
            )
            self.assertEqual(
                read_xattr(destination / "payload.bin", "com.example.migrator-file"),
                file_value,
            )
            self.assertEqual(
                read_xattr(
                    destination / "payload-link",
                    "com.example.migrator-symlink",
                    symlink=True,
                ),
                symlink_value,
            )

            write_xattr(
                destination / "payload.bin",
                "com.example.migrator-file",
                b"tampered metadata",
            )
            refused = run_migrator(
                "verify",
                "--source",
                str(source),
                "--destination",
                str(destination),
                check=False,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Metadata differs", refused.stderr)

    def test_verification_ignores_instance_xattrs_only_on_app_root(self) -> None:
        path = Path("/tmp/example.app")
        finder_comment = b"com.apple.metadata:kMDItemFinderComment"
        macl = b"com.apple.macl"
        provenance = b"com.apple.provenance"
        quarantine = b"com.apple.quarantine"
        application_metadata = b"com.example.application-metadata"
        all_names = [finder_comment, macl, provenance, quarantine, application_metadata]
        with mock.patch.object(
            MIGRATOR_MODULE,
            "list_xattr_names",
            return_value=all_names,
        ), mock.patch.object(
            MIGRATOR_MODULE,
            "read_xattr",
            return_value=b"preserved-value",
        ):
            data_result = MIGRATOR_MODULE.xattr_map(
                path,
                follow_symlinks=False,
                ignored_names=MIGRATOR_MODULE.verification_ignored_xattrs("data", "."),
            )
            app_root_result = MIGRATOR_MODULE.xattr_map(
                path,
                follow_symlinks=False,
                ignored_names=MIGRATOR_MODULE.verification_ignored_xattrs("app", "."),
            )
            app_child_result = MIGRATOR_MODULE.xattr_map(
                path,
                follow_symlinks=False,
                ignored_names=MIGRATOR_MODULE.verification_ignored_xattrs("app", "Contents/MacOS/App"),
            )

        self.assertEqual(
            app_root_result,
            {
                application_metadata.hex(): hashlib.sha256(
                    b"preserved-value"
                ).hexdigest()
            },
        )
        self.assertEqual(set(data_result), {name.hex() for name in all_names})
        self.assertEqual(set(app_child_result), {name.hex() for name in all_names})

    def test_full_verify_limits_instance_xattr_exceptions_to_app_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-root-xattr-") as temporary:
            root = Path(temporary)
            source = root / "Source.app"
            destination = root / "Destination.app"
            write_file(source / "Contents" / "Info.plist", b"identical app payload")
            shutil.copytree(source, destination, copy_function=shutil.copy2)

            write_xattr(source, "com.apple.quarantine", b"source-instance")
            write_xattr(destination, "com.apple.quarantine", b"destination-instance")
            MIGRATOR_MODULE.full_verify(source, destination, kind="app")

            write_xattr(
                source / "Contents" / "Info.plist",
                "com.apple.quarantine",
                b"source-payload-metadata",
            )
            write_xattr(
                destination / "Contents" / "Info.plist",
                "com.apple.quarantine",
                b"destination-payload-metadata",
            )
            with self.assertRaisesRegex(MIGRATOR_MODULE.MigrationError, "Metadata differs"):
                MIGRATOR_MODULE.full_verify(source, destination, kind="app")

    def test_acls_are_copied_and_tampering_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-app-acl-") as temporary:
            root = Path(temporary)
            source = root / "internal" / "Data"
            destination = self.external_parent("acl") / "Data"
            write_file(source / "payload.bin", b"acl payload")
            os.symlink("payload.bin", source / "payload-link")
            acl_entry = "everyone allow readattr"
            add_acl(source, acl_entry)
            add_acl(source / "payload.bin", acl_entry)

            run_migrator(*copy_arguments(source, destination), "--execute")
            verified = run_migrator(
                "verify", "--source", str(source), "--destination", str(destination)
            )
            self.assertIn("Full verification passed", verified.stdout)
            self.assertEqual(acl_entries_for_test(destination), acl_entries_for_test(source))
            self.assertEqual(
                acl_entries_for_test(destination / "payload.bin"),
                acl_entries_for_test(source / "payload.bin"),
            )
            subprocess.run(
                ["/bin/chmod", "-N", str(destination)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            refused = run_migrator(
                "verify",
                "--source",
                str(source),
                "--destination",
                str(destination),
                check=False,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Metadata differs", refused.stderr)

    def test_launcher_and_app_copy_are_built_and_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="migrate-launcher-test-") as temporary:
            root = Path(temporary).resolve()
            game = root / "Fake Game.app"
            resources_parent = self.external_parent("launcher-resources")
            resources = resources_parent / "Resources"
            output_parent = self.external_parent("launcher-output")
            output = output_parent / "Test External Launcher.app"
            copied_parent = self.external_parent("launcher-copy")
            copied_app = copied_parent / output.name
            (game / "Contents" / "MacOS").mkdir(parents=True)
            resources.mkdir(parents=True)
            fake_executable = game / "Contents" / "MacOS" / "FakeGame"
            shutil.copyfile("/usr/bin/true", fake_executable)
            fake_executable.chmod(0o755)
            with (game / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump(
                    {
                        "CFBundleIdentifier": "test.fake.game",
                        "CFBundleExecutable": "FakeGame",
                        "CFBundleName": "Fake Game",
                        "CFBundlePackageType": "APPL",
                    },
                    handle,
                )
            signed = subprocess.run(
                [
                    "/usr/bin/codesign",
                    "--force",
                    "--deep",
                    "--sign",
                    "-",
                    "--identifier",
                    "test.fake.game",
                    str(game),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(signed.returncode, 0, msg=signed.stderr)

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
            ]

            nested_resources = resources / "Nested"
            nested_resources.mkdir()
            resources_alias = resources_parent / "ResourcesAlias"
            resources_alias.symlink_to(resources, target_is_directory=True)
            escaped_output = resources_alias / "Nested" / "Escaped Launcher.app"
            escaped_command = list(build_command)
            output_index = escaped_command.index("--output-app") + 1
            escaped_command[output_index] = str(escaped_output)
            escaped = subprocess.run(
                escaped_command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(escaped.returncode, 2)
            self.assertIn("canonical", escaped.stderr)
            self.assertFalse((nested_resources / escaped_output.name).exists())

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
