---
name: migrate-macos-app-data
description: Safely copy, verify, and hand off a macOS application bundle or one narrowly scoped application-data directory to external APFS, route Docker Desktop sparse VM-disk relocation to its app-native workflow, or guide an explicitly authorized consolidation of adjacent containers on one external APFS disk through verified staging and UUID-locked destructive gates. Use for macOS apps, games, media libraries, models, downloads, Docker.raw or sparse virtual disks, Wuthering Waves / 鸣潮, and external APFS partition/container consolidation when strict verification and recoverable handoff are required. 安全迁移 macOS 程序或明确数据目录，把 Docker Desktop 稀疏虚拟磁盘导向应用原生流程，或通过已校验临时分区和 UUID 锁定删除门整合外接 APFS 容器。
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
- 真实界面测试前后都要记录内置盘可用空间，并检查 `~/Library/Group Containers/group.com.apple.coreservices.useractivityd/shared-pasteboard/archives`。测试前记录现有条目的路径、inode、大小与时间，作为不可触碰的基线。不要把完整 `.app` 路径作为界面控制目标，也不要用剪贴板方式输入短测试文本；先按精确路径启动外接应用，再用 bundle ID 或显示名称控制界面。测试后只处理本轮新生成、且能由测试时间窗口和迁移对象大小证明归属的归档：先用 `lsof` 确认未被占用，再自动通过访达移到系统废纸篓。不得处理基线条目、强制结束 `useractivityd`、永久删除或自动清倒废纸篓；新归档仍被占用或归属不明确时必须停止并报告。

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

若任务是把同一块外接磁盘上的整个 APFS 容器经临时分区合并、扩容和改名，不要把宗卷根目录交给迁移脚本，也不要给脚本增加删除容器能力；改用独立的[外接 APFS 容器整合流程（中文）](references/apfs-container-consolidation.zh-CN.md)。该流程要求每次破坏性动作前按 UUID 重新解析目标，并覆盖 USB 重置、`ditto` 漏掉普通 `._` 文件、冲突归档、provenance 明示接受和最终扩容。

若发现 Docker Desktop、`Docker.raw`、虚拟机磁盘或稀疏文件，先读 [Docker Desktop 稀疏虚拟磁盘流程（中文）](references/docker-desktop.zh-CN.md)。通用复制器会在真实稀疏空洞上安全停止，因为 `ditto` 会展开空洞；优先使用 Docker 官方磁盘位置迁移。用户跳过 SHA-256 时不得声称完整校验成功，也不得给工具增加绕过参数。

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
  --destination "/Volumes/External/ExactDestination" \
  --process-name "ExactProcessName"
```

`verify` 对每个普通文件重新计算源与目标 SHA-256，并比较目录树、类型、权限、ACL、扩展属性、软链接目标和硬链接结构；`.app` 根目录上脚本明确列出的 macOS 实例属性（包括 `com.apple.provenance`）属于实例元数据，允许源目标不同；应用包内部条目只允许目标端新增的受保护 `com.apple.provenance`，若源端已有则源目标必须完全一致。普通数据与其他所有 xattr 保持严格比较。`.app` 还必须通过 `codesign --verify --deep --strict`。校验开始前和写入 `verified` 状态前都会复查日志中记录的程序、更新器和辅助进程仍已退出。新建复制日志必须至少记录一个相关进程；旧日志可在此处追加一个或多个 `--process-name` 后修复，缺少进程名时安全停止。校验时源路径必须仍是实体目录，因此不能提前清理内置盘。

### 4A. 程序 `.app` 的访达交接

直接从外接盘启动已校验的 `.app`，完成登录、读取现有数据、写入测试数据、完全退出、再次启动以及更新器检查。通过后运行：

```bash
python3 scripts/migrate_app_data.py reveal \
  --source "/Applications/App.app" \
  --destination "/Volumes/External/Applications/App.app"
