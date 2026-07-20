#!/bin/zsh

set -euo pipefail

script_dir="${0:A:h}"
program_name="${0:t}"
skill_dir="${script_dir:h}"
swift_source="$skill_dir/assets/wuthering-waves-launcher/main.swift"

game_app=""
resources=""
output_app=""
bundle_id="local.migrate-macos-app-data.wuthering-waves-launcher"
game_bundle_id="com.kurogame.mingchao"
display_name="鸣潮（外接数据）"
warning_delay="65"
build_root=""

usage() {
  print -- "用法 / Usage: $program_name --game-app PATH --resources PATH --output-app PATH [选项 / options]"
  print -- ""
  print -- "必填 / Required:"
  print -- "  --game-app PATH       鸣潮应用路径 / Wuthering Waves app path"
  print -- "  --resources PATH      已迁移的外接 Resources / migrated external Resources"
  print -- "  --output-app PATH     外接盘上的新启动器路径 / new launcher path on external volume"
  print -- ""
  print -- "选项 / Options:"
  print -- "  --bundle-id ID        默认 / default: $bundle_id"
  print -- "  --game-bundle-id ID   默认 / default: $game_bundle_id"
  print -- "  --display-name NAME   默认 / default: $display_name"
  print -- "  --warning-delay SEC   默认 / default: $warning_delay"
  print -- ""
  print -- "已有输出不会被覆盖；请在访达中自行处理旧启动器。"
  print -- "Existing output is never replaced; manage an old launcher manually in Finder."
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
    --game-bundle-id)
      game_bundle_id="${2:?missing value for --game-bundle-id}"
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print -u2 -- "未知参数 / Unknown argument: $1"
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$game_app" || -z "$resources" || -z "$output_app" ]]; then
  usage >&2
  exit 2
