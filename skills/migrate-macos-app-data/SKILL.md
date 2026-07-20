---
name: migrate-macos-app-data
description: Safely migrate macOS application or game data directories between internal and external volumes with minimal temporary disk usage. Use when a user asks to move large app data, game resources, AI models, media libraries, downloads, or caches to another disk while keeping the app operational; when a symlink may interact with App Sandbox; or when migrating Wuthering Waves / 鸣潮 data with its security-scoped launcher adapter. Provides read-only discovery, APFS compatibility checks, same-filesystem atomic moves, resumable cross-volume per-file SHA-256 copy-delete, source-link creation, and post-migration verification.
---

# Migrate macOS App Data

Move one narrowly identified app-data directory at a time. Minimize space without weakening data integrity: use an atomic rename on one filesystem or a journaled copy-verify-delete stream across filesystems.

## Workflow

### 1. Audit before writing

- Identify the exact app bundle, bundle identifier, process names, source directory, destination directory, and destination filesystem.
- Run `scripts/inspect_app.py /absolute/path/App.app`.
- Read [references/compatibility.md](references/compatibility.md) for an unfamiliar app.
- Quit the app and all helper/updater processes. Keep the migration boundary narrower than the whole container or `Application Support` directory.
- Run the read-only audit:

```bash
python3 scripts/migrate_app_data.py audit \
  --source "/exact/current/data" \
  --destination "/Volumes/External/AppData"
```

Report the logical size, largest file, free destination capacity, filesystem, and whether the source is already linked. Never infer deletion authority from a request to analyze or “consider moving” data.

### 2. Prove the integration adapter

- Prefer the app's native storage-location setting.
- For a non-sandboxed app, test whether a symlink works after migration.
- For a sandboxed app, do not rely on a symlink alone. Use a known security-scoped adapter or stop before mutation.
- For Wuthering Waves / 鸣潮, read [references/wuthering-waves.md](references/wuthering-waves.md) and build the included launcher only after the paths are known.

Do not use the bounded-space destructive mode for an unfamiliar sandboxed app until its post-migration access method is proven.

### 3. Select the space strategy

- Use `auto` by default. It chooses an atomic move when source and destination share a filesystem; otherwise it chooses streaming mode.
- Explain that streaming mode temporarily duplicates at most one file, approximately the largest file plus 16 MiB, rather than the full dataset.
- Explain that a cross-volume move cannot have literally zero temporary bytes.
- Obtain explicit confirmation before streaming mode because it removes each source file only after that file is fsynced and SHA-256 verified.
- If the user requires an easy rollback and has enough external space, make a full verified copy first instead of streaming.

### 4. Dry-run, then execute

Run the exact command without `--execute` first:

```bash
python3 scripts/migrate_app_data.py move \
  --source "/exact/current/data" \
  --destination "/Volumes/External/AppData" \
  --strategy auto \
  --link-mode symlink \
  --process-name "ExactProcessName"
```

Re-check the printed paths, process list, filesystem, required capacity, and peak overhead. After explicit approval, execute:

```bash
python3 scripts/migrate_app_data.py move \
  --source "/exact/current/data" \
  --destination "/Volumes/External/AppData" \
  --strategy auto \
  --link-mode symlink \
  --process-name "ExactProcessName" \
  --execute \
  --confirm MOVE_WITHOUT_FULL_BACKUP
```

Use `--link-mode none` only when the app's native configuration already points to the destination. Do not pass `--allow-non-apfs` without explaining the metadata risks and receiving confirmation.

### 5. Verify both data and behavior

Run:

```bash
python3 scripts/migrate_app_data.py verify \
  --source "/exact/current/data" \
  --destination "/Volumes/External/AppData"
```

Then launch the app and verify real reads/writes at the destination, no new permission or sandbox denials, update behavior, and clean shutdown/relaunch. Leave the external disk connected throughout. For interrupted work, read [references/recovery.md](references/recovery.md) and rerun the same move command.

If the app proves incompatible, use the documented `restore` command to move the data back with the same bounded-space algorithm. Dry-run it first and obtain explicit confirmation before `--execute`.

## Safety rules

- Treat `--execute` streaming mode as destructive even though every source file is verified before removal.
- Never target `/`, a home directory, `~/Library`, an entire container root, `/Volumes`, or another broad path.
- Never migrate live databases, lock files, or active sync roots.
- Never delete a migration journal or destination to “start over” while a move is incomplete.
- Keep passwords, tokens, cookies, account databases, and keychain material out of reports and repositories.
- Prefer APFS and preserve ACLs, extended attributes, resource forks, hardlinks, and symlinks.
- Request only the permissions necessary to read the exact source. Do not grant Full Disk Access to the target app as a sandbox workaround.
- Fully quit the app before ejecting its destination volume.

## Included resources

- `scripts/migrate_app_data.py`: audit, bounded-space atomic/streaming move, resume journal, verification, and reverse restore.
- `scripts/inspect_app.py`: read-only bundle, sandbox, process, and standard data-location inspection.
- `scripts/build_wuthering_waves_launcher.sh`: build the source-only security-scoped 鸣潮 launcher.
- `assets/wuthering-waves-launcher/main.swift`: parameterized launcher source; never commit generated local `.app` bundles.
