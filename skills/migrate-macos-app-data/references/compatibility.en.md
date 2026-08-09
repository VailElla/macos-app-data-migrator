# macOS App and Data Migration Compatibility

## Prove how the app will find the new location first

Migrating identical bytes and migrating a working application are separate problems. Full hashes prove copy identity; only a real launch, read, write, quit, and relaunch test proves compatibility.

| Component | Preferred integration | When it fits | Risk that must be tested |
|---|---|---|---|
| `.app` inside a DMG | Mount read-only and copy directly to external APFS | The image contains a directly runnable app that needs no privileged installer | DMG integrity, mounted-source identity, destination signature, Gatekeeper, split user configuration, and updater behavior |
| `.app` bundle | Launch directly from external APFS | The standalone app permits removable-volume execution | Signature, Gatekeeper, login items, and updater behavior at the new path |
| Large data directory | App-native location setting | The app exposes a library, model, download, or game-content location | Whether all large data classes move and the setting survives relaunch |
| Non-sandboxed data | Original-path symlink | The app and updater accept an external resolved target | Updates replacing the link and disconnection creating an empty directory |
| Sandboxed data | Folder picker or security-scoped adapter | The mechanism is tested for that exact app | The sandbox may reject the external target even when Finder follows a symlink |

Run:

```bash
python3 scripts/inspect_app.py "/absolute/path/App.app" --verify-signature
```

Treat `Sandboxed: yes` as an unproven-symlink warning. Prefer the app's settings. If there is no native mechanism or tested adapter, keep the source intact and stop.

## A direct DMG install is not an internal-app handoff

An app inside a DMG is a transient read-only mounted source. Follow [Install directly from a DMG to external APFS](dmg-install.en.md): run `hdiutil verify`, prefer read-only `diskutil image attach`, and pass the mounted app to the generic copier with `--kind app`. Finish full `verify` and the platform-appropriate system-policy assessment before ejecting the image. When the journal has not reached `status: verified`, neither a destination signature nor a successful launch substitutes for source/destination verification.

When no internal app existed, do not perform the app-migration Finder removal handoff. Preferences, plugins, login state, and small configuration normally remain under the user profile and must be recorded and accepted separately from the external app bundle. Stop on a `.pkg`, installer script, system extension, or privileged installation requirement and use the publisher's supported installer workflow instead of pretending it is a copyable app.

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

- Production migration accepts only a volume `diskutil` explicitly identifies as external APFS; the production CLI exposes no internal-volume override.
- exFAT, NTFS, network filesystems, and cloud drives can lose ACLs, extended attributes, resource forks, hardlinks, permissions, or case semantics and are rejected by default.
- Quit the app, launcher, updater, and helpers. A new `copy` journal must include at least one `--process-name` for the discovered app/updater/helper processes, and the copier re-checks those names periodically.
- Require a stable external mount path. Stop immediately on disconnection; never continue into an internal directory that happens to have the same name.
- Quit the app before ejecting the volume. Re-test signatures, links/location settings, and real I/O after major updates.

## Success gate

Every condition is required:

1. While the source still exists, verify the full tree, SHA-256 of every regular file, metadata, ACLs, extended attributes, symlinks, and hardlinks.
2. Require strict deep signature verification for an `.app`.
3. For a DMG source, validate the image, finish full source/destination verification before detach, and assess the external target with Gatekeeper.
4. Launch the external copy, read existing content, and complete a safe write.
5. Quit fully, relaunch successfully, and confirm new writes land externally.
6. Check updater, login-item, plugin, helper, and sandbox behavior.

Do not guide the user to remove the internal source app or data until every condition passes.
