# macOS App & Data Migrator Skill

一个中英双语的 Codex Skill，用于在内置盘几乎没有可用空间时，把一个明确的 macOS 程序或程序数据目录迁移到外接 APFS，同时保留可验证的无损回退点。

A bilingual Codex Skill for migrating one precisely scoped macOS application or app-data directory to external APFS when the internal disk has almost no free space, while retaining a verifiable lossless rollback point.

## 中文说明

### 这个项目解决什么

传统“移动”脚本往往会边复制边删除源文件，或者先在内置盘生成压缩包/临时副本。这个 Skill 使用更严格的五段式流程：

```text
只读审计 → 只向外接盘复制 → 源与目标完整校验 → 访达手动交接 → 真实运行验收
```

- 复制与校验阶段把内置源程序和源数据视为只读；迁移器没有源删除、源移动或自动恢复命令，后续交接只通过访达完成。
- 迁移日志、临时副本、Swift 构建目录和缓存全部位于目标外接盘。
- 每个普通文件都做 SHA-256，完整校验还比较目录树、权限、ACL、扩展属性、resource fork、软链接和硬链接。`.app` 根目录上脚本明确列出的 macOS 实例属性（包括 `com.apple.provenance`）属于实例元数据，允许源目标不同；应用包内部条目只允许目标端新增的受保护 `com.apple.provenance`，若源端已有则源目标必须完全一致。普通数据与其他所有 xattr 仍严格比较。
- `.app` 额外执行严格深层代码签名校验。
- 删除内置 `.app` 时，工具只在访达中定位并由用户亲自移到废纸篓。数据目录默认在用户明确授权后，由 Codex 通过访达移到废纸篓但不清空；用户明确偏好时才改用同级 `.internal-backup`。建立原路径软链接前，必须提供准确的 Finder 恢复路径并由工具用源快照、inode 和设备号证明回滚副本仍是原目录。
- 不请求管理员密码、不使用 `sudo`，不用终端命令删除内置程序或数据。
- 对沙盒程序不假设软链接可用；没有原生位置设置或已验证适配器时停止并保留源文件。

### 接近 0 空间的含义

迁移不会把用户负载或工具临时文件写入内置盘。目标外接盘必须有完整最终容量和约 64 MiB 工具余量。若程序数据需要保留原路径，最终会建立一个只占极少元数据的软链接。

macOS 自己仍可能写少量日志、TCC 权限记录、安全书签或偏好设置，因此“操作系统绝对 0 字节写入”无法诚实保证；本项目保证的是不主动在内置盘创建迁移负载、完整副本或构建缓存。

程序自身也可能在真实启动时重新生成着色器、索引等派生缓存。它们不是迁移副本，但会真实占用内置空间；发布前和每次迁移验收都应单独测量并披露，不能把“迁移负载外置”等同于“程序运行时零增长”。

迁移不是备份：在访达中永久删除废纸篓里的内置源后，外接副本会成为唯一工作副本。本项目能防止迁移流程丢失数据，不能防止之后的外接盘物理损坏；重要数据仍应有独立备份。

### 为什么迁移器不会自动删除源文件

数据一致不等于程序兼容。完整校验通过后，仍需真实测试启动、读取、写入、退出、重启和更新器。保留内置源文件直到行为测试完成，才可能同时满足“数据无丢失”和“迁移后正常运行”。

对于数据目录，默认在用户明确授权后由 Codex 通过访达把准确源目录移到废纸篓但不清空，再由迁移器建立软链接；测试失败时，先在访达中移除链接，再对废纸篓中的源执行“放回原处”。只有用户明确偏好同级备份时，才把源改名为 `.internal-backup` 并在失败时恢复原名。两种回滚都无需重新复制整份数据。

### 支持的组件

- 可直接从外接宗卷运行的 macOS `.app`
- 程序原生支持指定位置的媒体库、下载、模型、游戏资源等大型目录
- 已实测支持软链接的非沙盒程序数据
- 有专用文件夹授权适配器的沙盒程序
- 鸣潮 / Wuthering Waves 的源码级安全作用域启动器
- Docker Desktop 稀疏虚拟磁盘的官方原生位置迁移与降级证明边界

默认拒绝整个 `~/Library`、整个容器、活动数据库、同步根目录、非 APFS 目标以及未明确识别为外接的目标宗卷。

### 安装与使用

将仓库克隆到任意位置，然后把 Skill 目录链接到 Codex：

```bash
ln -s "/absolute/path/macos-app-data-migrator/skills/migrate-macos-app-data" \
  "$HOME/.codex/skills/migrate-macos-app-data"
```

在 Codex 中调用：

```text
$migrate-macos-app-data 帮我把这个程序及其大型数据迁移到外接 APFS；内置盘接近 0 空间，所有交接都使用访达、必须先取得我的明确授权，并且绝不自动清空废纸篓。
```

