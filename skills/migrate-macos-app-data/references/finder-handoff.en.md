# Finder Handoff and Internal-Space Release

## Mandatory rules

- During the removal/rename handoff, the migration helper may run only `open -R` to select the exact path in Finder; it never substitutes a Terminal command for the user's Finder action.
- For a data directory, after explicit user authorization Codex normally moves the source to Trash through Finder without emptying Trash and verifies that the original path is free. Permanent deletion remains a separate confirmation gate. Use a reversible sibling rename only when the user explicitly prefers it.
- Never request an administrator password, run `sudo`, or use `rm`, `mv`, `ditto --delete`, or any Terminal command to delete, overwrite, or replace an internal app/data path.
- Path confirmation and deletion confirmation are separate gates. Ask for the latter only after full verification and app behavior tests pass.

## `.app` bundle

1. Keep the internal `.app` and launch the verified external copy.
2. Test sign-in, reads, a safe write, quit, relaunch, and updater behavior.
3. Run `reveal` to select the internal `.app` in Finder.
4. Show the source and destination again and explain that the app is unavailable while the external disk is disconnected.
5. After explicit confirmation, the user chooses Move to Trash in Finder.
6. Do not create an original-path symlink for an `.app`.

## Data directory

1. After full verification, run `reveal` to select the original directory in Finder.
2. After explicit authorization, Codex moves the source to Trash through Finder without emptying Trash and never substitutes a Terminal command. Use `Name.internal-backup` only when the user explicitly prefers a sibling backup.
3. Confirm that the original path is free and the trashed source still supports Put Back (or that the sibling backup remains), then dry-run `link`.
4. Execute `link --execute` only after the user reviews both exact paths. It creates only a symlink.
5. Keep the backup through real read, write, full quit, relaunch, and updater tests.
6. Confirm that new writes land externally and no new large internal directory appears.
7. After the user confirms success, explain that the internal source in Trash may be permanently deleted. Emptying Trash requires a fresh action-time confirmation and must not silently remove unrelated items.
8. For a sibling backup, run `reveal --path "/exact/Name.internal-backup"` before moving it to Trash.

Migration is not backup. After Trash is emptied, the external disk is the sole working copy. A later physical disk failure is outside the migration-integrity guarantee, so important data needs an independent backup.

## Confirmation wording

Before releasing the final internal space, say clearly:

> The external copy passed full verification, and the app passed read, write, quit, and relaunch tests. Finder now selects the internal backup `[exact path]`; the external destination is `[exact path]`. Moving it to Trash makes rollback depend on the external copy. Please confirm whether you will perform this action in Finder.

Without that explicit confirmation, retain the backup and end the run.