fi
if [[ "$game_app" != /* || "$resources" != /* ]]; then
  print -u2 -- "游戏和 Resources 必须使用绝对路径 / Game and Resources must use absolute paths"
  exit 2
fi
if [[ ! -d "$game_app" || -L "$game_app" || "$game_app" != *.app ]]; then
  print -u2 -- "不是实体应用包 / Not a real app bundle: $game_app"
  exit 2
fi
if [[ ! -d "$resources" || -L "$resources" ]]; then
  print -u2 -- "找不到实体 Resources 目录 / Real Resources directory not found: $resources"
  exit 2
fi
if [[ "${resources:t}" != "Resources" ]]; then
  print -u2 -- "必须选择准确的 Resources 目录 / Select the exact directory named Resources: $resources"
  exit 2
fi
if [[ "$output_app" != /* || "$output_app" != *.app || "$output_app" == "/.app" ]]; then
  print -u2 -- "输出必须是明确的绝对 .app 路径 / Output must be an absolute, scoped .app path"
  exit 2
fi
if [[ "$display_name" == *"/"* || "$display_name" == "." || "$display_name" == ".." ]]; then
  print -u2 -- "显示名称必须是安全的单一文件名 / Display name must be one safe filename"
  exit 2
fi
if [[ ! "$bundle_id" =~ '^[A-Za-z0-9][A-Za-z0-9.-]+$' ]]; then
  print -u2 -- "Bundle ID 含不支持字符 / Bundle ID contains unsupported characters"
  exit 2
fi
if [[ ! "$game_bundle_id" =~ '^[A-Za-z0-9][A-Za-z0-9.-]+$' ]]; then
  print -u2 -- "游戏 Bundle ID 含不支持字符 / Game bundle ID contains unsupported characters"
  exit 2
fi
if [[ ! "$warning_delay" =~ '^[0-9]+([.][0-9]+)?$' ]] || (( warning_delay < 15 )); then
  print -u2 -- "延迟必须是不小于 15 秒的数字 / Warning delay must be at least 15 seconds"
  exit 2
fi
if [[ -e "$output_app" || -L "$output_app" ]]; then
  print -u2 -- "拒绝覆盖已有输出；如需移除请在访达中手动处理 / Refusing to replace existing output; manage it manually in Finder: $output_app"
  exit 2
fi

output_parent="${output_app:h}"
if [[ ! -d "$output_parent" || -L "$output_parent" ]]; then
  print -u2 -- "输出上级目录必须已存在且不能是软链接 / Output parent must already exist and not be a symlink: $output_parent"
  exit 2
fi

game_app_real="${game_app:A}"
resources_real="${resources:A}"
output_parent_real="${output_parent:A}"
output_app_real="$output_parent_real/${output_app:t}"
if [[ "$game_app" != "$game_app_real" ]]; then
  print -u2 -- "游戏路径必须是无软链接祖先的真实路径 / Game path must be canonical and contain no symlink ancestor: $game_app"
  exit 2
fi
if [[ "$resources" != "$resources_real" ]]; then
  print -u2 -- "Resources 路径必须是无软链接祖先的真实路径 / Resources path must be canonical and contain no symlink ancestor: $resources"
  exit 2
fi
if [[ "$output_parent" != "$output_parent_real" ]]; then
  print -u2 -- "输出上级目录必须是无软链接祖先的真实路径 / Output parent must be canonical and contain no symlink ancestor: $output_parent"
  exit 2
fi
if [[ "$output_app_real" == "$game_app_real" || "$output_app_real" == "$game_app_real"/* || "$output_app_real" == "$resources_real" || "$output_app_real" == "$resources_real"/* ]]; then
  print -u2 -- "输出不能位于游戏或资源源目录内部 / Output must not be inside the game or source Resources"
  exit 2
fi

actual_game_bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$game_app/Contents/Info.plist" 2>/dev/null || true)"
if [[ "$actual_game_bundle_id" != "$game_bundle_id" ]]; then
  print -u2 -- "游戏 Bundle ID 不匹配 / Game bundle ID mismatch: expected $game_bundle_id, found ${actual_game_bundle_id:-unknown}"
  exit 2
fi

volume_internal=""
volume_filesystem=""
if [[ -x /usr/sbin/diskutil ]]; then
  output_device="$(/bin/df -P "$output_parent" | /usr/bin/awk 'END {print $1}')"
  volume_plist="$(/usr/sbin/diskutil info -plist "$output_device" 2>/dev/null || true)"
  if [[ -n "$volume_plist" ]]; then
    volume_internal="$(print -rn -- "$volume_plist" | /usr/bin/plutil -extract Internal raw -o - - 2>/dev/null || true)"
    volume_filesystem="$(print -rn -- "$volume_plist" | /usr/bin/plutil -extract FilesystemType raw -o - - 2>/dev/null || true)"
  fi
fi
if [[ "$volume_internal" != "false" ]]; then
  print -u2 -- "未确认输出位于外接宗卷 / Output is not confirmed on an external volume: $output_parent"
  exit 2
fi
if [[ "$volume_filesystem" != "apfs" ]]; then
  print -u2 -- "外接输出宗卷必须是 APFS / External output volume must be APFS: ${volume_filesystem:-unknown}"
  exit 2
fi

resources_internal=""
resources_filesystem=""
if [[ -x /usr/sbin/diskutil ]]; then
  resources_device="$(/bin/df -P "$resources" | /usr/bin/awk 'END {print $1}')"
  resources_plist="$(/usr/sbin/diskutil info -plist "$resources_device" 2>/dev/null || true)"
  if [[ -n "$resources_plist" ]]; then
    resources_internal="$(print -rn -- "$resources_plist" | /usr/bin/plutil -extract Internal raw -o - - 2>/dev/null || true)"
    resources_filesystem="$(print -rn -- "$resources_plist" | /usr/bin/plutil -extract FilesystemType raw -o - - 2>/dev/null || true)"
  fi
fi
if [[ "$resources_internal" != "false" ]]; then
  print -u2 -- "未确认 Resources 位于外接宗卷 / Resources is not confirmed on an external volume: $resources"
  exit 2
fi
if [[ "$resources_filesystem" != "apfs" ]]; then
  print -u2 -- "Resources 宗卷必须是 APFS / Resources volume must be APFS: ${resources_filesystem:-unknown}"
  exit 2
fi
/usr/bin/codesign --verify --deep --strict "$game_app"

cleanup_external_build() {
  # Only remove this invocation's generated build root on the already-verified
  # target volume. Never point cleanup at the game, Resources, or internal data.
  if [[ -n "$build_root" && "$build_root" == "$output_parent"/.migrate-launcher-build.* && -d "$build_root" && ! -L "$build_root" ]]; then
    /bin/rm -R -- "$build_root"
  fi
}
trap cleanup_external_build EXIT INT TERM

build_root="$(/usr/bin/mktemp -d "$output_parent/.migrate-launcher-build.XXXXXX")"
module_cache="$build_root/module-cache"
tool_cache="$build_root/tool-cache"
app_bundle="$build_root/$display_name.app"
contents="$app_bundle/Contents"
macos_dir="$contents/MacOS"
resources_dir="$contents/Resources"
binary="$macos_dir/WutheringWavesExternalLauncher"
info_plist="$contents/Info.plist"

/bin/mkdir -p "$module_cache" "$tool_cache" "$macos_dir" "$resources_dir"

export TMPDIR="$tool_cache"
export TMP="$tool_cache"
export TEMP="$tool_cache"
export XDG_CACHE_HOME="$tool_cache"
export CLANG_MODULE_CACHE_PATH="$module_cache"
export SWIFT_MODULECACHE_PATH="$module_cache"

swiftc_path="$(/usr/bin/xcrun --find swiftc)"
"$swiftc_path" \
  -parse-as-library \
  -O \
  -module-cache-path "$module_cache" \
  -framework AppKit \
  -framework ApplicationServices \
  "$swift_source" \
  -o "$binary"
/bin/chmod 755 "$binary"

/usr/bin/plutil -create xml1 "$info_plist"
/usr/bin/plutil -insert CFBundleExecutable -string WutheringWavesExternalLauncher "$info_plist"
/usr/bin/plutil -insert CFBundleIdentifier -string "$bundle_id" "$info_plist"
/usr/bin/plutil -insert CFBundleName -string "$display_name" "$info_plist"
/usr/bin/plutil -insert CFBundleDisplayName -string "$display_name" "$info_plist"
/usr/bin/plutil -insert CFBundlePackageType -string APPL "$info_plist"
/usr/bin/plutil -insert CFBundleVersion -string 1 "$info_plist"
/usr/bin/plutil -insert CFBundleShortVersionString -string 1.1.0 "$info_plist"
/usr/bin/plutil -insert LSMinimumSystemVersion -string 13.0 "$info_plist"
/usr/bin/plutil -insert LSUIElement -bool true "$info_plist"
/usr/bin/plutil -insert NSPrincipalClass -string NSApplication "$info_plist"
/usr/bin/plutil -insert NSAccessibilityUsageDescription -string "仅用于关闭资源加载后的无害文件夹提示。 Used only to dismiss the harmless folder warning after resources load." "$info_plist"
/usr/bin/plutil -insert NSRemovableVolumesUsageDescription -string "用于从外接宗卷启动鸣潮资源。 Used to launch Wuthering Waves resources from an external volume." "$info_plist"
/usr/bin/plutil -insert MigrationGamePath -string "$game_app" "$info_plist"
/usr/bin/plutil -insert MigrationResourcesPath -string "$resources" "$info_plist"
/usr/bin/plutil -insert MigrationGameBundleIdentifier -string "$game_bundle_id" "$info_plist"
/usr/bin/plutil -insert MigrationWarningDelay -float "$warning_delay" "$info_plist"

game_info="$game_app/Contents/Info.plist"
icon_name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$game_info" 2>/dev/null || true)"
if [[ -n "$icon_name" ]]; then
  icon_path="$game_app/Contents/Resources/$icon_name"
  [[ -f "$icon_path" ]] || icon_path="$game_app/Contents/Resources/$icon_name.icns"
  if [[ -f "$icon_path" ]]; then
    /usr/bin/ditto "$icon_path" "$resources_dir/GameIcon.icns"
    /usr/bin/plutil -insert CFBundleIconFile -string GameIcon "$info_plist"
  fi
fi

/usr/bin/codesign --force --sign - --identifier "$bundle_id" "$app_bundle"
/usr/bin/ditto --rsrc --extattr --acl "$app_bundle" "$output_app"
/usr/bin/codesign --verify --deep --strict "$output_app"

print -- "已在目标宗卷完成构建与签名校验 / Built and verified on the target volume: $output_app"
print -- "首次运行请选择准确目录 / On first run, select exactly: $resources"
print -- "随后在 系统设置 → 隐私与安全性 → 辅助功能 中启用此启动器，再运行一次。"
print -- "Then enable this launcher in System Settings → Privacy & Security → Accessibility and run it again."
print -- "重建后的 ad-hoc 签名会变化，macOS 可能要求关闭再开启该辅助功能条目。"
print -- "After rebuilding, macOS may require toggling the Accessibility entry because the ad-hoc signature changed."