Skill 会先只读审计，再逐步停在每个真实审查门槛。不要从 README 中复制示例路径直接执行；所有路径都必须来自当前机器的只读发现。

### 鸣潮适配器

鸣潮 macOS 版受 App Sandbox 约束，普通软链接无法单独授予游戏访问外接资源的权限。仓库包含一个从 Swift 源码构建的小型启动器：用户通过系统文件夹选择器授权外接 `Resources`，启动器把安全作用域交给游戏，并在资源句柄建立后关闭无害提示。

构建必须显式指定外接输出路径；编译缓存和临时目录同样位于该外接宗卷。生成的 `.app` 含本机绝对路径和 ad-hoc 签名，已被忽略，不能提交到 GitHub。

真实 APFS 跨宗卷迁移的故障链、校验证据与回滚状态见[鸣潮 APFS 跨宗卷迁移验收记录](docs/cases/2026-07-29-wuthering-waves-cross-volume-migration.md)。

### Docker Desktop 适配器

`Docker.raw` 是逻辑大小可远大于实际分配的稀疏虚拟磁盘。只读审计会同时报告逻辑数据、源端实际分配、稀疏文件数和无法可靠检测空洞的文件数；通用 `ditto` 复制会展开空洞，因此迁移器在执行前安全停止。底层文件系统不支持可靠空洞检测时也会失败关闭，不把未知结果当作非稀疏文件。请改用 Docker Desktop 官方 Disk image location 流程，并按 [Docker Desktop 稀疏虚拟磁盘说明](skills/migrate-macos-app-data/references/docker-desktop.zh-CN.md) 完成停机、回滚核对、实际分配和容器读写/重启验收。跳过 SHA-256 不能获得 `verified` 状态。

### 开发验证

```bash
python3 -m py_compile \
  skills/migrate-macos-app-data/scripts/migrate_app_data.py \
  skills/migrate-macos-app-data/scripts/inspect_app.py

zsh -n skills/migrate-macos-app-data/scripts/build_wuthering_waves_launcher.sh
python3 -m unittest discover -s tests -v

macos_sdk_path="$(xcrun --sdk macosx --show-sdk-path)"
xcrun swiftc -sdk "$macos_sdk_path" -parse-as-library -typecheck \
  -framework AppKit \
  -framework ApplicationServices \
  skills/migrate-macos-app-data/assets/wuthering-waves-launcher/main.swift
```

测试使用一次性的外接 APFS RAM 宗卷承载目标副本、迁移日志、partial、构建目录和编译缓存；内置临时目录中只有很小的测试源夹具，并且不会接触当前真实迁移结果。测试覆盖真实 xattr/ACL 复制与篡改拒绝、软链接祖先路径拒绝、访达废纸篓/同级备份交接和目标文件损坏；生产迁移器本身不提供删除源文件的命令或内部宗卷绕过参数。

## English documentation

### What this project solves

Conventional “move” tools often delete source files while copying or stage an archive/temporary duplicate internally. This Skill uses five explicit gates:

```text
read-only audit → external-only copy → full source/destination verification → Finder handoff → live acceptance
```

- The internal source app/data remains read-only during copy and verification. The migrator has no source-delete, source-move, or automatic-restore command; the later handoff occurs only through Finder.
- Journals, partial copies, Swift build directories, and caches stay on the target external volume.
- Every regular file is SHA-256 checked; full verification also compares the tree, permissions, ACLs, extended attributes, resource forks, symlinks, and hardlinks. Script-listed macOS instance attributes on the `.app` root (including `com.apple.provenance`) are instance metadata and may differ between source and destination. For app descendants, only a destination-only protected `com.apple.provenance` is allowed; when the source already has it, source and destination must match exactly. Data migrations and every other xattr remain strict.
- An `.app` additionally receives strict deep code-signature verification.
- For an internal `.app`, the helper only reveals the exact item and the user moves it to Trash. For a data directory, after explicit authorization Codex normally moves the exact source to Trash through Finder without emptying Trash; a sibling `.internal-backup` is used only when the user explicitly prefers it. Before `link`, provide the exact recovery path and the explicit Finder-handoff attestation; the helper compares the saved source snapshot, inode, and device so a missing source cannot be mistaken for permanent deletion.
- It never requests an administrator password, uses `sudo`, or deletes internal app/data paths from Terminal.
- It does not assume a symlink crosses an app sandbox. Without a native location setting or tested adapter, it stops with the source intact.

### What “near-zero free space” means

No user payload or tool temporary data is intentionally written internally. The external volume needs the final dataset capacity plus roughly 64 MiB of tool headroom. Original-path compatibility may require one tiny symlink on the internal filesystem.

