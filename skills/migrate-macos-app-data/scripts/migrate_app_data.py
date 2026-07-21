#!/usr/bin/python3
"""Copy and verify one macOS app or app-data directory without deleting its source.

All migration payload, journal, partial-copy, and tool-temporary writes are placed
beside the destination.  The source is read-only.  Removing or renaming the
internal copy is deliberately handed back to the user in Finder.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = 3
STATE_SUFFIX = ".migrate-macos-app-data.json"
COPY_OVERHEAD_BYTES = 64 * 1024 * 1024
PROCESS_CHECK_INTERVAL = 5.0
CHUNK_SIZE = 8 * 1024 * 1024
XATTR_NOFOLLOW = 0x0001
ACL_TYPE_EXTENDED = 0x00000100


# Apple's bundled Python does not expose Darwin xattr or ACL APIs through os.
# Call libc directly so metadata handling stays dependency-free and fail-closed.
LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
LIBC.listxattr.restype = ctypes.c_ssize_t
LIBC.getxattr.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
]
LIBC.getxattr.restype = ctypes.c_ssize_t
LIBC.setxattr.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
]
LIBC.setxattr.restype = ctypes.c_int
LIBC.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
LIBC.acl_get_file.restype = ctypes.c_void_p
LIBC.acl_get_link_np.argtypes = [ctypes.c_char_p, ctypes.c_int]
LIBC.acl_get_link_np.restype = ctypes.c_void_p
LIBC.acl_set_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
LIBC.acl_set_file.restype = ctypes.c_int
LIBC.acl_set_link_np.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
LIBC.acl_set_link_np.restype = ctypes.c_int
LIBC.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
LIBC.acl_to_text.restype = ctypes.c_void_p
LIBC.acl_free.argtypes = [ctypes.c_void_p]
LIBC.acl_free.restype = ctypes.c_int


class MigrationError(RuntimeError):
    """A safe, expected refusal or validation failure."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def lexical_absolute(value: str) -> Path:
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        raise MigrationError(f"Path must be absolute / 路径必须为绝对路径: {value}")
    return Path(os.path.abspath(expanded))


def lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_scoped_source(path: Path) -> None:
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
        home / "Library" / "Group Containers",
    }
    if path in forbidden:
        raise MigrationError(f"Refusing broad source path / 拒绝宽泛源路径: {path}")

    for protected_root in (Path("/System"), Path("/Library"), Path("/usr"), Path("/bin"), Path("/sbin")):
        if is_within(path, protected_root):
            raise MigrationError(
                f"Refusing protected or administrator-owned source / 拒绝受保护或需要管理员权限的源路径: {path}"
            )

    container_roots = (
        home / "Library" / "Containers",
        home / "Library" / "Group Containers",
    )
    if any(path.parent == container_root for container_root in container_roots):
        raise MigrationError(
            f"Refusing an entire app container; choose one relocatable payload / "
            f"拒绝迁移整个程序容器，请选择单个可迁移的大型目录: {path}"
        )

    app_components = [index for index, part in enumerate(path.parts) if part.lower().endswith(".app")]
    if app_components and app_components[-1] != len(path.parts) - 1:
        raise MigrationError(
            f"Refusing a component inside a signed app bundle / 拒绝单独迁移签名应用包内部组件: {path}"
        )

    parts = path.parts
    is_application_bundle = (
        len(parts) == 3
        and parts[0] == "/"
        and parts[1] == "Applications"
        and path.suffix.lower() == ".app"
    )
    if not is_application_bundle and len(parts) < 4:
        raise MigrationError(f"Refusing broad source path / 拒绝宽泛源路径: {path}")


def validate_source_and_destination(source: Path, destination: Path) -> None:
    validate_scoped_source(source)
    if source == destination:
        raise MigrationError("Source and destination are identical / 源与目标路径相同")

    # Keep the lexical source location when it is already a symlink. This lets
    # audit/link inspect an existing integration link without treating its
    # resolved destination as a recursively nested source.
    source_real = source if source.is_symlink() else source.resolve(strict=False)
    destination_real = destination.parent.resolve(strict=False) / destination.name
    if is_within(destination_real, source_real):
        raise MigrationError("Destination is inside source / 目标位于源目录内部")
    if is_within(source_real, destination_real):
        raise MigrationError("Source is inside destination / 源目录位于目标内部")
    if destination == Path("/") or len(destination.parts) < 4:
        raise MigrationError(f"Refusing broad destination path / 拒绝宽泛目标路径: {destination}")


def nearest_existing(path: Path) -> Path:
    candidate = path
    while not lexists(candidate):
        if candidate == candidate.parent:
            raise MigrationError(f"No existing ancestor for path / 路径没有已存在的上级目录: {path}")
        candidate = candidate.parent
    if candidate.is_symlink():
        candidate = candidate.resolve(strict=True)
    return candidate


