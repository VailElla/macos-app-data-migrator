# Non-destructive Recovery and Interruption Handling

The journal sits beside the external destination:

```text
.<destination-name>.migrate-macos-app-data.json
```

It records exact paths, the starting source-tree snapshot, progress, hardlink mappings, and SHA-256 values. It contains no file payload, password, or credential.

## Interrupted copy

- The migration helper has not deleted or renamed the source app/data. It remains the primary recovery point.
- Reconnect the same external volume, confirm its mount path and volume UUID, and repeat the exact same `copy ... --execute` command.
- Completed destination files are re-hashed. Matching files are skipped; differing files are never overwritten. The helper may rewrite only a partial bearing its own migration ID inside the external destination.
- Never create a same-named directory while the mount is absent, and do not delete the journal to “start over.”

## Verification failure

- Stop immediately and retain both source and external copy.
- Confirm that the app and helpers are fully quit; inspect source changes, external-disk health, and connection stability.
- A SHA-256, metadata, ACL, extended-attribute, or signature failure blocks Finder cleanup.
- If the user eventually abandons the external copy, the user may manage those external generated files in Finder. Never substitute a Terminal deletion of the internal source.

## Finder handoff completed, link not yet created

For the default Trash handoff, cancel by selecting the exact original data directory in Trash and choosing Put Back. Confirm that the original path is restored before launching the app. If the user selected a sibling backup instead, rename `Name.internal-backup` to its original name in Finder. No source data must be copied back from external storage in either case.

## Symlink created, app behavior test failed

1. Quit the app and every helper.
2. Reveal the original path in Finder; the user moves the symlink to Trash.
3. By default, select the original data directory in Trash and choose Put Back. If a sibling backup was used, rename `Name.internal-backup` to the original name.
4. Launch against the internal source and confirm recovery.
5. Retain the external copy and journal while diagnosing. A sandbox denial commonly means a plain symlink is insufficient.

This rollback requires neither an administrator password nor a Terminal deletion command.

## External `.app` fails while the internal app remains

Launch the internal `.app` again. Do not move or delete it. If the user abandons the external copy, the user can manage that external `.app` in Finder.

## Source or sibling backup already in Trash

- Trash not emptied: the user chooses Put Back in Finder, then follows the symlink rollback steps.
- Trash emptied: preserve the only external copy. Returning it internally requires enough final capacity and a separately reviewed copy workflow; this skill does not pretend to provide lossless restoration into insufficient space.

## External disk disconnected

Quit the app immediately. Reconnect the original volume and confirm the same mount path and UUID. Do not let the app write to the original symlink location while the volume is absent, because it may create a new large internal directory.
