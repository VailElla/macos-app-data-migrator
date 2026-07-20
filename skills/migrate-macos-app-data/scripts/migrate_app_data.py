#!/usr/bin/env python3
"""Move one macOS app-data directory with bounded temporary disk usage.

The streaming strategy copies and SHA-256 verifies one file at a time, fsyncs it,
then removes only that verified source file.  A small JSON journal makes the
operation resumable.  The source directory is replaced by a symlink only after
the complete destination tree has been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
CONFIRM_PHRASE = "MOVE_WITHOUT_FULL_BACKUP"
RESTORE_CONFIRM_PHRASE = "RESTORE_TO_ORIGINAL"
PARTIAL_PREFIX = ".migrate-macos-app-data-"


class MigrationError(RuntimeError):
    pass


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def normalized_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.abspath(path))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_scoped_path(path: Path, label: str) -> None:
    home = Path.home()
    forbidden = {
        Path("/"),
        Path("/Applications"),
        Path("/Library"),
        Path("/System"),
        Path("/Users"),
        Path("/Volumes"),
        home,
        home / "Library",
        home / "Library" / "Containers",
        home / "Library" / "Application Support",
    }
    if path in forbidden or len(path.parts) < 4:
        raise MigrationError(f"Refusing broad {label} path: {path}")


def validate_pair(source: Path, destination: Path) -> None:
    validate_scoped_path(source, "source")
    validate_scoped_path(destination, "destination")
    source_compare = source if source.is_symlink() else source.resolve(strict=False)
    destination_compare = destination.resolve(strict=False)
    if source == destination or source_compare == destination_compare:
        raise MigrationError("Source and destination are the same path")
    if is_within(destination_compare, source_compare):
        raise MigrationError("Destination cannot be inside source")
    if is_within(source_compare, destination_compare):
        raise MigrationError("Source cannot be inside destination")


def nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        if candidate.parent == candidate:
            raise MigrationError(f"No existing parent for {path}")
        candidate = candidate.parent
    return candidate


def disk_info(path: Path) -> dict[str, Any]:
    existing = nearest_existing_parent(path)
    df_result = subprocess.run(
        ["/bin/df", "-P", str(existing)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if df_result.returncode != 0 or len(df_result.stdout.splitlines()) < 2:
        raise MigrationError(f"df could not identify the filesystem for {existing}")
    device = df_result.stdout.splitlines()[-1].split()[0]
    result = subprocess.run(
        ["/usr/sbin/diskutil", "info", "-plist", device],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise MigrationError(
            f"diskutil could not inspect {existing}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    try:
        return plistlib.loads(result.stdout)
    except Exception as error:  # pragma: no cover - defensive parser guard
        raise MigrationError(f"Invalid diskutil response for {existing}: {error}") from error


def filesystem_name(info: dict[str, Any]) -> str:
    return str(
        info.get("FilesystemType")
        or info.get("FilesystemName")
        or info.get("FileSystemPersonality")
        or "unknown"
    )


def tree_stats(root: Path) -> dict[str, int]:
    if root.is_symlink():
        return {
            "files": 0,
            "directories": 0,
            "symlinks": 1,
            "special": 0,
            "bytes": 0,
            "unique_bytes": 0,
            "largest_file": 0,
        }
    if not root.is_dir():
        raise MigrationError(f"Not a directory: {root}")

    result = {
        "files": 0,
        "directories": 1,
        "symlinks": 0,
        "special": 0,
        "bytes": 0,
        "unique_bytes": 0,
        "largest_file": 0,
    }
    seen_inodes: set[tuple[int, int]] = set()
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directory_names):
            item = current_path / name
            item_mode = item.lstat().st_mode
            if stat.S_ISLNK(item_mode):
                result["symlinks"] += 1
                directory_names.remove(name)
            elif stat.S_ISDIR(item_mode):
                result["directories"] += 1
            else:
                result["special"] += 1
                directory_names.remove(name)
        for name in file_names:
            item = current_path / name
            item_stat = item.lstat()
            if stat.S_ISLNK(item_stat.st_mode):
                result["symlinks"] += 1
            elif stat.S_ISREG(item_stat.st_mode):
                result["files"] += 1
                result["bytes"] += item_stat.st_size
                inode_key = (item_stat.st_dev, item_stat.st_ino)
                if inode_key not in seen_inodes:
                    seen_inodes.add(inode_key)
                    result["unique_bytes"] += item_stat.st_size
                result["largest_file"] = max(result["largest_file"], item_stat.st_size)
            else:
                result["special"] += 1
    return result


def print_stats(label: str, stats: dict[str, int]) -> None:
    print(
        f"{label}: {stats['files']} files, {stats['directories']} directories, "
        f"{stats['symlinks']} symlinks, {human_bytes(stats['bytes'])} logical data, "
        f"{human_bytes(stats.get('unique_bytes', stats['bytes']))} unique file data, "
        f"largest file {human_bytes(stats['largest_file'])}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def state_path_for(destination: Path, override: str | None) -> Path:
    if override:
        candidate = normalized_path(override)
        if candidate.parent != destination.parent:
            raise MigrationError("A custom journal must stay beside the destination directory")
        return candidate
    return destination.parent / f".{destination.name}.migrate-macos-app-data.json"


def write_state(path: Path, state_data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state_data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise MigrationError(f"Unsupported state schema in {path}")
    migration_id = str(data.get("migration_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", migration_id):
        raise MigrationError(f"Invalid migration ID in {path}")
    return data


def check_state_paths(state_data: dict[str, Any], source: Path, destination: Path) -> None:
    if state_data.get("source") != str(source) or state_data.get("destination") != str(destination):
        raise MigrationError("Existing migration journal belongs to different paths")


def check_processes(process_names: Iterable[str]) -> None:
    running: list[str] = []
    for name in process_names:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-x", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            running.append(name)
    if running:
        raise MigrationError("Quit these processes before migration: " + ", ".join(running))


def ensure_apfs(destination: Path, allow_non_apfs: bool) -> dict[str, Any]:
    info = disk_info(destination)
    fs_name = filesystem_name(info)
    if "apfs" not in fs_name.lower() and not allow_non_apfs:
        raise MigrationError(
            f"Destination filesystem is {fs_name}, not APFS. "
            "Use an APFS volume or explicitly pass --allow-non-apfs after reviewing metadata risks."
        )
    return info


def source_link_matches(source: Path, destination: Path) -> bool:
    if not source.is_symlink():
        return False
    return source.resolve(strict=False) == destination.resolve(strict=False)


def guard_destination_root(destination_root: Path, expected_device: int) -> None:
    if not destination_root.is_dir() or destination_root.stat().st_dev != expected_device:
        raise MigrationError(
            "Destination volume disappeared or changed. Reconnect the original volume and resume."
        )


def ensure_destination_parent(destination_root: Path, destination: Path, expected_device: int) -> None:
    guard_destination_root(destination_root, expected_device)
    destination.parent.mkdir(parents=True, exist_ok=True)
    guard_destination_root(destination_root, expected_device)
    if destination.parent.stat().st_dev != expected_device:
        raise MigrationError("Destination parent is no longer on the expected volume")


def copy_symlink(
    source: Path,
    destination: Path,
    destination_root: Path,
    expected_device: int,
) -> None:
    target = os.readlink(source)
    ensure_destination_parent(destination_root, destination, expected_device)
    if destination.is_symlink():
        if os.readlink(destination) != target:
            raise MigrationError(f"Conflicting destination symlink: {destination}")
    elif destination.exists():
        raise MigrationError(f"Destination already exists with another type: {destination}")
    else:
        os.symlink(target, destination)
        fsync_directory(destination.parent)
    source.unlink()


class StateRecorder:
    def __init__(self, path: Path, state_data: dict[str, Any]) -> None:
        self.path = path
        self.state_data = state_data
        self.pending_files = 0
        self.pending_bytes = 0

    def completed(self, byte_count: int) -> None:
        progress = self.state_data["progress"]
        progress["files"] += 1
        progress["bytes"] += byte_count
        self.pending_files += 1
        self.pending_bytes += byte_count
        if self.pending_files >= 64 or self.pending_bytes >= 256 * 1024 * 1024:
            self.flush()

    def completed_symlink(self) -> None:
        self.state_data["progress"]["symlinks"] += 1
        self.pending_files += 1
        if self.pending_files >= 64:
            self.flush()

    def flush(self) -> None:
        self.state_data["updated_at"] = int(time.time())
        write_state(self.path, self.state_data)
        self.pending_files = 0
        self.pending_bytes = 0


def remove_own_partials(destination: Path, migration_id: str) -> int:
    if not destination.exists():
        return 0
    prefix = f"{PARTIAL_PREFIX}{migration_id}-"
    removed = 0
    for current, _, files in os.walk(destination):
        for name in files:
            if name.startswith(prefix) and name.endswith(".partial"):
                partial = Path(current) / name
                partial.unlink()
                removed += 1
    return removed


def source_unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )


def verified_existing_file(source: Path, destination: Path) -> bool:
    if not destination.is_file() or destination.is_symlink():
        return False
    source_stat = source.stat()
    destination_stat = destination.stat()
    if source_stat.st_size != destination_stat.st_size:
        return False
    return sha256_file(source) == sha256_file(destination)


def copy_regular_file(
    source: Path,
    destination: Path,
    relative_path: Path,
    migration_id: str,
    state_data: dict[str, Any],
    recorder: StateRecorder,
    destination_root: Path,
    expected_device: int,
) -> None:
    source_stat = source.stat()
    ensure_destination_parent(destination_root, destination, expected_device)
    hardlink_key = f"{source_stat.st_dev}:{source_stat.st_ino}"
    hardlinks: dict[str, str] = state_data["hardlinks"]
    existing_relative = hardlinks.get(hardlink_key)

    if destination.exists() or destination.is_symlink():
        if verified_existing_file(source, destination):
            if existing_relative:
                existing_relative_path = Path(existing_relative)
                if existing_relative_path.is_absolute() or ".." in existing_relative_path.parts:
                    raise MigrationError("Unsafe hardlink path in migration journal")
                existing_destination = Path(state_data["destination"]) / existing_relative_path
                if not is_within(
                    existing_destination.resolve(strict=False),
                    destination_root.resolve(strict=False),
                ):
                    raise MigrationError("Hardlink target escapes the destination directory")
                if not existing_destination.is_file():
                    raise MigrationError(f"Missing migrated hardlink target: {existing_destination}")
                if destination.stat().st_ino != existing_destination.stat().st_ino:
                    destination.unlink()
                    os.link(existing_destination, destination)
                    fsync_directory(destination.parent)
            elif source_stat.st_nlink > 1:
                hardlinks[hardlink_key] = relative_path.as_posix()
            source.unlink()
            recorder.completed(source_stat.st_size)
            return
        raise MigrationError(f"Conflicting destination file: {destination}")

    if existing_relative:
        existing_relative_path = Path(existing_relative)
        if existing_relative_path.is_absolute() or ".." in existing_relative_path.parts:
            raise MigrationError("Unsafe hardlink path in migration journal")
        existing_destination = Path(state_data["destination"]) / existing_relative_path
        if not is_within(existing_destination.resolve(strict=False), destination_root.resolve(strict=False)):
            raise MigrationError("Hardlink target escapes the destination directory")
        if not existing_destination.is_file():
            raise MigrationError(f"Missing migrated hardlink target: {existing_destination}")
        os.link(existing_destination, destination)
        fsync_directory(destination.parent)
        source.unlink()
        recorder.completed(source_stat.st_size)
        return

    relative_digest = hashlib.sha256(relative_path.as_posix().encode("utf-8")).hexdigest()[:16]
    temporary = destination.parent / f"{PARTIAL_PREFIX}{migration_id}-{relative_digest}.partial"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()

    result = subprocess.run(
        ["/usr/bin/ditto", "--rsrc", "--extattr", "--acl", str(source), str(temporary)],
        check=False,
    )
    if result.returncode != 0:
        raise MigrationError(f"ditto failed while copying {source}")

    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())

    after_copy_stat = source.stat()
    if not source_unchanged(source_stat, after_copy_stat):
        temporary.unlink(missing_ok=True)
        raise MigrationError(f"Source changed during copy: {source}")

    if source_stat.st_size != temporary.stat().st_size or sha256_file(source) != sha256_file(temporary):
        temporary.unlink(missing_ok=True)
        raise MigrationError(f"SHA-256 verification failed: {source}")

    os.replace(temporary, destination)
    fsync_directory(destination.parent)
    if source_stat.st_nlink > 1:
        hardlinks[hardlink_key] = relative_path.as_posix()
    source.unlink()
    recorder.completed(source_stat.st_size)


def stream_move(
    source: Path,
    destination: Path,
    state_file: Path,
    state_data: dict[str, Any],
    process_names: Iterable[str],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    expected_destination_device = destination.stat().st_dev
    migration_id = state_data["migration_id"]
    removed_partials = remove_own_partials(destination, migration_id)
    if removed_partials:
        print(f"Removed {removed_partials} incomplete temporary file(s) from an interrupted run")

    recorder = StateRecorder(state_file, state_data)
    real_directories: list[Path] = []
    last_process_check = 0.0

    for current, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        guard_destination_root(destination, expected_destination_device)
        if time.monotonic() - last_process_check >= 5:
            check_processes(process_names)
            last_process_check = time.monotonic()
        current_path = Path(current)
        real_directories.append(current_path)
        directory_names.sort()
        file_names.sort()

        for name in list(directory_names):
            item = current_path / name
            if item.is_symlink():
                relative = item.relative_to(source)
                copy_symlink(
                    item,
                    destination / relative,
                    destination,
                    expected_destination_device,
                )
                recorder.completed_symlink()
                directory_names.remove(name)

        for name in file_names:
            if time.monotonic() - last_process_check >= 5:
                check_processes(process_names)
                last_process_check = time.monotonic()
            item = current_path / name
            relative = item.relative_to(source)
            destination_item = destination / relative
            item_mode = item.lstat().st_mode
            if stat.S_ISLNK(item_mode):
                copy_symlink(
                    item,
                    destination_item,
                    destination,
                    expected_destination_device,
                )
                recorder.completed_symlink()
            elif stat.S_ISREG(item_mode):
                copy_regular_file(
                    item,
                    destination_item,
                    relative,
                    migration_id,
                    state_data,
                    recorder,
                    destination,
                    expected_destination_device,
                )
            else:
                raise MigrationError(f"Unsupported special file: {item}")

    recorder.flush()

    for source_directory in reversed(real_directories):
        guard_destination_root(destination, expected_destination_device)
        relative = source_directory.relative_to(source)
        destination_directory = destination / relative
        destination_directory.mkdir(parents=True, exist_ok=True)
        shutil.copystat(source_directory, destination_directory, follow_symlinks=False)
        if source_directory != source:
            source_directory.rmdir()

    source.rmdir()
    if state_data["link_mode"] == "symlink":
        source.symlink_to(destination, target_is_directory=True)
        fsync_directory(source.parent)

    final_stats = tree_stats(destination)
    expected = state_data["initial_stats"]
    comparable = ("files", "directories", "symlinks", "special", "bytes")
    differences = [key for key in comparable if final_stats[key] != expected[key]]
    if differences:
        raise MigrationError("Final tree statistics differ for: " + ", ".join(differences))

    state_data["status"] = "linked" if state_data["link_mode"] == "symlink" else "moved"
    state_data["final_stats"] = final_stats
    state_data["completed_at"] = int(time.time())
    recorder.flush()


def atomic_move(
    source: Path,
    destination: Path,
    state_file: Path,
    state_data: dict[str, Any],
) -> None:
    if destination.exists() or destination.is_symlink():
        raise MigrationError(f"Atomic destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    if state_data["link_mode"] == "symlink":
        source.symlink_to(destination, target_is_directory=True)
        fsync_directory(source.parent)
    state_data["status"] = "linked" if state_data["link_mode"] == "symlink" else "moved"
    state_data["final_stats"] = state_data["initial_stats"]
    state_data["completed_at"] = int(time.time())
    write_state(state_file, state_data)


def finalize_interrupted_move(
    source: Path,
    destination: Path,
    state_file: Path,
    state_data: dict[str, Any],
) -> None:
    if not destination.is_dir():
        raise MigrationError("Cannot finalize: destination directory is missing")
    final_stats = tree_stats(destination)
    expected = state_data["initial_stats"]
    comparable = ("files", "directories", "symlinks", "special", "bytes")
    differences = [key for key in comparable if final_stats[key] != expected[key]]
    if differences:
        raise MigrationError("Cannot finalize; destination differs for: " + ", ".join(differences))

    if state_data["link_mode"] == "symlink":
        if source.is_symlink():
            if not source_link_matches(source, destination):
                raise MigrationError("Existing source symlink points to another destination")
        elif source.exists():
            raise MigrationError("Cannot finalize because the source path still exists")
        else:
            source.symlink_to(destination, target_is_directory=True)
            fsync_directory(source.parent)
    elif source.exists() or source.is_symlink():
        raise MigrationError("Cannot finalize link-mode none because the source path still exists")

    state_data["status"] = "linked" if state_data["link_mode"] == "symlink" else "moved"
    state_data["final_stats"] = final_stats
    state_data["completed_at"] = int(time.time())
    state_data["updated_at"] = int(time.time())
    write_state(state_file, state_data)


def existing_parent_device(path: Path) -> int:
    return nearest_existing_parent(path).stat().st_dev


def command_audit(args: argparse.Namespace) -> int:
    source = normalized_path(args.source)
    destination = normalized_path(args.destination)
    validate_pair(source, destination)

    print(f"Source:      {source}")
    print(f"Destination: {destination}")
    if source.is_symlink():
        print(f"Source is already a symlink -> {os.readlink(source)}")
    elif source.is_dir():
        source_stats = tree_stats(source)
        print_stats("Source", source_stats)
    else:
        raise MigrationError(f"Source directory does not exist: {source}")

    if destination.is_dir():
        print_stats("Destination", tree_stats(destination))
    elif destination.exists() or destination.is_symlink():
        raise MigrationError(f"Destination exists but is not a directory: {destination}")
    else:
        print("Destination does not exist yet")

    info = disk_info(destination)
    print(
        "Destination volume: "
        f"{info.get('VolumeName', 'unknown')} "
        f"({filesystem_name(info)}, {info.get('DeviceIdentifier', 'unknown')})"
    )
    free = shutil.disk_usage(nearest_existing_parent(destination)).free
    print(f"Destination free space: {human_bytes(free)}")
    return 0


def command_move(args: argparse.Namespace) -> int:
    source = normalized_path(args.source)
    destination = normalized_path(args.destination)
    validate_pair(source, destination)
    check_processes(args.process_name)

    state_file = state_path_for(destination, args.state_file)
    state_data = read_state(state_file)
    destination_info: dict[str, Any] | None = None
    if state_data:
        check_state_paths(state_data, source, destination)
        destination_info = ensure_apfs(destination, args.allow_non_apfs)
        recorded_uuid = str(state_data.get("destination_volume_uuid") or "")
        current_uuid = str(destination_info.get("VolumeUUID") or "")
        if recorded_uuid and current_uuid and recorded_uuid != current_uuid:
            raise MigrationError("The destination path is mounted from a different volume than the journal")

    if source_link_matches(source, destination):
        if state_data and state_data.get("status") not in {"linked", "moved"}:
            if not args.execute:
                print("Data is complete and linked; --execute would repair the journal status")
                return 0
            finalize_interrupted_move(source, destination, state_file, state_data)
        print("Migration is already complete; source symlink points to destination")
        return 0
    if source.is_symlink():
        raise MigrationError(f"Source is a symlink to another target: {source} -> {os.readlink(source)}")
    if not source.exists() and state_data and state_data.get("status") == "moving":
        if not args.execute:
            print("Destination is complete; --execute would recreate the source link and finalize the journal")
            return 0
        finalize_interrupted_move(source, destination, state_file, state_data)
        print("Finalized an interrupted migration after all data had moved")
        return 0
    if not source.is_dir():
        raise MigrationError(f"Source directory does not exist: {source}")
    if not destination.parent.is_dir():
        raise MigrationError(
            "Destination parent must already exist on the intended volume; create and verify it first"
        )
    if destination.is_symlink():
        raise MigrationError("Destination must not be a symlink")
    if destination.exists() and not destination.is_dir():
        raise MigrationError("Destination exists but is not a directory")

    if destination_info is None:
        destination_info = ensure_apfs(destination, args.allow_non_apfs)
    if state_data:
        if state_data.get("status") in {"linked", "moved"}:
            print(f"Migration journal already reports {state_data['status']}")
            return 0
        initial_stats = state_data["initial_stats"]
    else:
        if destination.exists() and any(destination.iterdir()):
            raise MigrationError("Destination is not empty and no matching migration journal exists")
        initial_stats = tree_stats(source)
        if initial_stats["special"]:
            raise MigrationError("Source contains sockets, devices, or other unsupported special files")

    source_device = source.stat().st_dev
    destination_device = existing_parent_device(destination)
    strategy = args.strategy
    if strategy == "auto":
        strategy = "atomic" if source_device == destination_device else "stream"
    if strategy == "atomic" and source_device != destination_device:
        raise MigrationError("Atomic move requires source and destination on the same filesystem")

    print(f"Strategy: {strategy}")
    print_stats("Initial source", initial_stats)
    print(f"Destination filesystem: {filesystem_name(destination_info)}")
    if strategy == "stream":
        peak_extra = initial_stats["largest_file"] + 16 * 1024 * 1024
        print(f"Bounded temporary overhead: approximately {human_bytes(peak_extra)} or less")
        free = shutil.disk_usage(nearest_existing_parent(destination)).free
        remaining_stats = tree_stats(source)
        required_destination_space = remaining_stats.get("unique_bytes", remaining_stats["bytes"])
        if free < required_destination_space:
            raise MigrationError(
                f"Destination needs about {human_bytes(required_destination_space)} free; "
                f"only {human_bytes(free)} is available"
            )

    if not args.execute:
        print("Dry run only. Re-run with --execute after reviewing the exact paths and process list.")
        if strategy == "stream":
            print(f"Streaming mode also requires --confirm {CONFIRM_PHRASE}")
        return 0
    if strategy == "stream" and args.confirm != CONFIRM_PHRASE:
        raise MigrationError(f"Streaming mode requires --confirm {CONFIRM_PHRASE}")

    if state_data is None:
        state_data = {
            "schema_version": SCHEMA_VERSION,
            "migration_id": uuid.uuid4().hex[:16],
            "source": str(source),
            "destination": str(destination),
            "strategy": strategy,
            "link_mode": args.link_mode,
            "status": "moving",
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "initial_stats": initial_stats,
            "progress": {"files": 0, "symlinks": 0, "bytes": 0},
            "hardlinks": {},
            "per_file_sha256": strategy == "stream",
            "destination_volume_uuid": str(destination_info.get("VolumeUUID") or ""),
        }
        write_state(state_file, state_data)
    elif state_data.get("strategy") != strategy or state_data.get("link_mode") != args.link_mode:
        raise MigrationError("Resume must use the strategy and link mode recorded in the journal")

    print(f"Journal: {state_file}")
    if strategy == "atomic":
        atomic_move(source, destination, state_file, state_data)
    else:
        stream_move(source, destination, state_file, state_data, args.process_name)
    print("Migration completed")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    source = normalized_path(args.source)
    destination = normalized_path(args.destination)
    validate_pair(source, destination)
    state_file = state_path_for(destination, args.state_file)
    state_data = read_state(state_file)
    if not state_data:
        raise MigrationError(f"Migration journal not found: {state_file}")
    check_state_paths(state_data, source, destination)
    if state_data.get("status") not in {"linked", "moved"}:
        raise MigrationError(f"Migration is not complete; journal status is {state_data.get('status')}")
    if not destination.is_dir():
        raise MigrationError(f"Destination directory is missing: {destination}")

    actual = tree_stats(destination)
    expected = state_data["initial_stats"]
    comparable = ("files", "directories", "symlinks", "special", "bytes")
    differences = [key for key in comparable if actual[key] != expected[key]]
    if differences:
        raise MigrationError("Verification failed for: " + ", ".join(differences))
    if state_data["link_mode"] == "symlink" and not source_link_matches(source, destination):
        raise MigrationError("Source symlink does not point to destination")
    if state_data["link_mode"] == "none" and source.exists():
        raise MigrationError("Source still exists even though link mode is none")

    partial_prefix = f"{PARTIAL_PREFIX}{state_data['migration_id']}-"
    partials = [
        Path(current) / name
        for current, _, files in os.walk(destination)
        for name in files
        if name.startswith(partial_prefix) and name.endswith(".partial")
    ]
    if partials:
        raise MigrationError(f"Found {len(partials)} incomplete temporary file(s)")

    print_stats("Verified destination", actual)
    print(f"Journal status: {state_data['status']}")
    print(f"Per-file SHA-256 verification: {state_data.get('per_file_sha256', False)}")
    print("Verification passed")
    return 0


def command_restore(args: argparse.Namespace) -> int:
    original = normalized_path(args.source_link)
    data = normalized_path(args.data)
    validate_pair(original, data)
    check_processes(args.process_name)

    reverse_state_file = state_path_for(original, None)
    reverse_state = read_state(reverse_state_file)
    if reverse_state:
        check_state_paths(reverse_state, data, original)
        if reverse_state.get("status") == "moved" and original.is_dir() and not data.exists():
            print("Data is already restored to the original directory")
            return 0

    linked = source_link_matches(original, data)
    if not linked and not reverse_state:
        raise MigrationError("Original path is not a symlink to the specified migrated data")
    if data.exists() and not data.is_dir():
        raise MigrationError(f"Migrated data is not a directory: {data}")
    if not data.exists() and not reverse_state:
        raise MigrationError(f"Migrated data is missing: {data}")
    if not original.parent.is_dir():
        raise MigrationError("Original parent directory is missing")

    destination_info = disk_info(original.parent)
    if "apfs" not in filesystem_name(destination_info).lower() and not args.allow_non_apfs:
        raise MigrationError("Original destination is not APFS; review metadata risks before restoring")

    if data.is_dir():
        remaining_stats = tree_stats(data)
        print_stats("Data to restore", remaining_stats)
        required = remaining_stats.get("unique_bytes", remaining_stats["bytes"])
        available = shutil.disk_usage(original.parent).free
        print(f"Original volume free space: {human_bytes(available)}")
        if available < required:
            raise MigrationError(
                f"Original volume needs about {human_bytes(required)} free; only {human_bytes(available)} is available"
            )
    print(f"Restore from: {data}")
    print(f"Restore to:   {original}")

    if not args.execute:
        print(f"Dry run only. Re-run with --execute --confirm {RESTORE_CONFIRM_PHRASE}")
        return 0
    if args.confirm != RESTORE_CONFIRM_PHRASE:
        raise MigrationError(f"Restore requires --confirm {RESTORE_CONFIRM_PHRASE}")

    removed_link = False
    if linked:
        original.unlink()
        fsync_directory(original.parent)
        removed_link = True

    move_args = argparse.Namespace(
        source=str(data),
        destination=str(original),
        strategy="auto",
        link_mode="none",
        process_name=args.process_name,
        state_file=None,
        allow_non_apfs=args.allow_non_apfs,
        execute=True,
        confirm=CONFIRM_PHRASE,
    )
    try:
        result = command_move(move_args)
    except Exception:
        if removed_link and not reverse_state_file.exists() and not original.exists():
            original.symlink_to(data, target_is_directory=True)
            fsync_directory(original.parent)
        raise
    print("Restore completed")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate a macOS app-data directory with bounded temporary disk usage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_paths(target: argparse.ArgumentParser) -> None:
        target.add_argument("--source", required=True, help="Exact current app-data directory")
        target.add_argument("--destination", required=True, help="Exact new data directory")

    audit = subparsers.add_parser("audit", help="Read-only path, size, and filesystem audit")
    add_paths(audit)
    audit.set_defaults(handler=command_audit)

    move = subparsers.add_parser("move", help="Plan or execute a resumable migration")
    add_paths(move)
    move.add_argument("--strategy", choices=("auto", "atomic", "stream"), default="auto")
    move.add_argument("--link-mode", choices=("symlink", "none"), default="symlink")
    move.add_argument("--process-name", action="append", default=[], help="Exact process name that must be stopped")
    move.add_argument("--state-file", help="Optional journal path")
    move.add_argument("--allow-non-apfs", action="store_true", help="Allow a destination that may lose macOS metadata")
    move.add_argument("--execute", action="store_true", help="Perform the migration")
    move.add_argument("--confirm", help=f"Required phrase for streaming mode: {CONFIRM_PHRASE}")
    move.set_defaults(handler=command_move)

    verify = subparsers.add_parser("verify", help="Verify final tree and source link against the journal")
    add_paths(verify)
    verify.add_argument("--state-file", help="Optional journal path")
    verify.set_defaults(handler=command_verify)

    restore = subparsers.add_parser(
        "restore",
        help="Move migrated data back to the original path with the same bounded-space algorithm",
    )
    restore.add_argument("--source-link", required=True, help="Original path currently linked to migrated data")
    restore.add_argument("--data", required=True, help="Current migrated data directory")
    restore.add_argument("--process-name", action="append", default=[], help="Exact process name that must be stopped")
    restore.add_argument("--allow-non-apfs", action="store_true")
    restore.add_argument("--execute", action="store_true")
    restore.add_argument("--confirm", help=f"Required phrase: {RESTORE_CONFIRM_PHRASE}")
    restore.set_defaults(handler=command_restore)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except MigrationError as error:
        eprint(f"error: {error}")
        return 2
    except KeyboardInterrupt:
        eprint("Interrupted. Re-run the same command to resume from the journal.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