```

脚本只会在访达中定位内置 `.app`。用户确认外接程序实测正常后，亲自在访达中“移到废纸篓”；脚本不代删。`.app` 不建立原路径软链接。

交接回复必须用文本提供一个直接指向内置 `.app` 的可点击本地文件链接，例如 `[在访达中选择内置 App.app](/Applications/App.app)`；不能只链接 `/Applications` 父目录或只让用户自己寻找。链接目标必须是本轮已核对的精确源路径。若当前客户端不能打开本地文件链接，再以 `reveal` 作为后备定位方式。链接只负责选择目标，仍由用户亲自在访达中移到废纸篓。

为了在访达中区分副本，默认保留真实 `.app` 文件名，避免未经验证的改名影响更新器；在完整校验后给外接副本写入访达备注 `应用名（外接版）`。准确迁移路径仍按真实文件名记录。`.app` 根目录的访达备注及脚本列出的 macOS 实例属性（包括 `com.apple.provenance`）不参与负载元数据比较；应用内部条目只允许目标端新增的受保护 `com.apple.provenance` 这一项实例例外，源端已有 provenance 和其他全部 xattr 仍须严格一致。普通数据没有这项例外。

### 4B. 数据目录的访达交接

完整校验后运行 `reveal`。默认在用户明确授权后，由 Codex 通过访达界面把准确的内置源目录移到系统废纸篓，但绝不清空废纸篓；操作前后都要核对源路径，确保外接副本仍可用。这样会立即腾出原路径，同时保留“放回原处”的回滚能力。若用户明确偏好同级备份，再改用 `原名.internal-backup` 的可回滚同卷改名。两种交接都不能改用终端 `mv` 或删除命令。确认原路径已腾出后，找到访达废纸篓中的准确恢复项目（或用户明确选择的同级 `.internal-backup`），再用源快照、inode 和设备号证明它仍是原目录。预演并建立一个很小的软链接：

```bash
python3 scripts/migrate_app_data.py link \
  --source "/exact/original/data" \
  --destination "/Volumes/External/ExactDestination" \
  --recovery-path "/exact/Finder/Trash/or/sibling-backup" \
  --finder-handoff-verified

python3 scripts/migrate_app_data.py link \
  --source "/exact/original/data" \
  --destination "/Volumes/External/ExactDestination" \
  --recovery-path "/exact/Finder/Trash/or/sibling-backup" \
  --finder-handoff-verified \
  --execute
