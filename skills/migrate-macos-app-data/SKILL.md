---
name: migrate-macos-app-data
description: Safely copy, verify, and hand off a macOS application bundle or one narrowly scoped application-data directory to an external APFS volume without writing migration payloads or temporary files to the nearly-full internal disk and without deleting source data in Terminal; use for macOS apps, games, media libraries, models, downloads, or Wuthering Waves / 鸣潮 when the user needs Finder-guided removal and a proven native setting, symlink, or security-scoped adapter. 安全地把 macOS 程序或单个明确的数据目录复制、完整校验并交接到外接 APFS 宗卷；适用于内置盘接近无可用空间、禁止终端删除源文件、需要访达手动清理并验证程序仍可运行的场景。
---

# macOS App and Data Migration / macOS 程序与数据迁移

## 中文流程

### 不可破坏的边界

- 把内置盘源程序和源数据视为只读。脚本只提供 `audit`、`copy`、`verify`、`reveal`、`link`，没有删除、移动或恢复源文件的命令。
- 迁移副本、JSON 日志、逐文件临时副本、构建目录和工具缓存全部写在目标外接宗卷。不得在内置盘制作压缩包、镜像、完整备份或构建缓存。
- 不请求或接收管理员密码，不使用 `sudo`，不以终端命令删除、覆盖或重命名内置盘程序/数据。
- 只有“完整校验通过 + 真实启用/读写/重启测试通过”才能声明迁移成功。无法证明兼容时保留源文件并停止。
- 跨宗卷迁移不会增加内置盘中的用户数据占用，但 macOS 可能自行写入少量日志、权限记录或安全书签元数据；不要承诺操作系统层面的绝对零写入。
- 分开记录迁移负载与程序运行时派生缓存。即使复制器和构建器不向内置盘写迁移负载，程序仍可能重新生成着色器、索引或其他缓存；实测增长超出用户可用空间时必须停止，不能宣称“运行时零增长”。
- 真实界面测试前后都要记录内置盘可用空间，并检查 `~/Library/Group Containers/group.com.apple.coreservices.useractivityd/shared-pasteboard/archives`。不要把完整 `.app` 路径作为界面控制目标，也不要用剪贴板方式输入短测试文本；先按精确路径启动外接应用，再用 bundle ID 或显示名称控制界面。若共享剪贴板为外接文件生成大型内置归档，立即停止并报告准确文件与大小，不得自动清理。

### 1. 只读发现准确边界

一次只处理一个 `.app` 或一个大型、可迁移的数据目录。程序和数据都要迁移时，分成两个独立组件执行。

```bash
python3 scripts/inspect_app.py "/absolute/path/App.app" --verify-signature

python3 scripts/migrate_app_data.py audit \
  --source "/exact/source/path" \
  --destination "/Volumes/External/ExactDestination" \
  --kind auto
```

记录 bundle ID、主进程与辅助进程、沙盒状态、精确源路径、目标路径、外接宗卷格式、可用空间和最大文件。不得迁移整个 `~/Library`、整个容器、整个 `Application Support`，也不要把账户、凭据、钥匙串、活动数据库或锁文件当作大型资源一起搬走。

陌生程序先读[兼容性说明（中文）](references/compatibility.zh-CN.md)。优先使用程序原生的存储位置设置；非沙盒程序才考虑软链接；沙盒程序必须有已经证明可用的文件夹授权或专用适配器。不能证明时停止，不复制后删除源数据。

### 2. 预演并复制到外接 APFS

先完全退出程序、更新器和辅助进程。目标上级目录必须已经存在于已挂载的外接 APFS 宗卷。先执行不带 `--execute` 的预演，再逐字符复核路径：

```bash
python3 scripts/migrate_app_data.py copy \
  --source "/exact/source/path" \
  --destination "/Volumes/External/ExactDestination" \
  --kind data \
  --process-name "ExactProcessName"
```

复核无误后才执行同一命令并添加 `--execute`。复制器逐个文件用 SHA-256 校验，保留符号链接、硬链接、ACL、扩展属性和 resource fork；断点状态保存在外接目标旁边。它绝不删除源文件。