macOS may still write small logs, TCC records, security bookmarks, or preferences. Literal zero-byte OS writes cannot honestly be guaranteed; the enforceable guarantee is that this project creates no migration payload, full duplicate, or build cache internally.

The app itself may also regenerate derived shaders, indexes, or other caches during a real launch. These are not migration copies, but they consume real internal space and must be measured and disclosed separately; external-only migration payload does not mean zero runtime growth.

Migration is not backup. After the internal source in Trash is permanently deleted, the external copy becomes the sole working copy. This project protects the transition from data loss, not a later physical failure of the external disk; important data still needs an independent backup.

### Why the migrator never deletes source content automatically

Byte identity is not application compatibility. After full verification, the app still needs real launch, read, write, quit, relaunch, and updater testing. Keeping the internal source through that gate is what makes data-loss protection and post-migration operation compatible.

For a data directory, after explicit authorization Codex normally moves the exact source to Trash through Finder without emptying Trash, and the helper then creates a symlink. If testing fails, remove the link in Finder and choose Put Back for the original source. Use a sibling `.internal-backup` only when the user explicitly prefers it; that fallback restores the original name. Neither recovery path recopies the full dataset.

### Supported components

- macOS `.app` bundles that permit external-volume execution
- Large libraries, downloads, models, or game resources with an app-native location setting
- Non-sandboxed app data with a proven symlink integration
- Sandboxed data with a purpose-built folder-authorization adapter
- The included source-level Wuthering Waves / 鸣潮 security-scoped launcher
- Docker Desktop sparse VM disks through Docker's supported app-native relocation and explicit degraded-assurance boundaries

The default policy rejects all of `~/Library`, whole containers, live databases, sync roots, non-APFS destinations, and volumes that are not explicitly identified as external.

### Install and invoke

Clone the repository anywhere, then link its Skill directory into Codex using the command in the Chinese section. Invoke it with:

```text
$migrate-macos-app-data Move this app and its large data to external APFS. Internal free space is nearly zero; use Finder for every handoff, require my explicit authorization, and never empty Trash automatically.
```

The Skill begins read-only and pauses at every real review gate. Never copy example paths blindly; derive all paths from live read-only discovery.

### Wuthering Waves adapter

The macOS game is App Sandbox constrained, so a plain symlink does not independently grant external-resource access. The included Swift launcher asks the user to authorize the exact external `Resources` directory, passes its security scope to the game, and dismisses the harmless folder warning after resource handles are established.

The builder requires an explicit external output. Its compiler cache and temporary directory stay on that same external volume. A generated `.app` embeds local absolute paths and an ad-hoc signature, is ignored by Git, and must never be published.

See the [real APFS cross-volume migration case](docs/cases/2026-07-29-wuthering-waves-cross-volume-migration.md) for the observed failure chain, verification evidence, and rollback state.

### Docker Desktop adapter

`Docker.raw` is a sparse VM disk whose logical size can greatly exceed physical allocation. Read-only audit reports logical payload, source allocation, sparse-file count, and files whose holes cannot be classified reliably. Because the generic `ditto` path allocates holes, the migrator stops before execution and routes the task to Docker Desktop's supported Disk image location workflow. It also fails closed when the source filesystem cannot provide reliable hole detection, rather than treating an unknown result as non-sparse. Follow [Docker Desktop sparse VM-disk migration](skills/migrate-macos-app-data/references/docker-desktop.en.md) for quiescence, rollback checks, allocation review, and container read/write/restart acceptance. Declining SHA-256 never produces `verified` state.

### Development validation

Run the commands in the Chinese section. The test suite puts destination copies, journals, partials, build directories, and compiler caches on a disposable external APFS RAM volume. Only small source fixtures live in the internal temporary directory, and no live migration is touched. The suite covers source immutability, dry-run behavior, copy resume, full hashing, real xattr/ACL preservation and tamper rejection, hardlinks, symlinks, canonical launcher paths, destination tampering, Finder handoff, launcher build/signing, app-copy signature verification, and the absence of source-deletion or internal-volume-override CLI commands.

## Repository layout / 仓库结构

```text
skills/migrate-macos-app-data/
├── SKILL.md
├── agents/openai.yaml
├── assets/wuthering-waves-launcher/main.swift
├── references/                 # paired 中文 / English guides
└── scripts/
    ├── inspect_app.py
    ├── migrate_app_data.py
    └── build_wuthering_waves_launcher.sh
tests/
docs/cases/                    # anonymized real migration records / 匿名化真实迁移记录
REVIEW_CHECKLIST.md
```

## Review before publication / 发布前审查

Please work through [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md). The repository should not be pushed or published until the owner explicitly confirms the review.

## License

[MIT](LICENSE)
