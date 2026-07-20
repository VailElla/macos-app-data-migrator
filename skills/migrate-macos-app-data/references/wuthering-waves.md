# Wuthering Waves / 鸣潮 adapter

Use this adapter only for the macOS build with bundle identifier `com.kurogame.mingchao`. Discover live paths instead of copying these examples blindly.

## Known storage boundary

- Default sandbox container: `~/Library/Containers/com.kurogame.mingchao`
- Large payload observed in current releases: `Data/Library/Client/Saved/Resources`
- Preserve the rest of `Saved` internally because it contains small configuration and state directories.
- Locate the installed game app by bundle identifier; it may live in `/Applications` or on another mounted volume.

The game is sandboxed. A correct symlink from `Saved/Resources` to an external volume is not sufficient by itself: the game process can receive `Sandbox: deny` for the external target.

## Build the security-scoped launcher

After migration and symlink creation, build the source-only launcher into the user's Applications directory:

```bash
skills/migrate-macos-app-data/scripts/build_wuthering_waves_launcher.sh \
  --game-app "/absolute/path/鸣潮.app" \
  --resources "/Volumes/ExternalVolume/WutheringWaves/Resources"
```

Do not commit the generated `.app`; it embeds local paths and an ad-hoc signature.

On first run:

1. Select the exact external `Resources` directory in the macOS folder picker. The launcher stores a security-scoped bookmark.
2. Enable only the launcher in **System Settings → Privacy & Security → Accessibility**, then launch it again.
3. Leave the harmless “cannot open Resources as a document” warning visible. The launcher waits 65 seconds by default so the game can establish external file handles, then dismisses it automatically.

Do not grant Full Disk Access to the game or Terminal as a workaround. The launcher needs folder authorization and Accessibility only.

## Verify the live process

Before the warning closes, confirm that the game has opened files below the external directory. After it closes, confirm that the game remains alive, the external open-file count increases, and no new sandbox denials mention the external path.

Useful read-only checks:

```bash
game_pid="$(pgrep -x Client-Mac-Shipping)"
lsof -p "$game_pid" | grep -F "/Volumes/ExternalVolume/WutheringWaves/Resources"
log show --last 3m --style compact \
  --predicate 'eventMessage CONTAINS[c] "WutheringWaves"' | grep -Ei 'deny|sandbox'
```

If the launcher is rebuilt, its ad-hoc code hash changes. Toggle its Accessibility entry off and on, or remove and re-add it, before testing again.
