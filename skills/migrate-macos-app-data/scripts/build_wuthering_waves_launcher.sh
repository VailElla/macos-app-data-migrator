#!/bin/zsh

set -euo pipefail

script_dir="${0:A:h}"
skill_dir="${script_dir:h}"
swift_source="$skill_dir/assets/wuthering-waves-launcher/main.swift"

game_app=""
resources=""
output_app="$HOME/Applications/鸣潮（外接数据）.app"
bundle_id="local.migrate-macos-app-data.wuthering-waves-launcher"
game_bundle_id="com.kurogame.mingchao"
display_name="鸣潮（外接数据）"
warning_delay="65"
replace="false"

usage() {
  print -- "usage: $0 --game-app PATH --resources PATH [options]"
  print -- ""
  print -- "options:"
  print -- "  --output-app PATH      default: $output_app"
  print -- "  --bundle-id ID         default: $bundle_id"
  print -- "  --display-name NAME    default: $display_name"
  print -- "  --warning-delay SEC    default: $warning_delay"
  print -- "  --replace              replace an existing output app"
}

while (( $# > 0 )); do
  case "$1" in
    --game-app)
      game_app="${2:?missing value for --game-app}"
      shift 2
      ;;
    --resources)
      resources="${2:?missing value for --resources}"
      shift 2
      ;;
    --output-app)
      output_app="${2:?missing value for --output-app}"
      shift 2
      ;;
    --bundle-id)
      bundle_id="${2:?missing value for --bundle-id}"
      shift 2
      ;;
    --display-name)
      display_name="${2:?missing value for --display-name}"
      shift 2
      ;;
    --warning-delay)
      warning_delay="${2:?missing value for --warning-delay}"
      shift 2
      ;;
    --replace)
      replace="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print -u2 -- "unknown argument: $1"
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$game_app" || -z "$resources" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -d "$game_app" || "$game_app" != *.app ]]; then
  print -u2 -- "not an app bundle: $game_app"
  exit 2
fi
if [[ ! -d "$resources" ]]; then
  print -u2 -- "resources directory not found: $resources"
  exit 2
fi
if [[ "$output_app" != /* || "$output_app" != *.app || "$output_app" == "/.app" ]]; then
  print -u2 -- "output must be an absolute, scoped .app path"
  exit 2
fi
if [[ "$display_name" == *"/"* || "$display_name" == "." || "$display_name" == ".." ]]; then
  print -u2 -- "display name must be a single safe filename"
  exit 2
fi
if [[ ! "$bundle_id" =~ '^[A-Za-z0-9][A-Za-z0-9.-]+$' ]]; then
  print -u2 -- "bundle ID contains unsupported characters"
  exit 2
fi
if [[ ! "$warning_delay" =~ '^[0-9]+([.][0-9]+)?$' ]] || (( warning_delay < 15 )); then
  print -u2 -- "warning delay must be a number of at least 15 seconds"
  exit 2
fi
if [[ ( -e "$output_app" || -L "$output_app" ) && "$replace" != "true" ]]; then
  print -u2 -- "output already exists; pass --replace after reviewing the exact path: $output_app"
  exit 2
fi
if [[ -d "$output_app" && "$replace" == "true" ]]; then
  existing_bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$output_app/Contents/Info.plist" 2>/dev/null || true)"
  if [[ "$existing_bundle_id" != "$bundle_id" ]]; then
    print -u2 -- "refusing to replace an app with a different bundle ID: ${existing_bundle_id:-unknown}"
    exit 2
  fi
fi

swiftc_path="$(/usr/bin/xcrun --find swiftc)"
build_root="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/migrate-macos-launcher.XXXXXX")"
trap '/bin/rm -R "$build_root"' EXIT

app_bundle="$build_root/$display_name.app"
contents="$app_bundle/Contents"
macos_dir="$contents/MacOS"
resources_dir="$contents/Resources"
binary="$macos_dir/WutheringWavesExternalLauncher"
info_plist="$contents/Info.plist"

/bin/mkdir -p "$macos_dir" "$resources_dir"
"$swiftc_path" \
  -parse-as-library \
  -O \
  -framework AppKit \
  -framework ApplicationServices \
  "$swift_source" \
  -o "$binary"
/bin/chmod 755 "$binary"

/usr/bin/plutil -create xml1 "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string WutheringWavesExternalLauncher" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $bundle_id" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string $display_name" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $display_name" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType string APPL" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 1.0.0" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 13.0" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :NSPrincipalClass string NSApplication" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :NSAccessibilityUsageDescription string Used only to dismiss the harmless folder-open warning after resources load." "$info_plist"
/usr/libexec/PlistBuddy -c "Add :NSRemovableVolumesUsageDescription string Used to launch Wuthering Waves with resources selected from an external volume." "$info_plist"
/usr/libexec/PlistBuddy -c "Add :MigrationGamePath string $game_app" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :MigrationResourcesPath string $resources" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :MigrationGameBundleIdentifier string $game_bundle_id" "$info_plist"
/usr/libexec/PlistBuddy -c "Add :MigrationWarningDelay real $warning_delay" "$info_plist"

game_info="$game_app/Contents/Info.plist"
icon_name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$game_info" 2>/dev/null || true)"
if [[ -n "$icon_name" ]]; then
  icon_path="$game_app/Contents/Resources/$icon_name"
  [[ -f "$icon_path" ]] || icon_path="$game_app/Contents/Resources/$icon_name.icns"
  if [[ -f "$icon_path" ]]; then
    /bin/cp "$icon_path" "$resources_dir/GameIcon.icns"
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string GameIcon" "$info_plist"
  fi
fi

/usr/bin/codesign --force --sign - --identifier "$bundle_id" "$app_bundle"
/bin/mkdir -p "${output_app:h}"
if [[ -e "$output_app" || -L "$output_app" ]]; then
  /bin/rm -R "$output_app"
fi
/usr/bin/ditto "$app_bundle" "$output_app"
/usr/bin/codesign --verify --deep --strict "$output_app"

print -- "Built and verified: $output_app"
print -- "First run: select exactly $resources, then enable this launcher in Accessibility and run it again."
print -- "After any rebuild, macOS may require toggling the Accessibility entry off and on because the ad-hoc signature changed."