### 3. 保留源文件并完整校验

```bash
python3 scripts/migrate_app_data.py verify \
  --source "/exact/source/path" \
  --destination "/Volumes/External/ExactDestination"
```

`verify` 对每个普通文件重新计算源与目标 SHA-256，并比较目录树、类型、权限、ACL、扩展属性、软链接目标和硬链接结构；`.app` 还必须通过 `codesign --verify --deep --strict`。校验时源路径必须仍是实体目录，因此不能提前清理内置盘。

### 4A. 程序 `.app` 的访达交接

直接从外接盘启动已校验的 `.app`，完成登录、读取现有数据、写入测试数据、完全退出、再次启动以及更新器检查。通过后运行：

```bash
python3 scripts/migrate_app_data.py reveal \
  --source "/Applications/App.app" \
  --destination "/Volumes/External/Applications/App.app"
```

脚本只会在访达中定位内置 `.app`。用户确认外接程序实测正常后，亲自在访达中“移到废纸篓”；脚本不代删。`.app` 不建立原路径软链接。

为了在访达中区分副本，默认保留真实 `.app` 文件名，避免未经验证的改名影响更新器；在完整校验后给外接副本写入访达备注 `应用名（外接版）`。准确迁移路径仍按真实文件名记录。访达备注属于实例标识，不参与源与目标的负载元数据比较。

### 4B. 数据目录的访达交接

完整校验后运行 `reveal`。让用户在访达中把原目录重命名为 `原名.internal-backup`；重命名不会复制数据，也不会额外占用等量内置空间。用户明确确认访达操作完成后，预演并建立一个很小的软链接：

```bash
python3 scripts/migrate_app_data.py link \
  --source "/exact/original/data" \
  --destination "/Volumes/External/ExactDestination"

python3 scripts/migrate_app_data.py link \
  --source "/exact/original/data" \
  --destination "/Volumes/External/ExactDestination" \
  --execute
```

如果程序使用原生存储设置或安全作用域适配器，不要建立软链接；按该适配器配置目标。软链接只占极少量文件系统元数据，这是保留原路径兼容性所需的唯一内置盘写入。

### 5. 真实验证后才释放空间

保持 `.internal-backup`，完成真实读取、写入、退出、重启和更新检查，并确认新写入落在外接盘。若失败，按[恢复说明（中文）](references/recovery.zh-CN.md)在访达中移除链接并把备份改回原名。

只有用户确认全部测试通过，才再次用 `reveal --path "/exact/source.internal-backup"` 定位备份，并请用户在访达中移到废纸篓。提醒用户：只有在访达中清倒废纸篓后空间才真正释放；是否执行仍由用户决定。不得用终端代替这一步。迁移不是备份，清倒后外接盘会成为唯一工作副本。

鸣潮使用专用流程：[鸣潮适配器（中文）](references/wuthering-waves.zh-CN.md)。任何删除前都遵循[访达交接（中文）](references/finder-handoff.zh-CN.md)。

## English workflow

### Non-destructive invariants

- Treat the internal source app and source data as read-only. The helper exposes only `audit`, `copy`, `verify`, `reveal`, and `link`; it has no command that deletes, moves, or restores source content.
- Put the migrated copy, JSON journal, per-file partials, build directory, and tool caches on the destination external volume. Do not create an archive, disk image, full backup, or build cache on the internal disk.
- Never request an administrator password, use `sudo`, or delete, overwrite, or rename internal app/data paths from Terminal.
- Declare success only after full verification and a real launch/read/write/relaunch smoke test. If compatibility cannot be proved, retain the source and stop.
- Cross-volume migration adds no user payload to the internal disk. macOS may still create small OS-managed logs, permission records, or security-bookmark metadata, so do not promise literally zero operating-system writes.
- Measure migration payload separately from runtime-derived app caches. Even when the copier and builder keep all migration payload external, the app may regenerate shaders, indexes, or other caches internally; stop if observed growth exceeds the user's available space, and never claim zero runtime growth.
- Record internal free space before and after every real UI test, and inspect `~/Library/Group Containers/group.com.apple.coreservices.useractivityd/shared-pasteboard/archives`. Do not target UI automation by a full `.app` path or use clipboard-backed input for short test text. Launch the exact external path first, then control the UI by bundle ID or display name. If shared pasteboard creates a large internal archive for an external file, stop and report its exact path and size; never clean it automatically.

