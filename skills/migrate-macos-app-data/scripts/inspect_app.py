#!/usr/bin/env python3
"""Read-only macOS app inspection before adapter choice / 选择迁移适配器前只读检查应用。"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_plist(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return plistlib.load(handle)


def extract_entitlements(app: Path) -> dict[str, Any]:
    result = run(["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app)])
    for payload in (result.stdout, result.stderr):
        xml_start = payload.find(b"<?xml")
        binary_start = payload.find(b"bplist")
        start_candidates = [position for position in (xml_start, binary_start) if position >= 0]
        if not start_candidates:
            continue
        try:
            return plistlib.loads(payload[min(start_candidates):])
        except Exception:
            continue
    return {}


def candidate_paths(bundle_id: str, bundle_name: str, entitlements: dict[str, Any]) -> list[tuple[str, Path]]:
    home = Path.home()
    candidates: list[tuple[str, Path]] = []
    if bundle_id:
        candidates.extend(
            [
                ("sandbox container / 沙盒容器", home / "Library" / "Containers" / bundle_id),
                ("application support by bundle id / 按 bundle ID", home / "Library" / "Application Support" / bundle_id),
                ("cache / 缓存", home / "Library" / "Caches" / bundle_id),
                ("preferences / 偏好设置", home / "Library" / "Preferences" / f"{bundle_id}.plist"),
                ("saved state / 保存状态", home / "Library" / "Saved Application State" / f"{bundle_id}.savedState"),
            ]
        )
    candidates.append(
        ("application support by name / 按应用名称", home / "Library" / "Application Support" / bundle_name)
    )
    groups = entitlements.get("com.apple.security.application-groups", [])
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, str):
                candidates.append(("app group / 应用组", home / "Library" / "Group Containers" / group))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", help="Path to the .app bundle")
    parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Perform a potentially slow full bundle signature verification",
    )
    args = parser.parse_args()

    app = Path(args.app).expanduser()
    if not app.is_absolute():
        app = Path.cwd() / app
    app = Path(os.path.abspath(app))
    info_path = app / "Contents" / "Info.plist"
    if app.suffix != ".app" or not info_path.is_file():
        print(f"error / 错误: not a macOS app bundle / 不是 macOS 应用包: {app}", file=sys.stderr)
        return 2

    info = read_plist(info_path)
    bundle_id = str(info.get("CFBundleIdentifier", ""))
    bundle_name = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem)
    executable = str(info.get("CFBundleExecutable", ""))
    entitlements = extract_entitlements(app)
    sandboxed = bool(entitlements.get("com.apple.security.app-sandbox", False))

    if args.verify_signature:
        signature = run(["/usr/bin/codesign", "--verify", "--strict", str(app)])
        signature_label = "verified / 已验证" if signature.returncode == 0 else "verification failed / 验证失败"
    else:
        signature = run(["/usr/bin/codesign", "-d", str(app)])
        signature_label = (
            "present, not fully verified / 已检测，未完整验证"
            if signature.returncode == 0
            else "not detected / 未检测到"
        )
    process = run(["/usr/bin/pgrep", "-x", executable]) if executable else None

    print(f"App / 应用:             {app}")
    print(f"Name / 名称:            {bundle_name}")
    print(f"Bundle ID:              {bundle_id or 'unknown / 未知'}")
    print(f"Executable / 可执行文件: {executable or 'unknown / 未知'}")
    print(f"Sandboxed / 沙盒:       {'yes / 是' if sandboxed else 'no / 否'}")
    print(f"Signature / 签名:       {signature_label}")
    print(f"Running / 正在运行:     {'yes / 是' if process and process.returncode == 0 else 'no / 否'}")
    print("\nExisting data candidates / 已存在的数据候选（只检查，不要全部盲目迁移）:")
    found = False
    for label, path in candidate_paths(bundle_id, bundle_name, entitlements):
        if path.exists() or path.is_symlink():
            found = True
            kind = "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file"
            print(f"- {label}: {path} [{kind}]")
    if not found:
        print("- No standard candidate found; inspect app storage settings and open files.")
        print("  未发现标准候选；请检查程序自身的存储设置和已打开文件。")

    print("\nAdapter guidance / 适配器建议:")
    if sandboxed:
        print("- Do not assume a plain symlink will work across volumes. / 不要假设跨宗卷普通软链接可用。")
        print("- Prefer an app-native setting or tested security-scoped adapter. / 优先使用程序原生设置或已验证的安全作用域适配器。")
    else:
        print("- A symlink may work, but require a live smoke test. / 软链接可能可用，但必须完成真实运行测试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
