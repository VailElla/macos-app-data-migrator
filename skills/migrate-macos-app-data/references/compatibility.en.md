# macOS App and Data Migration Compatibility

## Prove how the app will find the new location first

Migrating identical bytes and migrating a working application are separate problems. Full hashes prove copy identity; only a real launch, read, write, quit, and relaunch test proves compatibility.

| Component | Preferred integration | When it fits | Risk that must be tested |
|---|---|---|---|
| `.app` bundle | Launch directly from external APFS | The standalone app permits removable-volume execution | Signature, Gatekeeper, login items, and updater behavior at the new path |
| Large data directory | App-native location setting | The app exposes a library, model, download, or game-content location | Whether all large data classes move and the setting survives relaunch |
| Non-sandboxed data | Original-path symlink | The app and updater accept an external resolved target | Updates replacing the link and disconnection creating an empty directory |
| Sandboxed data | Folder picker or security-scoped adapter | The mechanism is tested for that exact app | The sandbox may reject the external target even when Finder follows a symlink |

Run:

```bash
python3 scripts/inspect_app.py "/absolute/path/App.app" --verify-signature
```

Treat `Sandboxed: yes` as an unproven-symlink warning. Prefer the app's settings. If there is no native mechanism or tested adapter, keep the source intact and stop.

## Scope one exact component

- Process one `.app` or one directory at a time. Copy, verify, and smoke-test program and data as separate components when both are in scope.
- Select only the large relocatable payload, such as game resources, a media library, downloads, offline models, or a cache the user explicitly needs to retain.
- Keep preferences, login state, saves, databases, lock files, keychain references, and updater state internal unless the app explicitly supports relocating them.
- Never migrate all of `~/Library`, all of `~/Library/Containers`, a whole app container, all of `Application Support`, or a synchronization root.
- Pause and review iCloud Drive, Dropbox, OneDrive, Time Machine, and other sync roots under their own rules.

## Space model when internal free space is nearly zero

- The source remains in place. No migration copy, archive, disk image, journal, or per-file partial is created on the internal disk.
- The external destination needs capacity for the full final copy plus approximately 64 MiB of tool headroom.
- Journals and temporary files sit beside the external destination, so an interruption does not redirect a large write internally.
- A data integration that requires the original path creates one small symlink on the internal filesystem. If even that metadata cannot be written, release a small amount in Finder or use an app-native setting.
- macOS itself may create small logs, TCC records, or security-bookmark metadata. Those are not migration payloads, and literal zero OS writes cannot be guaranteed.

## Filesystem and lifecycle requirements

- Production migration accepts only a volume `diskutil` explicitly identifies as external APFS. Never use the internal-destination test override for real data.
- exFAT, NTFS, network filesystems, and cloud drives can lose ACLs, extended attributes, resource forks, hardlinks, permissions, or case semantics and are rejected by default.
- Quit the app, launcher, updater, and helpers. The copier re-checks named processes periodically.
- Require a stable external mount path. Stop immediately on disconnection; never continue into an internal directory that happens to have the same name.
- Quit the app before ejecting the volume. Re-test signatures, links/location settings, and real I/O after major updates.

## Success gate

Every condition is required:

1. While the source still exists, verify the full tree, SHA-256 of every regular file, metadata, ACLs, extended attributes, symlinks, and hardlinks.
2. Require strict deep signature verification for an `.app`.
3. Launch the external copy, read existing content, and complete a safe write.
4. Quit fully, relaunch successfully, and confirm new writes land externally.
5. Check updater, login-item, helper, and sandbox behavior.

Do not guide the user to remove the internal source app or data until every condition passes.