```

`--recovery-path` 必须是访达废纸篓中的准确恢复项目，或用户明确选择的同级 `.internal-backup`；`--finder-handoff-verified` 是对访达完成授权交接的明确确认。工具会比较该路径与日志中的源快照、inode 和设备号，交接收据不匹配时拒绝建立链接。如果程序使用原生存储设置或安全作用域适配器，不要建立软链接；按该适配器配置目标。软链接只占极少量文件系统元数据，这是保留原路径兼容性所需的唯一内置盘写入。

### 5. 真实验证后才释放空间

保持废纸篓中的内置源（或用户选择的 `.internal-backup`），完成真实读取、写入、退出、重启和更新检查，并确认新写入落在外接盘。若失败，按[恢复说明（中文）](references/recovery.zh-CN.md)在访达中移除链接并对废纸篓源执行“放回原处”，或把同级备份改回原名。

只有用户确认全部测试通过，才说明可以永久删除废纸篓中的内置源；清空废纸篓必须在动作发生时再次取得用户确认，且不得自动清空其他内容。若使用同级备份，则先通过 `reveal --path "/exact/source.internal-backup"` 定位并移到废纸篓。不得用终端代替这些步骤。迁移不是备份，永久删除后外接盘会成为唯一工作副本。

鸣潮使用专用流程：[鸣潮适配器（中文）](references/wuthering-waves.zh-CN.md)。任何删除前都遵循[访达交接（中文）](references/finder-handoff.zh-CN.md)。

## English workflow

### Non-destructive invariants

- Treat the internal source app and source data as read-only. The helper exposes only `audit`, `copy`, `verify`, `reveal`, and `link`; it has no command that deletes, moves, or restores source content.
- Put the migrated copy, JSON journal, per-file partials, build directory, and tool caches on the destination external volume. Do not create an archive, disk image, full backup, or build cache on the internal disk.
- Never request an administrator password, use `sudo`, or delete, overwrite, or rename internal app/data paths from Terminal.
- Declare success only after full verification and a real launch/read/write/relaunch smoke test. If compatibility cannot be proved, retain the source and stop.
- Cross-volume migration adds no user payload to the internal disk. macOS may still create small OS-managed logs, permission records, or security-bookmark metadata, so do not promise literally zero operating-system writes.
- Measure migration payload separately from runtime-derived app caches. Even when the copier and builder keep all migration payload external, the app may regenerate shaders, indexes, or other caches internally; stop if observed growth exceeds the user's available space, and never claim zero runtime growth.
- Record internal free space before and after every real UI test, and inspect `~/Library/Group Containers/group.com.apple.coreservices.useractivityd/shared-pasteboard/archives`. Before testing, snapshot every existing entry's path, inode, size, and timestamp as an untouchable baseline. Do not target UI automation by a full `.app` path or use clipboard-backed input for short test text. Launch the exact external path first, then control the UI by bundle ID or display name. After testing, handle only archives created during the current run whose ownership is proven by the test window and migrated-object size: confirm with `lsof` that each file is unused, then move it to system Trash through Finder automatically. Never touch baseline entries, terminate `useractivityd`, permanently delete files, or empty Trash automatically. Stop and report any new archive that remains open or cannot be attributed safely.

### 1. Discover one exact boundary read-only

Process one `.app` or one large relocatable data directory at a time. If both program and data are in scope, treat them as two independently verified components.

Run `inspect_app.py` and the `audit` command shown in the Chinese workflow. Record the bundle ID, main/helper processes, sandbox status, exact source and destination, external filesystem, free capacity, and largest file. Never migrate all of `~/Library`, a whole container, or all of `Application Support`; keep credentials, account state, keychain material, live databases, and lock files outside the payload boundary.

For an unfamiliar app, read [Compatibility (English)](references/compatibility.en.md). Prefer an app-native location setting. Consider a symlink only for a non-sandboxed app. Require a proven folder authorization or purpose-built adapter for a sandboxed app. Stop with the source intact if the integration is unproven.

When the task is whole-container merge, resize, and rename on one external disk through temporary staging, do not pass a volume root to the migrator or add container-deletion verbs to it. Follow the separate [External APFS container consolidation workflow (English)](references/apfs-container-consolidation.en.md). It resolves destructive targets by UUID immediately before use and covers USB resets, ordinary `._` files omitted by `ditto`, conflict archives, explicit provenance acceptance, and the final resize.

For Docker Desktop, `Docker.raw`, VM disks, or sparse files, first read [Docker Desktop sparse VM-disk migration (English)](references/docker-desktop.en.md). The generic copier stops safely on real sparse holes because `ditto` allocates them; prefer Docker's supported disk-location relocation. If the user declines SHA-256, never claim full verification or add a bypass flag.

### 2. Dry-run and copy to external APFS

Quit the app, updater, and every helper. The destination parent must already exist on a mounted external APFS volume. A new journal must include at least one `--process-name` for the app, updater, or helper; repeat the same flag for each relevant process. Run the `copy` command without `--execute`, review every character of both paths, then repeat the same command with `--execute`.

The copier SHA-256 checks each file, preserves symlinks, hardlinks, ACLs, extended attributes, and resource forks, and stores resumable state beside the external destination. It never deletes source content.

### 3. Fully verify while the source still exists

Run the `verify` command shown above. It re-hashes every regular file and compares the complete tree, entry types, permissions, ACLs, extended attributes, symlink targets, and hardlink topology. Script-listed macOS instance attributes on the `.app` root (including `com.apple.provenance`) are instance metadata and may differ between source and destination. For app descendants, only a destination-only protected `com.apple.provenance` is allowed; when the source already has it, source and destination must match exactly. Data migrations and every other xattr remain strict. An app bundle must also pass strict deep code-signature verification. A new copy journal must record at least one app, updater, or helper process; add one or more `--process-name` values here when repairing a legacy journal, and stop safely when none are available. The recorded processes are checked before verification and again before committing `verified` state. The source must remain a real directory during this gate.

### 4A. Finder handoff for an `.app`

Launch the verified app directly from the external volume. Test sign-in, existing-data reads, a safe write, full quit, relaunch, and updater behavior. Then run `reveal`; it only selects the internal `.app` in Finder. After the user confirms the external app works, the user moves the internal app to Trash in Finder. Do not create a source-path symlink for an app bundle.

The handoff response must provide a clickable local-file link that targets the exact verified internal `.app`, for example `[Select the internal App.app in Finder](/Applications/App.app)`. Do not link only to the `/Applications` parent or make the user locate the bundle manually. Use `reveal` as a fallback when the client cannot open local-file links. The link selects the target; the user still moves it to Trash in Finder.

Keep the real `.app` filename unless updater compatibility with renaming has been proven. After full verification, add the Finder comment `App Name (External)` to identify the external copy while preserving its exact path. The Finder comment and listed macOS instance attributes on the `.app` root (including `com.apple.provenance`) are excluded from payload-metadata comparison. Within app descendants, the only instance exception is destination-only protected `com.apple.provenance`; source-present provenance and every other xattr must still match exactly. Data migrations have no such exception.

### 4B. Finder handoff for a data directory

After full verification, run `reveal`. By default, after explicit user authorization, use the Finder UI to move the exact internal source directory to system Trash without emptying Trash; verify the exact source path before and after and keep the external copy available. This frees the original path while preserving Finder's Put Back rollback. Use a reversible same-volume rename to `Name.internal-backup` only when the user explicitly prefers a sibling backup. Never substitute Terminal `mv` or a deletion command for either handoff. Before `link`, provide the exact recovery path and the explicit Finder-handoff attestation; the helper compares the saved source snapshot, inode, and device before creating a symlink. If the app uses a native location setting or a security-scoped adapter, configure that instead of creating a symlink.

A symlink consumes only a small amount of filesystem metadata; it is the only intentional internal write when original-path compatibility is required.

### 5. Release internal space only after behavior verification

Keep the internal source in Trash (or the user-selected `.internal-backup`) through real read/write/quit/relaunch/update testing and verify that new writes land externally. If anything fails, follow [Recovery (English)](references/recovery.en.md) to remove the link and use Put Back, or restore the sibling backup name in Finder.

Only after the user confirms every test should you explain that the internal source in Trash may be permanently deleted. Emptying Trash requires a fresh confirmation at action time and must never silently remove unrelated Trash contents. For a sibling backup, use `reveal --path "/exact/source.internal-backup"` before moving it to Trash. Never replace the handoff with a Terminal deletion command. Migration is not backup, and the external disk becomes the sole working copy after permanent deletion.

Use the dedicated [Wuthering Waves adapter (English)](references/wuthering-waves.en.md) for 鸣潮 and follow [Finder handoff (English)](references/finder-handoff.en.md) before any removal.

## Included resources / 随附资源

- `scripts/migrate_app_data.py`: non-destructive audit, external-only copy state, full verification, Finder reveal, and post-Finder link creation.
- `scripts/inspect_app.py`: read-only bundle, signature, entitlement, sandbox, process, and common-location inspection.
- `scripts/build_wuthering_waves_launcher.sh`: builds the source-only security-scoped 鸣潮 launcher entirely on the selected target volume.
- `assets/wuthering-waves-launcher/main.swift`: bilingual, parameterized launcher source. Never commit a generated local `.app`.
- `references/apfs-container-consolidation.zh-CN.md` and `.en.md`: UUID-locked, fully verified external APFS staging, merge, rename, reference-repair, and final-resize procedure.
- `references/docker-desktop.zh-CN.md` and `.en.md`: app-native Docker VM-disk relocation, sparse-allocation auditing, runtime proof, rollback, and degraded-assurance boundaries.
