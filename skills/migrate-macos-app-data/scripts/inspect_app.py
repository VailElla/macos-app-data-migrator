#!/usr/bin/env python3
"""Read-only inspection of a macOS app before choosing a migration adapter."""

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
    candidates: list[tuple[str, Path]] = [
        ("sandbox container", home / "Library" / "Containers" / bundle_id),
        ("application support by bundle id", home / "Library" / "Application Support" / bundle_id),
        ("application support by name", home / "Library" / "Application Support" / bundle_name),
        ("cache", home / "Library" / "Caches" / bundle_id),
        ("preferences", home / "Library" / "Preferences" / f"{bundle_id}.plist"),
        ("saved state", home / "Library" / "Saved Application State" / f"{bundle_id}.savedState"),
    ]
    groups = entitlements.get("com.apple.security.application-groups", [])
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, str):
                candidates.append(("app group", home / "Library" / "Group Containers" / group))
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
        print(f"error: not a macOS app bundle: {app}", file=sys.stderr)
        return 2

    info = read_plist(info_path)
    bundle_id = str(info.get("CFBundleIdentifier", ""))
    bundle_name = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem)
    executable = str(info.get("CFBundleExecutable", ""))
    entitlements = extract_entitlements(app)
    sandboxed = bool(entitlements.get("com.apple.security.app-sandbox", False))

    if args.verify_signature:
        signature = run(["/usr/bin/codesign", "--verify", "--strict", str(app)])
        signature_label = "verified" if signature.returncode == 0 else "verification failed"
    else:
        signature = run(["/usr/bin/codesign", "-d", str(app)])
        signature_label = "present (not fully verified)" if signature.returncode == 0 else "not detected"
    process = run(["/usr/bin/pgrep", "-x", executable]) if executable else None

    print(f"App:          {app}")
    print(f"Name:         {bundle_name}")
    print(f"Bundle ID:    {bundle_id or 'unknown'}")
    print(f"Executable:   {executable or 'unknown'}")
    print(f"Sandboxed:    {'yes' if sandboxed else 'no'}")
    print(f"Signature:    {signature_label}")
    print(f"Running:      {'yes' if process and process.returncode == 0 else 'no'}")
    print("\nExisting data candidates (inspect; do not migrate all of them blindly):")
    found = False
    for label, path in candidate_paths(bundle_id, bundle_name, entitlements):
        if path.exists() or path.is_symlink():
            found = True
            kind = "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file"
            print(f"- {label}: {path} [{kind}]")
    if not found:
        print("- none of the standard candidates exist; inspect the app's own storage settings and open files")

    print("\nAdapter guidance:")
    if sandboxed:
        print("- Do not assume a plain symlink will work across volumes.")
        print("- Prefer an app-native storage setting or a tested security-scoped adapter.")
    else:
        print("- A symlink may work, but perform a live smoke test before declaring success.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
