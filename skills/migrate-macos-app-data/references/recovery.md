# Interrupted migration recovery

The migration journal is stored beside the destination as:

```text
.<destination-name>.migrate-macos-app-data.json
```

It contains exact source and destination paths, initial tree statistics, strategy, link mode, progress counters, and hardlink mappings. It contains no file contents or credentials.

## Resume rules

- Re-run the exact same `move` command with the same strategy and link mode.
- The script removes only temporary files bearing its own migration ID.
- If a destination file is already complete while its source still exists, the script hashes both; it deletes the source only when they match.
- If paths, strategy, link mode, or a pre-existing destination conflict with the journal, stop and inspect instead of overriding them.
- Never delete the journal during an incomplete move.

## Failure interpretation

- **App or helper still running:** quit it and rerun; no data should have moved before this check.
- **Destination out of space:** free destination capacity, keep both paths mounted, and rerun.
- **SHA-256 mismatch or source changed during copy:** stop. Check disk health and ensure no process writes to the source.
- **Unsupported special file:** use an app-native migration feature or a full filesystem-aware copy; do not force streaming mode.
- **External disk disconnected:** reconnect it at the same mount path and rerun. Do not create a replacement directory on the internal disk with the same path.
- **App cannot run after a completed move:** keep the external data and journal intact. Diagnose the integration adapter; for sandboxed apps, a plain symlink is often the cause.

After recovery, run the `verify` command and a live app smoke test. Treat journal verification as necessary but not sufficient for application compatibility.

## Restore to the original volume

If compatibility cannot be solved and the original volume has enough free space, reverse the migration with the same bounded-space algorithm. First run a dry plan, then obtain explicit approval and execute:

```bash
python3 scripts/migrate_app_data.py restore \
  --source-link "/exact/original/data" \
  --data "/Volumes/External/AppData" \
  --process-name "ExactProcessName"

python3 scripts/migrate_app_data.py restore \
  --source-link "/exact/original/data" \
  --data "/Volumes/External/AppData" \
  --process-name "ExactProcessName" \
  --execute \
  --confirm RESTORE_TO_ORIGINAL
```

Do not manually remove the original link or partial reverse-migration journal. Re-run the same restore command after an interruption.
