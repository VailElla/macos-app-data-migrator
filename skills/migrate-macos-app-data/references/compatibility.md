# macOS app data compatibility

## Choose the integration before moving data

Classify the target app and prove how it will find the new location before using a destructive streaming move.

| Integration | Preferred use | Ongoing overhead | Main risk |
|---|---|---:|---|
| App-native storage setting | The app exposes a library, cache, model, download, or game-content location | Configuration only | The app may move only some data classes |
| Same-filesystem atomic move + symlink | Source and destination share one filesystem; app is not sandboxed | One symlink | Updates may replace the symlink |
| Cross-volume verified stream + symlink | The app is not sandboxed and external storage is required | One symlink and a small journal | A plain symlink may still be rejected by app-specific checks |
| Security-scoped adapter | A sandboxed app has a proven launch or folder-selection mechanism | Usually a small launcher | Must be tested per app; not universal |

Run `scripts/inspect_app.py /absolute/path/App.app`. Treat `Sandboxed: yes` as a hard warning: a symlink can resolve correctly in Finder while the app sandbox still denies the external target.

## Keep the migration boundary narrow

- Discover the directory that contains the large, relocatable payload. Do not move an entire container merely because it is large.
- Keep preferences, account state, saves, databases, lock files, and keychain references internal unless the app explicitly supports moving them.
- Exclude reproducible caches unless the user specifically wants them preserved; deleting a cache and letting the app rebuild it may be safer than relocating it.
- Do not migrate data managed by iCloud Drive, Dropbox, OneDrive, Time Machine, or another live sync engine without first disabling synchronization and reviewing its rules.
- Process one source directory at a time. Give every source its own destination and migration journal.

## Bound temporary space

- On one filesystem, use the atomic strategy. Directory rename does not duplicate file data.
- Across filesystems, use the streaming strategy only after explicit approval. It copies one file to a temporary destination, fsyncs and SHA-256 verifies it, then removes that source file.
- Expect peak temporary overhead of roughly the largest individual file plus 16 MiB. Absolute zero-byte overhead is impossible during a cross-volume copy.
- The destination still needs enough free space for the final migrated dataset.
- If rollback safety matters more than space, make and verify a full destination copy before deleting any source data instead of using streaming mode.

## Filesystem and lifecycle requirements

- Prefer APFS. exFAT and network filesystems can lose permissions, ACLs, extended attributes, sparse-file behavior, or case semantics.
- Quit the app and every helper/updater process before migration. Re-check immediately before execution.
- Confirm that the external volume auto-mounts at a stable path before login launch, app updates, or background helpers need the data.
- Fully quit the app before ejecting the external disk.
- Re-run a smoke test after major app updates because an updater can replace a symlink or change its storage layout.