### 1. Discover one exact boundary read-only

Process one `.app` or one large relocatable data directory at a time. If both program and data are in scope, treat them as two independently verified components.

Run `inspect_app.py` and the `audit` command shown in the Chinese workflow. Record the bundle ID, main/helper processes, sandbox status, exact source and destination, external filesystem, free capacity, and largest file. Never migrate all of `~/Library`, a whole container, or all of `Application Support`; keep credentials, account state, keychain material, live databases, and lock files outside the payload boundary.

For an unfamiliar app, read [Compatibility (English)](references/compatibility.en.md). Prefer an app-native location setting. Consider a symlink only for a non-sandboxed app. Require a proven folder authorization or purpose-built adapter for a sandboxed app. Stop with the source intact if the integration is unproven.

### 2. Dry-run and copy to external APFS

Quit the app, updater, and every helper. The destination parent must already exist on a mounted external APFS volume. Run the `copy` command without `--execute`, review every character of both paths, then repeat the same command with `--execute`.

The copier SHA-256 checks each file, preserves symlinks, hardlinks, ACLs, extended attributes, and resource forks, and stores resumable state beside the external destination. It never deletes source content.

### 3. Fully verify while the source still exists

Run the `verify` command shown above. It re-hashes every regular file and compares the complete tree, entry types, permissions, ACLs, extended attributes, symlink targets, and hardlink topology. An app bundle must also pass strict deep code-signature verification. The source must remain a real directory during this gate.

### 4A. Finder handoff for an `.app`

Launch the verified app directly from the external volume. Test sign-in, existing-data reads, a safe write, full quit, relaunch, and updater behavior. Then run `reveal`; it only selects the internal `.app` in Finder. After the user confirms the external app works, the user moves the internal app to Trash in Finder. Do not create a source-path symlink for an app bundle.

Keep the real `.app` filename unless updater compatibility with renaming has been proven. After full verification, add the Finder comment `App Name (External)` to identify the external copy while preserving its exact path. This instance label is excluded from payload-metadata comparison.

### 4B. Finder handoff for a data directory

After full verification, run `reveal` and ask the user to rename the original directory to `Name.internal-backup` in Finder. Renaming on the same internal filesystem does not duplicate its data. After the user explicitly confirms Finder has finished, dry-run and execute `link`. If the app uses a native location setting or a security-scoped adapter, configure that instead of creating a symlink.

A symlink consumes only a small amount of filesystem metadata; it is the only intentional internal write when original-path compatibility is required.

### 5. Release internal space only after behavior verification

Keep `.internal-backup` through real read/write/quit/relaunch/update testing and verify that new writes land externally. If anything fails, follow [Recovery (English)](references/recovery.en.md) to remove the link and restore the backup name in Finder.

Only after the user confirms every test should `reveal --path "/exact/source.internal-backup"` select the backup for the user to move to Trash in Finder. Explain that space is not released until the user empties Trash in Finder; that decision remains with the user. Never replace the handoff with a Terminal deletion command. Migration is not backup, and the external disk becomes the sole working copy afterward.

Use the dedicated [Wuthering Waves adapter (English)](references/wuthering-waves.en.md) for 鸣潮 and follow [Finder handoff (English)](references/finder-handoff.en.md) before any removal.

## Included resources / 随附资源

- `scripts/migrate_app_data.py`: non-destructive audit, external-only copy state, full verification, Finder reveal, and post-Finder link creation.
- `scripts/inspect_app.py`: read-only bundle, signature, entitlement, sandbox, process, and common-location inspection.
- `scripts/build_wuthering_waves_launcher.sh`: builds the source-only security-scoped 鸣潮 launcher entirely on the selected target volume.
- `assets/wuthering-waves-launcher/main.swift`: bilingual, parameterized launcher source. Never commit a generated local `.app`.