def disk_info(path: Path) -> Dict[str, Any]:
    existing = nearest_existing(path)
    info: Dict[str, Any] = {
        "query_path": str(existing),
        "device": None,
        "filesystem": None,
        "volume_uuid": None,
        "mount_point": None,
        "internal": None,
        "free_bytes": shutil.disk_usage(str(existing)).free,
        "st_dev": existing.stat().st_dev,
    }

    try:
        df_result = subprocess.run(
            ["/bin/df", "-P", str(existing)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        fields = df_result.stdout.strip().splitlines()[-1].split()
        if fields:
            info["device"] = fields[0]
        if len(fields) >= 6:
            info["mount_point"] = " ".join(fields[5:])
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass

    diskutil = Path("/usr/sbin/diskutil")
    if diskutil.exists():
        try:
            disk_query = str(info.get("device") or existing)
            result = subprocess.run(
                [str(diskutil), "info", "-plist", disk_query],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            payload = plistlib.loads(result.stdout)
            info["filesystem"] = payload.get("FilesystemType") or payload.get("Type (Bundle)")
            info["volume_uuid"] = payload.get("VolumeUUID") or payload.get("APFSVolumeUUID")
            info["mount_point"] = payload.get("MountPoint") or info["mount_point"]
            if "Internal" in payload:
                info["internal"] = bool(payload["Internal"])
            info["device"] = payload.get("DeviceNode") or info["device"]
        except (OSError, subprocess.CalledProcessError, plistlib.InvalidFileException):
            pass

    if info["filesystem"] is None:
        info["filesystem"] = "unknown"
    return info


def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.2f} {unit}"
        number /= 1024
    return f"{value} B"


def iter_tree(root: Path) -> Iterable[Tuple[str, Path, os.stat_result]]:
    """Yield root and descendants without following symbolic links."""
    stack: List[Tuple[str, Path]] = [(".", root)]
    while stack:
        relative, path = stack.pop()
        metadata = path.lstat()
        yield relative, path, metadata
        if stat.S_ISDIR(metadata.st_mode):
            children = sorted(os.scandir(str(path)), key=lambda entry: entry.name, reverse=True)
            for entry in children:
                child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
                stack.append((child_relative, Path(entry.path)))


def tree_stats(root: Path) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "files": 0,
        "directories": 0,
        "symlinks": 0,
        "special": 0,
        "logical_bytes": 0,
        "unique_bytes": 0,
        "largest_file": 0,
    }
    seen_inodes = set()
    for relative, _path, metadata in iter_tree(root):
        if stat.S_ISDIR(metadata.st_mode):
            if relative != ".":
                stats["directories"] += 1
        elif stat.S_ISREG(metadata.st_mode):
            stats["files"] += 1
            stats["logical_bytes"] += metadata.st_size
            stats["largest_file"] = max(stats["largest_file"], metadata.st_size)
            inode_key = (metadata.st_dev, metadata.st_ino)
            if inode_key not in seen_inodes:
                seen_inodes.add(inode_key)
                stats["unique_bytes"] += metadata.st_size
        elif stat.S_ISLNK(metadata.st_mode):
            stats["symlinks"] += 1
        else:
            stats["special"] += 1
    return stats


def metadata_signature(metadata: os.stat_result) -> Dict[str, Any]:
    return {
        "type": file_type(metadata.st_mode),
        "size": metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0,
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "mtime_ns": metadata.st_mtime_ns,
        "flags": getattr(metadata, "st_flags", 0),
        "inode": metadata.st_ino,
        "device": metadata.st_dev,
        "nlink": metadata.st_nlink,
    }


def source_snapshot(root: Path) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for relative, path, metadata in iter_tree(root):
        record = metadata_signature(metadata)
        if stat.S_ISLNK(metadata.st_mode):
            record["link_target"] = os.readlink(str(path))
        snapshot[relative] = record
    return snapshot


def file_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def state_path_for(destination: Path) -> Path:
    return destination.parent / f".{destination.name}{STATE_SUFFIX}"


def validated_migration_id(state: Dict[str, Any]) -> str:
    migration_id = state.get("migration_id")
    if (
        not isinstance(migration_id, str)
        or len(migration_id) != 32
        or any(character not in "0123456789abcdef" for character in migration_id)
    ):
        raise MigrationError("Migration journal ID is invalid / 迁移日志 ID 无效")
    return migration_id


def write_state(path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    migration_id = validated_migration_id(state)
    write_nonce = uuid.uuid4().hex
    temporary = path.parent / f".{path.name}.{migration_id}.{write_nonce}.tmp"
    persistent_state = {
        key: value for key, value in state.items() if not key.startswith("_runtime_")
    }
    encoded = (json.dumps(persistent_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(str(temporary), flags, 0o600)
    except OSError as error:
        raise MigrationError(
            f"Cannot safely create migration journal temporary / 无法安全创建迁移日志临时文件: {temporary}: {error}"
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.replace(str(temporary), str(path))
    fsync_directory(path.parent)


def checkpoint_state(path: Path, state: Dict[str, Any], force: bool = False) -> None:
    now = time.monotonic()
    previous = float(state.get("_runtime_last_checkpoint", 0.0))
    if force or now - previous >= PROCESS_CHECK_INTERVAL:
        write_state(path, state)
        state["_runtime_last_checkpoint"] = now


def load_state(destination: Path, required: bool = True) -> Optional[Dict[str, Any]]:
    state_path = state_path_for(destination)
    if state_path.is_symlink() or not state_path.is_file():
        if required:
            raise MigrationError(f"Migration journal not found / 未找到迁移日志: {state_path}")
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"Cannot read migration journal / 无法读取迁移日志: {error}") from error
    if state.get("schema_version") != SCHEMA_VERSION:
        raise MigrationError("Unsupported migration journal version / 不支持的迁移日志版本")
    validated_migration_id(state)
    return state


def validate_state(state: Dict[str, Any], source: Path, destination: Path, kind: Optional[str] = None) -> None:
    if state.get("source") != str(source) or state.get("destination") != str(destination):
        raise MigrationError("Migration journal paths do not match / 迁移日志路径不匹配")
    state_kind = state.get("kind")
    if state_kind not in {"app", "data"}:
        raise MigrationError("Migration journal kind is invalid / 迁移日志类型无效")
    if source.suffix.lower() == ".app" and state_kind != "app":
        raise MigrationError("An app bundle cannot use data migration rules / 应用包不能使用数据迁移规则")
    if source.is_dir() and not source.is_symlink() and detect_source_kind(source) != state_kind:
        raise MigrationError("Migration kind does not match the source / 迁移类型与源路径不匹配")
    if kind is not None and state.get("kind") != kind:
        raise MigrationError("Migration kind does not match journal / 迁移类型与日志不匹配")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_source_directory(source: Path) -> None:
    if source.is_symlink():
        raise MigrationError(f"Source is already a symbolic link / 源路径已是软链接: {source}")
    if not source.is_dir():
        raise MigrationError(f"Source directory not found / 找不到源目录: {source}")


def detect_source_kind(source: Path) -> str:
    if source.suffix.lower() == ".app" and (source / "Contents" / "Info.plist").is_file():
        return "app"
    return "data"


def resolve_kind(source: Path, requested: str) -> str:
    detected = detect_source_kind(source)
    if source.suffix.lower() == ".app" and detected != "app":
        raise MigrationError(
            f"Path has an .app suffix but is not a valid app bundle / 路径以 .app 结尾但不是有效应用包: {source}"
        )
    if requested != "auto" and requested != detected:
        raise MigrationError(
            f"Requested kind {requested} conflicts with detected kind {detected} / "
            f"请求类型 {requested} 与检测类型 {detected} 冲突"
        )
    return detected


def process_is_running(name: str) -> bool:
    result = subprocess.run(
        ["/usr/bin/pgrep", "-x", name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def require_processes_stopped(names: List[str]) -> None:
    running = [name for name in names if process_is_running(name)]
    if running:
        raise MigrationError(
            "Quit these processes before continuing / 请先完全退出这些进程: " + ", ".join(running)
        )


class DestinationGuard:
    def __init__(self, parent: Path, volume: Dict[str, Any], process_names: List[str]) -> None:
        self.parent = parent
        self.expected_device = parent.stat().st_dev
        self.expected_uuid = volume.get("volume_uuid")
        self.process_names = process_names
        self.last_slow_check = 0.0

    def check(self, force_slow: bool = False) -> None:
        if not self.parent.is_dir() or self.parent.is_symlink():
            raise MigrationError("Destination volume disappeared / 目标宗卷已断开")
        if self.parent.stat().st_dev != self.expected_device:
            raise MigrationError("Destination device changed / 目标设备已变化，立即停止")
        now = time.monotonic()
        if force_slow or now - self.last_slow_check >= PROCESS_CHECK_INTERVAL:
            require_processes_stopped(self.process_names)
            current = disk_info(self.parent)
            if self.expected_uuid and current.get("volume_uuid") != self.expected_uuid:
                raise MigrationError("Destination volume UUID changed / 目标宗卷 UUID 已变化")
            self.last_slow_check = now


def require_destination_policy(destination: Path) -> Dict[str, Any]:
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise MigrationError(
            "Destination parent must already exist and must not be a symlink / "
            f"目标上级目录必须已存在且不能是软链接: {parent}"
        )
    if parent.resolve(strict=True) != parent:
        raise MigrationError(
            f"Destination parent must use its canonical path / 目标上级目录必须使用真实路径而非别名: {parent}"
        )
    info = disk_info(parent)
    if info.get("internal") is not False:
        raise MigrationError(
            "Destination is not confirmed as an external volume / 未确认目标为外接宗卷"
        )
    filesystem = str(info.get("filesystem") or "").lower()
    if filesystem != "apfs":
        raise MigrationError(
            f"Destination filesystem is {filesystem or 'unknown'}, not APFS / 目标文件系统不是 APFS"
        )
    if not info.get("volume_uuid"):
        raise MigrationError("External APFS volume UUID is unavailable / 无法读取外接 APFS 宗卷 UUID")
    return info


def print_audit(source: Path, destination: Path, kind: str, stats: Dict[str, Any], info: Dict[str, Any]) -> None:
    print("Read-only audit / 只读审计")
    print(f"  Source / 源: {source}")
    print(f"  Destination / 目标: {destination}")
    print(f"  Kind / 类型: {kind}")
    print(f"  Files / 文件: {stats['files']}")
    print(f"  Directories / 目录: {stats['directories']}")
    print(f"  Symlinks / 软链接: {stats['symlinks']}")
    print(f"  Logical size / 逻辑大小: {format_bytes(stats['logical_bytes'])}")
    print(f"  Unique payload / 去重后数据: {format_bytes(stats['unique_bytes'])}")
    print(f"  Largest file / 最大文件: {format_bytes(stats['largest_file'])}")
    print(f"  Destination free / 目标可用: {format_bytes(int(info['free_bytes']))}")
    print(f"  Filesystem / 文件系统: {info.get('filesystem') or 'unknown'}")
    print(f"  External / 外接: {info.get('internal') is False}")
    print(f"  Mount point / 挂载点: {info.get('mount_point') or 'unknown'}")
    print("  Source mutation / 源路径改动: none / 无")


def command_audit(arguments: argparse.Namespace) -> None:
    source = lexical_absolute(arguments.source)
    destination = lexical_absolute(arguments.destination)
    validate_source_and_destination(source, destination)

    if source.is_symlink():
        print("Read-only audit / 只读审计")
        print(f"  Source / 源: {source}")
        print(f"  Existing symlink target / 现有软链接目标: {os.readlink(str(source))}")
        return
    require_source_directory(source)
    kind = resolve_kind(source, arguments.kind)
    stats = tree_stats(source)
    info = disk_info(destination.parent)
    print_audit(source, destination, kind, stats, info)
    if stats["special"]:
        raise MigrationError("Source contains special files / 源目录包含不支持的特殊文件")


def make_initial_state(
    source: Path,
    destination: Path,
    kind: str,
    process_names: List[str],
    source_info: Dict[str, Any],
    destination_info: Dict[str, Any],
    stats: Dict[str, Any],
    snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "migration_id": uuid.uuid4().hex,
        "source": str(source),
        "destination": str(destination),
        "kind": kind,
        "process_names": sorted(set(process_names)),
        "status": "copying",
        "created_at": time.time(),
        "updated_at": time.time(),
        "source_volume_uuid": source_info.get("volume_uuid"),
        "destination_volume_uuid": destination_info.get("volume_uuid"),
        "destination_device": destination_info.get("device"),
        "destination_st_dev": destination_info.get("st_dev"),
        "initial_stats": stats,
        "source_snapshot": snapshot,
        "progress": {"files": 0, "symlinks": 0, "bytes": 0},
        "hardlinks": {},
        "file_sha256": {},
        "source_deleted_by_tool": False,
    }


def require_journal_destination(destination: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    current = disk_info(destination)
    if current.get("internal") is not False:
        raise MigrationError(
            "Verified external destination is no longer mounted / 已校验的外接目标当前未挂载"
        )
    if str(current.get("filesystem") or "").lower() != "apfs":
        raise MigrationError("Destination is no longer external APFS / 目标已不是外接 APFS")
    expected_uuid = state.get("destination_volume_uuid")
    if expected_uuid:
        if current.get("volume_uuid") != expected_uuid:
            raise MigrationError("Destination volume UUID differs from journal / 目标宗卷 UUID 与日志不一致")
    elif current.get("st_dev") != state.get("destination_st_dev"):
        raise MigrationError("Destination device differs from journal / 目标设备与日志不一致")
    return current


def assert_snapshot_entry(relative: str, path: Path, expected: Dict[str, Any]) -> os.stat_result:
    if not lexists(path):
        raise MigrationError(f"Source changed during copy / 复制期间源路径发生变化: {relative}")
    current = path.lstat()
    actual = metadata_signature(current)
    keys = ("type", "size", "mode", "uid", "gid", "mtime_ns", "flags", "inode", "device", "nlink")
    if any(actual.get(key) != expected.get(key) for key in keys):
        raise MigrationError(f"Source changed during copy / 复制期间源路径发生变化: {relative}")
    if actual["type"] == "symlink" and os.readlink(str(path)) != expected.get("link_target"):
        raise MigrationError(f"Source symlink changed during copy / 复制期间源软链接发生变化: {relative}")
    return current


def xattr_error(action: str, path: Path, name: Optional[bytes] = None) -> MigrationError:
    error_number = ctypes.get_errno()
    detail = os.strerror(error_number)
    chinese_action = {"list": "列出", "read": "读取", "write": "写入"}.get(action, action)
    attribute = ""
    if name is not None:
        attribute = f" {name.decode('utf-8', errors='backslashreplace')}"
    return MigrationError(
        f"Unable to {action} extended attribute / 无法{chinese_action}扩展属性"
        f"{attribute}: {path}: [{error_number}] {detail}"
    )


def list_xattr_names(path: Path, follow_symlinks: bool) -> List[bytes]:
    encoded_path = os.fsencode(path)
    options = 0 if follow_symlinks else XATTR_NOFOLLOW
    for _attempt in range(3):
        ctypes.set_errno(0)
        required = LIBC.listxattr(encoded_path, None, 0, options)
        if required < 0:
            raise xattr_error("list", path)
        if required == 0:
            return []
        buffer = ctypes.create_string_buffer(required)
        ctypes.set_errno(0)
        actual = LIBC.listxattr(encoded_path, buffer, required, options)
        if actual >= 0:
            payload = buffer.raw[:actual]
            if payload and not payload.endswith(b"\0"):
                raise MigrationError(f"Malformed extended-attribute list / 扩展属性列表格式错误: {path}")
            return sorted(name for name in payload.split(b"\0") if name)
        if ctypes.get_errno() != errno.ERANGE:
            raise xattr_error("list", path)
    raise MigrationError(f"Extended attributes changed repeatedly / 扩展属性反复变化: {path}")


def read_xattr(path: Path, name: bytes, follow_symlinks: bool) -> bytes:
    encoded_path = os.fsencode(path)
    options = 0 if follow_symlinks else XATTR_NOFOLLOW
    for _attempt in range(3):
        ctypes.set_errno(0)
        required = LIBC.getxattr(encoded_path, name, None, 0, 0, options)
        if required < 0:
            raise xattr_error("read", path, name)
        if required == 0:
            return b""
        buffer = ctypes.create_string_buffer(required)
        ctypes.set_errno(0)
        actual = LIBC.getxattr(encoded_path, name, buffer, required, 0, options)
        if actual >= 0:
            return buffer.raw[:actual]
        if ctypes.get_errno() != errno.ERANGE:
            raise xattr_error("read", path, name)
    raise MigrationError(f"Extended attribute changed repeatedly / 扩展属性反复变化: {path}")


def write_xattr(path: Path, name: bytes, value: bytes, follow_symlinks: bool) -> None:
    encoded_path = os.fsencode(path)
    options = 0 if follow_symlinks else XATTR_NOFOLLOW
    buffer = ctypes.create_string_buffer(value, len(value)) if value else None
    pointer = ctypes.cast(buffer, ctypes.c_void_p) if buffer is not None else None
    ctypes.set_errno(0)
    result = LIBC.setxattr(encoded_path, name, pointer, len(value), 0, options)
    if result != 0:
        raise xattr_error("write", path, name)


def copy_xattrs(source: Path, destination: Path, follow_symlinks: bool) -> None:
    for name in list_xattr_names(source, follow_symlinks):
        value = read_xattr(source, name, follow_symlinks)
        write_xattr(destination, name, value, follow_symlinks)


def acl_error(action: str, path: Path) -> MigrationError:
    error_number = ctypes.get_errno()
    chinese_action = {"read": "读取", "serialize": "序列化", "write": "写入"}.get(action, action)
    return MigrationError(
        f"Unable to {action} ACL / 无法{chinese_action} ACL: {path}: "
        f"[{error_number}] {os.strerror(error_number)}"
    )


def get_acl(path: Path, follow_symlinks: bool) -> Optional[int]:
    ctypes.set_errno(0)
    getter = LIBC.acl_get_file if follow_symlinks else LIBC.acl_get_link_np
    acl = getter(os.fsencode(path), ACL_TYPE_EXTENDED)
    if not acl:
        error_number = ctypes.get_errno()
        if error_number == errno.ENOENT and lexists(path):
            return None
        raise acl_error("read", path)
    return acl


def acl_text_from_pointer(acl: int, path: Path) -> str:
    text_pointer: Optional[int] = None
    try:
        length = ctypes.c_ssize_t()
        ctypes.set_errno(0)
        text_pointer = LIBC.acl_to_text(acl, ctypes.byref(length))
        if not text_pointer:
            raise acl_error("serialize", path)
        return ctypes.string_at(text_pointer, length.value).decode("utf-8")
    finally:
        if text_pointer:
            LIBC.acl_free(text_pointer)


def acl_text(path: Path) -> str:
    acl = get_acl(path, follow_symlinks=not path.is_symlink())
    if acl is None:
        return ""
    try:
        return acl_text_from_pointer(acl, path)
    finally:
        LIBC.acl_free(acl)


def copy_acl(source: Path, destination: Path, follow_symlinks: bool) -> None:
    acl = get_acl(source, follow_symlinks)
    if acl is None:
        return
    try:
        if not acl_text_from_pointer(acl, source):
            return
        ctypes.set_errno(0)
        setter = LIBC.acl_set_file if follow_symlinks else LIBC.acl_set_link_np
        result = setter(os.fsencode(destination), ACL_TYPE_EXTENDED, acl)
        if result != 0:
            raise acl_error("write", destination)
    finally:
        LIBC.acl_free(acl)


def copy_directory_metadata(source: Path, destination: Path) -> None:
    shutil.copystat(str(source), str(destination), follow_symlinks=False)
    copy_xattrs(source, destination, follow_symlinks=False)
    copy_acl(source, destination, follow_symlinks=True)


def copy_symlink_metadata(source: Path, destination: Path) -> None:
    copy_xattrs(source, destination, follow_symlinks=False)
    try:
        shutil.copystat(str(source), str(destination), follow_symlinks=False)
    except (NotImplementedError, OSError):
        pass
    copy_acl(source, destination, follow_symlinks=False)


def partial_path(destination_file: Path, migration_id: str) -> Path:
    return destination_file.parent / f".{destination_file.name}.{migration_id}.partial"


def prepare_owned_partial(path: Path, destination: Path, migration_id: str) -> None:
    expected_suffix = f".{migration_id}.partial"
    if not path.name.endswith(expected_suffix) or not is_within(path, destination):
        raise MigrationError(f"Refusing to rewrite unowned artifact / 拒绝改写非本工具临时文件: {path}")
    if lexists(path):
        if path.is_symlink() or not path.is_file():
            raise MigrationError(f"Owned partial is no longer a regular file / 临时文件已不是普通文件: {path}")
        descriptor = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def ensure_parent_directories(
    relative: str,
    source: Path,
    destination: Path,
    snapshot: Dict[str, Dict[str, Any]],
    guard: DestinationGuard,
) -> None:
    relative_path = Path(relative)
    current = Path()
    for part in relative_path.parts[:-1]:
        current = current / part
        current_text = current.as_posix()
        expected = snapshot.get(current_text)
        if not expected or expected.get("type") != "directory":
            raise MigrationError(f"Invalid source snapshot parent / 源快照上级目录无效: {current_text}")
        source_dir = source / current
        destination_dir = destination / current
        assert_snapshot_entry(current_text, source_dir, expected)
        guard.check()
        if lexists(destination_dir):
            if destination_dir.is_symlink() or not destination_dir.is_dir():
                raise MigrationError(f"Destination entry type mismatch / 目标条目类型不匹配: {destination_dir}")
        else:
            destination_dir.mkdir(mode=0o700)


def destination_file_matches(source_file: Path, destination_file: Path, expected_hash: Optional[str]) -> Tuple[bool, str]:
    if not destination_file.is_file() or destination_file.is_symlink():
        return False, ""
    if source_file.stat().st_size != destination_file.stat().st_size:
        return False, ""
    source_hash = expected_hash or sha256_file(source_file)
    return sha256_file(destination_file) == source_hash, source_hash


def ditto_copy_file(source: Path, partial: Path, work_root: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "TMPDIR": str(work_root),
            "TMP": str(work_root),
            "TEMP": str(work_root),
            "XDG_CACHE_HOME": str(work_root),
        }
    )
    result = subprocess.run(
        ["/usr/bin/ditto", "--rsrc", "--extattr", "--acl", str(source), str(partial)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    if result.returncode != 0:
        raise MigrationError(f"ditto failed for {source}: {result.stderr.strip()}")


def copy_regular_file(
    relative: str,
    source_file: Path,
    destination_file: Path,
    source_metadata: os.stat_result,
    destination: Path,
    work_root: Path,
    state: Dict[str, Any],
    state_path: Path,
    guard: DestinationGuard,
) -> None:
    known_hash = state["file_sha256"].get(relative)
    inode_key = f"{source_metadata.st_dev}:{source_metadata.st_ino}"
    representative_relative = state["hardlinks"].get(inode_key)

    if lexists(destination_file):
        matches, source_hash = destination_file_matches(source_file, destination_file, known_hash)
        if not matches:
            raise MigrationError(
                f"Existing destination file differs; refusing overwrite / 目标已有不同文件，拒绝覆盖: {destination_file}"
            )
        state["file_sha256"][relative] = source_hash
        if source_metadata.st_nlink > 1:
            if representative_relative:
                representative = destination / representative_relative
                if representative.stat().st_ino != destination_file.stat().st_ino:
                    raise MigrationError(f"Destination hardlink topology differs / 目标硬链接结构不一致: {relative}")
            else:
                state["hardlinks"][inode_key] = relative
        return

    guard.check()
    if representative_relative:
        representative = destination / representative_relative
        if not representative.is_file() or representative.is_symlink():
            raise MigrationError(f"Hardlink representative is unavailable / 硬链接代表文件不可用: {representative}")
        os.link(str(representative), str(destination_file))
        source_hash = state["file_sha256"].get(representative_relative) or sha256_file(source_file)
        state["file_sha256"][relative] = source_hash
    else:
        migration_id = str(state["migration_id"])
        partial = partial_path(destination_file, migration_id)
        if lexists(partial):
            prepare_owned_partial(partial, destination, migration_id)

        before = metadata_signature(source_file.lstat())
        ditto_copy_file(source_file, partial, work_root)
        if not partial.is_file() or partial.is_symlink():
            raise MigrationError(f"Partial copy is not a regular file / 临时副本不是普通文件: {partial}")
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        source_hash = sha256_file(source_file)
        destination_hash = sha256_file(partial)
        after = metadata_signature(source_file.lstat())
        if before != after:
            raise MigrationError(f"Source file changed while being copied / 复制时源文件发生变化: {relative}")
        if source_hash != destination_hash:
            raise MigrationError(f"SHA-256 mismatch / SHA-256 不一致: {relative}")
        guard.check()
        os.replace(str(partial), str(destination_file))
        fsync_directory(destination_file.parent)
        state["file_sha256"][relative] = source_hash
        if source_metadata.st_nlink > 1:
            state["hardlinks"][inode_key] = relative

    state["progress"]["files"] += 1
    state["progress"]["bytes"] += source_metadata.st_size
    checkpoint_state(state_path, state)


def seed_hardlink_representatives(
    source: Path,
    destination: Path,
    state: Dict[str, Any],
    snapshot: Dict[str, Dict[str, Any]],
) -> None:
    """Use a verified surviving destination hardlink as the resume representative."""
    for relative in sorted(snapshot):
        expected = snapshot[relative]
        if expected.get("type") != "file" or int(expected.get("nlink", 1)) <= 1:
            continue
        inode_key = f"{expected['device']}:{expected['inode']}"
        if inode_key in state["hardlinks"]:
            continue
        source_file = source / relative
        destination_file = destination / relative
        if not destination_file.is_file() or destination_file.is_symlink():
            continue
        matches, source_hash = destination_file_matches(
            source_file,
            destination_file,
            state["file_sha256"].get(relative),
        )
        if matches:
            state["hardlinks"][inode_key] = relative
            state["file_sha256"][relative] = source_hash


def copy_tree(
    source: Path,
    destination: Path,
    state: Dict[str, Any],
    guard: DestinationGuard,
) -> None:
    snapshot = state["source_snapshot"]
    # Rebuild hardlink representatives from destination entries on every run.
    # A persisted representative may itself be the file missing after an interruption.
    state["hardlinks"] = {}
    migration_id = str(state["migration_id"])
    work_root = destination.parent / f".{destination.name}.migrate-work-{migration_id}"
    if lexists(work_root) and (work_root.is_symlink() or not work_root.is_dir()):
        raise MigrationError(f"Invalid migration work directory / 迁移工作目录无效: {work_root}")
    work_root.mkdir(mode=0o700, exist_ok=True)
    state_path = state_path_for(destination)

    if lexists(destination):
        if destination.is_symlink() or not destination.is_dir():
            raise MigrationError(f"Destination is not a real directory / 目标不是实体目录: {destination}")
    else:
        guard.check(force_slow=True)
        destination.mkdir(mode=0o700)
        fsync_directory(destination.parent)

    seed_hardlink_representatives(source, destination, state, snapshot)

    try:
        for relative in sorted(snapshot):
            if relative == ".":
                continue
            expected = snapshot[relative]
            source_path = source / relative
            destination_path = destination / relative
            source_metadata = assert_snapshot_entry(relative, source_path, expected)
            ensure_parent_directories(relative, source, destination, snapshot, guard)

            if expected["type"] == "directory":
                if lexists(destination_path):
                    if destination_path.is_symlink() or not destination_path.is_dir():
                        raise MigrationError(f"Destination type mismatch / 目标类型不匹配: {destination_path}")
                else:
                    guard.check()
                    destination_path.mkdir(mode=0o700)
            elif expected["type"] == "symlink":
                target = str(expected["link_target"])
                if lexists(destination_path):
                    if not destination_path.is_symlink() or os.readlink(str(destination_path)) != target:
                        raise MigrationError(f"Destination symlink differs / 目标软链接不一致: {destination_path}")
                else:
                    guard.check()
                    os.symlink(target, str(destination_path))
                    state["progress"]["symlinks"] += 1
                # A previous run can stop after creating the link but before
                # applying its metadata. Always reapply metadata on resume.
                copy_symlink_metadata(source_path, destination_path)
                checkpoint_state(state_path, state)
            elif expected["type"] == "file":
                copy_regular_file(
                    relative,
                    source_path,
                    destination_path,
                    source_metadata,
                    destination,
                    work_root,
                    state,
                    state_path,
                    guard,
                )
            else:
                raise MigrationError(f"Special file is unsupported / 不支持特殊文件: {source_path}")

        # Apply directory metadata last because creating children changes directory timestamps.
        directory_relatives = [
            relative for relative, record in snapshot.items() if record["type"] == "directory"
        ]
        for relative in sorted(directory_relatives, key=lambda item: item.count("/"), reverse=True):
            source_dir = source if relative == "." else source / relative
            destination_dir = destination if relative == "." else destination / relative
            assert_snapshot_entry(relative, source_dir, snapshot[relative])
            copy_directory_metadata(source_dir, destination_dir)

        current_snapshot = source_snapshot(source)
        if current_snapshot != snapshot:
            raise MigrationError("Source tree changed during copy / 复制期间源目录发生变化")
        guard.check(force_slow=True)
    finally:
        try:
            work_root.rmdir()
        except OSError:
            pass


def command_copy(arguments: argparse.Namespace) -> None:
    source = lexical_absolute(arguments.source)
    destination = lexical_absolute(arguments.destination)
    validate_source_and_destination(source, destination)
    require_source_directory(source)
    kind = resolve_kind(source, arguments.kind)
    destination_info = require_destination_policy(destination)
    require_processes_stopped(arguments.process_name)

    stats = tree_stats(source)
    if stats["special"]:
        raise MigrationError("Source contains special files / 源目录包含不支持的特殊文件")
    print_audit(source, destination, kind, stats, destination_info)
    snapshot = source_snapshot(source)
    existing_state = load_state(destination, required=False)
    if existing_state is None and lexists(destination):
        raise MigrationError(
            "Destination already exists without this migration journal / 目标已存在但没有本次迁移日志"
        )
    if existing_state is not None:
        validate_state(existing_state, source, destination, kind)
        require_journal_destination(destination, existing_state)
        state = existing_state
        if state.get("status") not in {"copying", "copied", "verified", "linked"}:
            raise MigrationError("Migration journal status is invalid / 迁移日志状态无效")
        if snapshot != state.get("source_snapshot"):
            raise MigrationError("Source differs from the saved start snapshot / 源目录与初始快照不一致")
    else:
        state = make_initial_state(
            source,
            destination,
            kind,
            arguments.process_name,
            disk_info(source),
            destination_info,
            stats,
            snapshot,
        )

    saved_process_names = state.get("process_names", [])
    if not isinstance(saved_process_names, list) or any(
        not isinstance(name, str) or not name for name in saved_process_names
    ):
        raise MigrationError("Migration journal process list is invalid / 迁移日志进程列表无效")
    process_names = sorted(set(saved_process_names) | set(arguments.process_name))
    state["process_names"] = process_names
    require_processes_stopped(process_names)

    existing_payload = 0
    if destination.is_dir() and not destination.is_symlink():
        existing_payload = min(stats["unique_bytes"], tree_stats(destination)["unique_bytes"])
    remaining_payload = max(0, stats["unique_bytes"] - existing_payload)
    required_free = remaining_payload + COPY_OVERHEAD_BYTES
    print(f"  Remaining payload / 剩余数据: {format_bytes(remaining_payload)}")
    print(f"  Required destination free / 目标所需可用空间: {format_bytes(required_free)}")
    if int(destination_info["free_bytes"]) < required_free:
        raise MigrationError("Not enough destination space / 目标空间不足")

    if not arguments.execute:
        print("Dry run only; no files were written / 仅预演，未写入任何文件")
        print("Re-run with --execute after reviewing the exact paths / 审核准确路径后添加 --execute")
        return

    guard = DestinationGuard(destination.parent, destination_info, process_names)
    if existing_state is None:
        write_state(state_path_for(destination), state)
    copy_tree(source, destination, state, guard)
    state["progress"] = {
        "files": stats["files"],
        "symlinks": stats["symlinks"],
        "bytes": stats["logical_bytes"],
    }
    state["status"] = "copied"
    state["copied_at"] = time.time()
    write_state(state_path_for(destination), state)
    print("Copy complete; source remains untouched / 复制完成，源目录保持不变")
    print("Next: run verify before Finder handoff / 下一步：先运行 verify，再进入访达交接")


APP_ROOT_INSTANCE_LOCAL_XATTRS = frozenset(
    {
        # macOS can attach or rewrite these system-managed attributes during a
        # cross-volume app copy or first launch. Finder comments are an
        # intentional instance label. These rewrite exceptions are deliberately
        # limited to the app-bundle root. App descendants retain strict xattr
        # comparison except for the destination-only provenance case documented
        # separately below; data migrations remain fully strict.
        b"com.apple.macl",
        b"com.apple.metadata:kMDItemFinderComment",
        b"com.apple.provenance",
        b"com.apple.quarantine",
    }
)

# macOS may attach this protected, system-generated attribute to every entry
# created while copying an application bundle to another volume. It cannot be
# removed reliably by an unprivileged process. Verification may therefore
# accept it only when it is an extra destination attribute in an app bundle.
# A source value must still be preserved exactly, and data migrations retain
# strict bidirectional xattr comparison.
APP_DESTINATION_ONLY_XATTRS = frozenset({b"com.apple.provenance"})


def verification_ignored_xattrs(kind: str, relative: str) -> frozenset[bytes]:
    if kind == "app" and relative == ".":
        return APP_ROOT_INSTANCE_LOCAL_XATTRS
    return frozenset()


def normalize_destination_only_app_xattrs(
    source_record: Dict[str, Any],
    destination_record: Dict[str, Any],
    kind: str,
) -> None:
    if kind != "app":
        return
    source_xattrs = source_record.get("xattrs")
    destination_xattrs = destination_record.get("xattrs")
    if not isinstance(source_xattrs, dict) or not isinstance(destination_xattrs, dict):
        return
    for name in APP_DESTINATION_ONLY_XATTRS:
        key = name.hex()
        if key not in source_xattrs:
            destination_xattrs.pop(key, None)


def xattr_map(
    path: Path,
    follow_symlinks: bool,
    ignored_names: frozenset[bytes] = frozenset(),
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for name in list_xattr_names(path, follow_symlinks):
        if name in ignored_names:
            continue
        value = read_xattr(path, name, follow_symlinks)
        result[name.hex()] = hashlib.sha256(value).hexdigest()
    return result


def verification_record(
    path: Path,
    metadata: os.stat_result,
    ignored_xattrs: frozenset[bytes] = frozenset(),
) -> Dict[str, Any]:
    kind = file_type(metadata.st_mode)
    record: Dict[str, Any] = {
        "type": kind,
        "mode": stat.S_IMODE(metadata.st_mode),
        "flags": getattr(metadata, "st_flags", 0),
        "xattrs": xattr_map(path, follow_symlinks=False, ignored_names=ignored_xattrs),
        "acl": acl_text(path),
    }
    if kind != "symlink":
        record["mtime_ns"] = metadata.st_mtime_ns
    if kind == "file":
        record["size"] = metadata.st_size
    elif kind == "symlink":
        record["link_target"] = os.readlink(str(path))
    return record


def stability_signature(metadata: os.stat_result) -> Dict[str, Any]:
    signature = metadata_signature(metadata)
    signature["ctime_ns"] = metadata.st_ctime_ns
    return signature


def collect_verification_entries(root: Path) -> Dict[str, Tuple[Path, os.stat_result]]:
    try:
        return {relative: (path, metadata) for relative, path, metadata in iter_tree(root)}
    except OSError as error:
        raise MigrationError(
            f"Tree changed while being inspected / 检查时目录树发生变化: {root}: {error}"
        ) from error


def verification_stability_snapshot(
    entries: Dict[str, Tuple[Path, os.stat_result]],
    kind: str,
) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for relative in sorted(entries):
        path, discovered_metadata = entries[relative]
        try:
            before = path.lstat()
            before_signature = stability_signature(before)
            if before_signature != stability_signature(discovered_metadata):
                raise MigrationError(
                    f"Tree changed while being inspected / 检查时目录树发生变化: {relative}"
                )
            record = verification_record(
                path,
                before,
                ignored_xattrs=verification_ignored_xattrs(kind, relative),
            )
            after_signature = stability_signature(path.lstat())
        except OSError as error:
            raise MigrationError(
                f"Tree changed while being inspected / 检查时目录树发生变化: {relative}: {error}"
            ) from error
        if after_signature != before_signature:
            raise MigrationError(
                f"Entry changed while metadata was read / 读取元数据时条目发生变化: {relative}"
            )
        record["_stability_stat"] = before_signature
        snapshot[relative] = record
    return snapshot


def stable_sha256_file(path: Path, expected: Dict[str, Any], relative: str) -> str:
    try:
        before = stability_signature(path.lstat())
        if before != expected:
            raise MigrationError(
                f"File changed before hashing / 哈希前文件发生变化: {relative}"
            )
        digest = sha256_file(path)
        after = stability_signature(path.lstat())
    except OSError as error:
        raise MigrationError(
            f"File changed while hashing / 哈希时文件发生变化: {relative}: {error}"
        ) from error
    if after != before:
        raise MigrationError(f"File changed while hashing / 哈希时文件发生变化: {relative}")
    return digest


def hardlink_topology(
    entries: Dict[str, Tuple[Path, os.stat_result]],
    require_destination_isolation: bool,
) -> List[Tuple[str, ...]]:
    inode_groups: Dict[Tuple[int, int], List[str]] = {}
    for relative, (_path, metadata) in entries.items():
        if stat.S_ISREG(metadata.st_mode):
            inode_groups.setdefault((metadata.st_dev, metadata.st_ino), []).append(relative)

    topology: List[Tuple[str, ...]] = []
    for relatives in inode_groups.values():
        ordered = tuple(sorted(relatives))
        if require_destination_isolation:
            for relative in ordered:
                metadata = entries[relative][1]
                if metadata.st_nlink != len(ordered):
                    raise MigrationError(
                        "Destination file has a hardlink outside the migration tree / "
                        f"目标文件在迁移目录树外还有硬链接: {relative}"
                    )
        if len(ordered) > 1:
            topology.append(ordered)
    return sorted(topology)


def full_verify(source: Path, destination: Path, kind: str = "data") -> Dict[str, str]:
    if kind not in {"app", "data"}:
        raise MigrationError(f"Invalid verification kind / 无效校验类型: {kind}")
    source_entries = collect_verification_entries(source)
    destination_entries = collect_verification_entries(destination)
    if set(source_entries) != set(destination_entries):
        missing = sorted(set(source_entries) - set(destination_entries))[:10]
        extra = sorted(set(destination_entries) - set(source_entries))[:10]
        raise MigrationError(f"Tree entries differ / 目录条目不一致; missing={missing}, extra={extra}")

    source_before = verification_stability_snapshot(source_entries, kind)
    destination_before = verification_stability_snapshot(destination_entries, kind)
    source_topology = hardlink_topology(source_entries, require_destination_isolation=False)
    destination_topology = hardlink_topology(destination_entries, require_destination_isolation=True)
    if source_topology != destination_topology:
        raise MigrationError(
            f"Hardlink topology differs / 硬链接结构不一致: source={source_topology}, destination={destination_topology}"
        )

    hashes: Dict[str, str] = {}
    for relative in sorted(source_entries):
        source_path, _source_metadata = source_entries[relative]
        destination_path, _destination_metadata = destination_entries[relative]
        source_record = dict(source_before[relative])
        destination_record = dict(destination_before[relative])
        source_expected = source_record.pop("_stability_stat")
        destination_expected = destination_record.pop("_stability_stat")
        source_record["xattrs"] = dict(source_record["xattrs"])
        destination_record["xattrs"] = dict(destination_record["xattrs"])
        normalize_destination_only_app_xattrs(source_record, destination_record, kind)
        if source_record != destination_record:
            raise MigrationError(f"Metadata differs / 元数据不一致: {relative}")
        if source_record["type"] == "file":
            source_hash = stable_sha256_file(source_path, source_expected, relative)
            destination_hash = stable_sha256_file(destination_path, destination_expected, relative)
            if source_hash != destination_hash:
                raise MigrationError(f"SHA-256 mismatch / SHA-256 不一致: {relative}")
            hashes[relative] = source_hash

    source_after = verification_stability_snapshot(collect_verification_entries(source), kind)
    destination_after = verification_stability_snapshot(collect_verification_entries(destination), kind)
    if source_after != source_before:
        raise MigrationError("Source changed during verification / 校验期间源目录发生变化")
    if destination_after != destination_before:
        raise MigrationError("Destination changed during verification / 校验期间目标目录发生变化")
    return hashes


def verify_app_signature(app: Path) -> None:
    result = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise MigrationError(
            "Destination app signature verification failed / 目标应用签名校验失败: "
            + result.stderr.strip()
        )


def command_verify(arguments: argparse.Namespace) -> None:
    source = lexical_absolute(arguments.source)
    destination = lexical_absolute(arguments.destination)
    validate_source_and_destination(source, destination)
    require_source_directory(source)
    if destination.is_symlink() or not destination.is_dir():
        raise MigrationError(f"Destination directory not found / 找不到目标目录: {destination}")
    state = load_state(destination)
    assert state is not None
    validate_state(state, source, destination)
    require_journal_destination(destination, state)
    if state.get("status") not in {"copied", "verified", "linked"}:
        raise MigrationError("Copy has not completed / 复制尚未完成")
    process_names = state.get("process_names", [])
    if not isinstance(process_names, list) or any(
        not isinstance(name, str) or not name for name in process_names
    ):
        raise MigrationError("Migration journal process list is invalid / 迁移日志进程列表无效")
    require_processes_stopped(process_names)

    hashes = full_verify(source, destination, str(state["kind"]))
    if state.get("kind") == "app":
        verify_app_signature(destination)
    # A long full-tree hash can outlive an application restart. Do not commit
    # the verified state while a recorded app, updater, or helper is running,
    # even when it has not yet changed a migrated file.
    require_processes_stopped(process_names)
    state["file_sha256"] = hashes
    state["status"] = "linked" if state.get("status") == "linked" else "verified"
    state["verified_at"] = time.time()
    state["full_verification"] = {
        "all_regular_files_sha256": True,
        "metadata": True,
        "xattrs": True,
        "acls": True,
        "hardlinks": True,
        "stable_snapshots": True,
        "destination_hardlink_isolation": True,
        "codesign": state.get("kind") == "app",
    }
    write_state(state_path_for(destination), state)
    print("Full verification passed / 完整校验通过")
    print("Source remains untouched / 源目录保持不变")


def validate_reveal_path(source: Path, requested: Optional[str]) -> Path:
    if requested is None:
        return source
    candidate = lexical_absolute(requested)
    if candidate == source:
        return candidate
    if candidate.parent != source.parent or not candidate.name.startswith(source.name):
        raise MigrationError(
            "Reveal path must be the source or its explicitly named sibling backup / "
            "访达定位路径只能是源路径或同级、以原名开头的备份"
        )
    return candidate


def command_reveal(arguments: argparse.Namespace) -> None:
    source = lexical_absolute(arguments.source)
    destination = lexical_absolute(arguments.destination)
    validate_source_and_destination(source, destination)
    state = load_state(destination)
    assert state is not None
    validate_state(state, source, destination)
    if destination.is_symlink() or not destination.is_dir():
        raise MigrationError("Verified destination is unavailable / 已校验目标不可用")
    require_journal_destination(destination, state)
    if state.get("status") not in {"verified", "linked"}:
        raise MigrationError("Full verification is required first / 必须先完成完整校验")
    reveal_path = validate_reveal_path(source, arguments.path)
    if not lexists(reveal_path):
        raise MigrationError(f"Path to reveal does not exist / 要在访达定位的路径不存在: {reveal_path}")

    print(f"Finder handoff / 访达交接: {reveal_path}")
    if state.get("kind") == "app":
        print("First launch and smoke-test the external app. Then move the internal app to Trash in Finder.")
        print("请先启动并实测外接盘应用；确认正常后，再在访达中把内置应用移到废纸篓。")
    else:
        print("After explicit authorization, move the source to Trash in Finder but do not empty Trash.")
        print("用户明确授权后，请在访达中把源目录移到废纸篓，但不要清空废纸篓。")
        print(f"Use a sibling backup only when explicitly selected: {source.name}.internal-backup")
        print(f"只有明确选择同级备份时才改名为：{source.name}.internal-backup")
        print("Return only after Finder finishes. The helper itself will not move or delete the source.")
        print("访达完成后再继续；迁移脚本本身不会移动或删除源目录。")
    if not arguments.print_only:
        subprocess.run(["/usr/bin/open", "-R", str(reveal_path)], check=True)


def command_link(arguments: argparse.Namespace) -> None:
    source = lexical_absolute(arguments.source)
    destination = lexical_absolute(arguments.destination)
    validate_source_and_destination(source, destination)
    state = load_state(destination)
    assert state is not None
    validate_state(state, source, destination)
    if state.get("kind") == "app":
        raise MigrationError("App bundles should launch from the external volume; no source link is created / 应用应直接从外接盘启动，不建立原路径软链接")
    if state.get("status") not in {"verified", "linked"}:
        raise MigrationError("Full verification is required before linking / 建立链接前必须完成完整校验")
    if not destination.is_dir() or destination.is_symlink():
        raise MigrationError("Verified destination is unavailable / 已校验目标不可用")
    require_journal_destination(destination, state)

    if source.is_symlink():
        if source.resolve(strict=False) == destination.resolve(strict=True):
            state["status"] = "linked"
            write_state(state_path_for(destination), state)
            print("Source link already points to destination / 原路径软链接已指向目标")
            return
        raise MigrationError("A different source symlink already exists / 原路径已有其他软链接")
    if lexists(source):
        raise MigrationError(
            "Source still exists. Complete the authorized Finder handoff first: move it to Trash by default, "
            "or use the explicitly selected sibling backup; this tool will not remove it / "
            "源路径仍存在；请先完成已授权的访达交接：默认移到废纸篓，或使用明确选择的同级备份；"
            "本工具不会移除源路径"
        )
    if not source.parent.is_dir() or source.parent.is_symlink():
        raise MigrationError("Source parent is unavailable / 源路径上级目录不可用")
    if not os.access(str(source.parent), os.W_OK):
        raise MigrationError(
            "Source parent is not user-writable; do not use sudo / 当前用户不可写入源路径上级目录，请勿使用 sudo"
        )

    print(f"Link / 链接: {source} -> {destination}")
    print("This creates only a small symlink; it does not empty Trash or delete the Finder recovery copy / 仅建立小型软链接，不清空废纸篓或删除访达恢复副本")
    if not arguments.execute:
        print("Dry run only / 仅预演；审核后添加 --execute")
        return
    os.symlink(str(destination), str(source))
    state["status"] = "linked"
    state["linked_at"] = time.time()
    write_state(state_path_for(destination), state)
    print("Link created. Keep the Finder recovery copy until the app passes a real smoke test / 链接已建立；应用实测通过前请保留访达恢复副本")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy and verify macOS app data without deleting the source / 复制并校验 macOS 应用数据，绝不删除源文件"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="read-only audit / 只读审计")
    audit.add_argument("--source", required=True)
    audit.add_argument("--destination", required=True)
    audit.add_argument("--kind", choices=("auto", "app", "data"), default="auto")
    audit.set_defaults(handler=command_audit)

    copy = subparsers.add_parser("copy", help="copy to destination without source deletion / 复制到目标但不删除源")
    copy.add_argument("--source", required=True)
    copy.add_argument("--destination", required=True)
    copy.add_argument("--kind", choices=("auto", "app", "data"), default="auto")
    copy.add_argument("--process-name", action="append", default=[])
    copy.add_argument("--execute", action="store_true")
    copy.set_defaults(handler=command_copy)

    verify = subparsers.add_parser("verify", help="full source-to-destination verification / 完整源目标校验")
    verify.add_argument("--source", required=True)
    verify.add_argument("--destination", required=True)
    verify.set_defaults(handler=command_verify)

    reveal = subparsers.add_parser("reveal", help="reveal source or backup in Finder / 在访达定位源或备份")
    reveal.add_argument("--source", required=True)
    reveal.add_argument("--destination", required=True)
    reveal.add_argument("--path")
    reveal.add_argument("--print-only", action="store_true")
    reveal.set_defaults(handler=command_reveal)

    link = subparsers.add_parser("link", help="create a symlink after Finder handoff / 访达交接后建立软链接")
    link.add_argument("--source", required=True)
    link.add_argument("--destination", required=True)
    link.add_argument("--execute", action="store_true")
    link.set_defaults(handler=command_link)
    return parser


def main() -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args()
        arguments.handler(arguments)
        return 0
    except MigrationError as error:
        eprint(f"Safety stop / 安全停止: {error}")
        return 2
    except KeyboardInterrupt:
        eprint("Interrupted safely; source was not deleted / 已安全中断，源数据未被删除")
        return 130
    except subprocess.CalledProcessError as error:
        eprint(f"Command failed / 命令失败: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
