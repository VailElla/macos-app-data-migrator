# Install Directly from a DMG to External APFS

## Contents

- [Scope](#scope)
- [1. Validate and mount the image read-only](#1-validate-and-mount-the-image-read-only)
- [2. Copy from the mounted source and fully verify](#2-copy-from-the-mounted-source-and-fully-verify)
- [3. Record split state and test the real integration](#3-record-split-state-and-test-the-real-integration)
- [4. Eject the image and retain the installer](#4-eject-the-image-and-retain-the-installer)

## Scope

Use this workflow when the user supplies a `.dmg` containing a directly runnable macOS `.app` and wants the first installation on external APFS. The app on the mounted image is a read-only installation source, not an old internal copy that must be removed from `/Applications`.

- Install one exact `.app` from the image at a time.
- Do not expand, convert, or duplicate the DMG into another internal-disk image.
- Require a destination that `diskutil` explicitly identifies as external APFS.
- Preserve the downloaded DMG, mounted source app, and external destination until full verification and live acceptance are complete.
- Never use `sudo`, add an overwrite mode, or add a verification bypass.

If `/Applications` already contains a same-named app, treat it as a separate existing-app migration and handoff component. A DMG source never authorizes replacing or deleting that internal app.

## 1. Validate and mount the image read-only

Resolve the exact user-supplied DMG, record a local SHA-256 fingerprint, and validate its embedded image checksum:

```bash
/usr/bin/shasum -a 256 "/absolute/path/App.dmg"
/usr/bin/hdiutil verify "/absolute/path/App.dmg"
/usr/sbin/diskutil image attach --plist --readOnly --nobrowse "/absolute/path/App.dmg"
```

When the publisher provides an official checksum through a primary source, compare it before continuing. On an older macOS release that does not provide `diskutil image attach`, use `/usr/bin/hdiutil attach -readonly -nobrowse` as the compatibility fallback; do not fall back merely because the current command reports a real image error. Derive the image device and current mount point from this command's result, then confirm them with `diskutil info`; never guess the volume name or reuse a stale `/Volumes/...` path.

Select only the exact `.app` on the mounted volume and inspect it read-only:

```bash
python3 scripts/inspect_app.py "/Volumes/ExactMountedVolume/App.app" --verify-signature

python3 scripts/migrate_app_data.py audit \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app
```

Record the DMG fingerprint, mount point, source app, bundle ID, version, process names, source-volume identity, destination-volume UUID, external free capacity, and largest file. Stop on an installer package, script, system extension, or `.pkg` that requires privileged installation; this workflow covers only directly runnable app bundles.

## 2. Copy from the mounted source and fully verify

Keep the image mounted and quit the same-named app, updater, and every helper. Dry-run first, review the same paths, and then execute:

```bash
python3 scripts/migrate_app_data.py copy \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app \
  --process-name "ExactProcessName"

python3 scripts/migrate_app_data.py copy \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app \
  --process-name "ExactProcessName" \
  --execute

python3 scripts/migrate_app_data.py verify \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --process-name "ExactProcessName"
```

The external journal must remain beside the destination and record `status: verified`. Detaching the DMG removes the source path, so complete the full source/destination SHA-256, tree, metadata, ACL, xattr, symlink, hardlink, and strict code-signature checks before detaching it. A destination-only signature check cannot retroactively replace verification against a missing source.

Assess the external destination against the current system policy as a separate acceptance gate. On macOS 14 or later, prefer `syspolicy_check`, which includes Gatekeeper and other trusted-execution checks:

```bash
/usr/bin/codesign --verify --deep --strict --verbose=2 "/Volumes/External/Applications/App.app"
/usr/bin/syspolicy_check distribution "/Volumes/External/Applications/App.app"
```

Only on an older macOS release without `syspolicy_check`, use the legacy Gatekeeper assessment:

```bash
/usr/sbin/spctl --assess --type execute --verbose=4 "/Volumes/External/Applications/App.app"
```

Launch only after strict code-signature verification and the platform-appropriate system-policy check pass. Do not add an overwrite mode to the copier. For a future version, copy and verify into a distinct staging destination before designing an explicit, recoverable version handoff.

## 3. Record split state and test the real integration

Record internal free space and the shared-pasteboard baseline before and after the first launch, then launch the exact external path. Test launch, read, a safe write, full quit, relaunch, and updater behavior.

An external app bundle does not imply that every state file is external. Preferences, plugins, login state, small databases, TCC records, and command-line tool configuration normally remain under the user profile and are outside this app-bundle payload by default. The acceptance record must distinguish:

- the external app and destination volume;
- actual internal user-configuration, plugin, and preference paths plus approximate size;
- separately configured plugins, command-line bridges, MCP servers, or other integrations;
- whether those integrations persist after full quit, relaunch, or external-volume remount;
- any runtime-derived cache growth that exceeds available internal capacity.

Declare the external DMG installation successful only when the app and required integrations work and no large app payload is recreated internally.

## 4. Eject the image and retain the installer

After full verification and live acceptance, eject the exact image device returned by the attach command:

```bash
/usr/sbin/diskutil eject "/dev/diskN"
```

A direct DMG install has no internal app source, so it does not use the app-migration Finder removal handoff and does not create an original-path symlink. Retain the downloaded DMG by default. If the user explicitly requests cleanup, move only that exact DMG to Trash through Finder; never delete it from Terminal or empty Trash automatically.
