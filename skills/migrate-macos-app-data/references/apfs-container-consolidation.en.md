# External APFS Container Consolidation

Use this workflow to consolidate adjacent APFS containers on one external GPT disk by staging one container in a temporary APFS partition at the physical end of the disk. This is a low-freedom operator procedure, not a new destructive command in `migrate_app_data.py`.

## Hard boundary

- Operate only on a physical disk proven to be external, GPT, and APFS. Stop for the system disk, Fusion Drive, RAID, unknown encryption state, or unclear topology.
- A temporary partition on the same physical disk is staging, not backup. Important data still needs an independent copy on another physical device.
- `diskutil` identifiers such as `diskN` and `diskNsM` can change after disconnects, USB resets, or re-enumeration. Resolve current identifiers from the recorded container, volume, and physical-store UUIDs immediately before every delete, resize, or rename.
- Container deletion is irreversible. Delete the current source container only after full verification and explicit user acceptance of every disclosed residual difference.
- `com.apple.provenance` is not a general ignore rule. Data comparison remains strict. If the only residual difference is protected provenance that cannot be restored, report exact paths and counts and require explicit user acceptance before crossing the deletion gate.
- Do not pass a volume root to `migrate_app_data.py`. It intentionally accepts one `.app` or one narrowly scoped data directory. Consolidate and verify top-level components independently, and handle ordinary root files individually.

## 0. Lock the topology read-only

Quit apps, launchers, synchronizers, and indexers that can write to either volume. Preserve this evidence:

```bash
diskutil list
diskutil apfs list
diskutil info -plist "/Volumes/Source"
diskutil info -plist "/Volumes/Destination"
diskutil apfs resizeContainer <destination-container-current-id> limits
lsof +D "/Volumes/Source"
```

Record whether the physical disk is external, partition starts and order, container/volume/physical-store UUIDs, mount points, capacity, used space, resize limits, and snapshots. Size staging above the actual source payload plus metadata overhead and margin; APFS used-space figures do not replace an inventory of top-level paths.

Write an action map naming the container to retain, stage, and delete and the exact contiguous extent expected after each action. Stop if adjacency is not proven.

## 1. Create temporary APFS staging and copy

Create the temporary APFS partition only in free space proven to be at the physical end of the disk. Recheck the whole-disk identity and physical-disk UUID immediately before changing the partition map. Never paste an example placeholder as a command.

Run `audit`, `copy --execute`, and `verify` for each top-level component. Keep the source quiescent and place journals and partials on staging. Copy ordinary volume-root files individually with SHA-256. Classify before excluding system-generated content such as `.Spotlight-V100`, `.fseventsd`, `.TemporaryItems`, `.Trashes`, and installer staging.

Compare the complete relative path sets even when a directory copier reports success. `ditto` can treat some ordinary filenames beginning with `._` as AppleDouble sidecars and omit them. Classify every missing path, copy it from the exact source path, and verify its hash; never ignore the prefix categorically.

After a cross-volume copy, restore every source-present non-provenance xattr, then replay directory permissions, ACLs, timestamps, and xattrs from deepest directory to root. Run full-tree verification again.

## 2. Stop safely after a USB reset

On `Device not configured`, a disappearing volume, I/O errors, or a changed device number, stop all writes:

1. Rerun `diskutil list`, `diskutil apfs list`, and `diskutil info -plist`; resolve new dynamic identifiers from the recorded UUIDs.
2. Run `fsck_apfs -n` where an unmounted or read-only check is appropriate, then reread and rehash the failed file.
3. Recheck every mount point and destination guard.
4. If an old journal is bound to changed `st_dev`, inode, mount point, or volume identity, restart from the current trusted snapshot. Do not edit the journal to bypass identity checks or continue with an old `diskN`.

## 3. Delete the old container and enlarge the retained container

Immediately before deletion, resolve and display:

- physical-disk UUID and external status;
- container UUID to delete, all of its volume UUIDs, and mount points;
- retained container UUID and its adjacent free extent;
- staging container UUID, verification result, and current readability;
- any writers reported by `lsof`.

Only after the user authorizes that exact UUID may the operator perform the equivalent of:

```bash
diskutil apfs deleteContainer <verified-old-container-current-id>
diskutil apfs resizeContainer <verified-destination-container-current-id> 0
```

The first resize can grow only to the staging-partition boundary. Re-enumerate immediately afterward and never assume identifiers stayed constant.

## 4. Merge staging into the retained volume

Before copying, inventory relative paths, entry types, and SHA-256 for regular files:

- Same path, type, and content: retain and verify.
- Same path but different type or content: copy the destination version into a conflict archive on the destination volume, verify the archive, then apply the approved “staging source wins” rule to the final path.
- Destination-only: retain only when it is on the destination allowlist.
- Staging-only: copy to the final path.

Do not substitute approximate file counts for path-set comparison. After the merge, supplement omitted ordinary `._` files, restore non-provenance xattrs, replay directory metadata deepest-first, and fully verify hashes and metadata against staging. Keep the conflict archive until final behavior testing is complete.

## 5. Rename and repair references

Renaming a volume changes its display name but does not repair absolute paths. After assigning the final volume name, re-enumerate and repair every functional reference:

- symlinks containing `/Volumes/OldName/...`;
- launchers, scripts, project settings, and environment variables;
- native storage settings, security-scoped bookmarks, and recent projects;
- login items, automations, and updater configuration.

Build a new launcher for the final path instead of overwriting an old launcher. Old launchers may still embed the old absolute path; after testing, move them to Trash through Finder only.

## 6. Final deletion gate

All conditions must pass before deleting staging:

- Full hash, type, ACL, xattr, symlink, and hardlink verification of the staged source passed. Every provenance exception has an exact inventory and explicit user acceptance.
- The final volume passed real read/write, project open/save, full app quit/relaunch, and updater checks, and the user confirmed critical apps. Do not repeat tests the user already completed and confirmed.
- New writes land on the final volume and no functional reference still uses the old absolute path.
- Appropriate read-only filesystem checks pass for final and staging volumes, with no active writers.

Resolve the staging container again by UUID, obtain user authorization for that exact container, delete it, and expand the retained container to the physical end of the disk. Preserve final `diskutil list`, `diskutil apfs list`, `df`, filesystem-check, and verification summaries.

Before deleting the old source container, stopping preserves the original layout. After deleting the old source but before deleting staging, staging is the recovery source. After staging is deleted, this workflow provides no same-disk rollback.
