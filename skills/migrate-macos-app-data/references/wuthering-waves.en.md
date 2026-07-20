# Wuthering Waves macOS External-Resources Adapter

Use this adapter only for the macOS app whose bundle ID is `com.kurogame.mingchao`. Discover live paths read-only every time; do not copy example paths blindly.

## Known boundary

- Default sandbox container: `~/Library/Containers/com.kurogame.mingchao`
- Large payload commonly found at: `Data/Library/Client/Saved/Resources`
- Migrate only the exact `Resources` directory. Keep the other small configuration, state, and log directories under `Saved` internal.
- The game `.app` may be in `/Applications` or on a mounted volume; locate it by bundle ID and verify its signature.

Wuthering Waves is App Sandbox constrained. Even when Finder follows an original-path symlink correctly, the game may receive `Sandbox: deny` for the external target. A plain symlink is therefore not the complete adapter.

## Safe migration order

1. Fully quit Wuthering Waves and helpers such as `Client-Mac-Shipping`.
2. Run `audit`, `copy --execute`, and `verify` for the exact `Resources`. Keep the source unchanged through full verification.
3. If moving the game `.app`, treat it as a separate `--kind app` component, verify its signature, and smoke-test external launch.
4. Pre-create the launcher parent directory on external APFS.
5. Run the builder below. Every Swift cache, temporary file, and generated artifact stays on the `--output-app` volume.

```bash
skills/migrate-macos-app-data/scripts/build_wuthering_waves_launcher.sh \
  --game-app "/absolute/path/Wuthering Waves.app" \
  --resources "/Volumes/External/WutheringWaves/Resources" \
  --output-app "/Volumes/External/Applications/Wuthering Waves (External Data).app"
```

The builder never overwrites an existing `.app`. Ask the user to manage an old launcher in Finder; do not add a Terminal replacement/deletion step. The generated app embeds local absolute paths and has an ad-hoc signature, so never commit it to a public repository.

Legacy launchers from earlier manual migrations may compile paths into the binary and lack the new `Migration...` Info.plist keys. Never overwrite them in place or assume an automatic upgrade. Build to a new output name, complete every live test, and let the user manage the legacy launcher in Finder.

## First run

1. Open the generated external-data launcher.
2. Select only the exact external `Resources` in the system folder picker. The launcher saves a security-scoped bookmark.
3. Enable only this launcher in System Settings → Privacy & Security → Accessibility, then run it again.
4. Leave the harmless “cannot open Resources as a document” warning visible. The default 65-second delay lets the game establish external file handles before the launcher presses OK.

Do not grant Full Disk Access to the game or Terminal as a workaround. The launcher needs authorization for the user-selected removable folder and Accessibility only. macOS writes a small security bookmark, TCC record, and preferences internally; this unavoidable OS metadata is not migration payload.

## Live acceptance

- The game process launches and remains alive.
- The game holds open files below external `Resources` before and after the warning closes.
- Sign-in, resource loading, entering a scene, one safe settings write, full quit, and relaunch succeed.
- New or updated large resources land externally, with no large `Resources` recreated under internal `Saved`.
- Recent logs contain no new sandbox denial for the external resource path.

These read-only diagnostic commands need no administrator password and must never be chained to deletion commands:

```bash
game_pid="$(pgrep -x Client-Mac-Shipping)"
lsof -p "$game_pid" | grep -F "/Volumes/External/WutheringWaves/Resources"
log show --last 3m --style compact \
  --predicate 'eventMessage CONTAINS[c] "WutheringWaves"' | grep -Ei 'deny|sandbox'
```

Rebuilding changes the ad-hoc code hash, so macOS may require toggling the Accessibility entry. Only after the live gates pass should the Finder handoff handle internal `Resources.internal-backup` or the internal game `.app`.
