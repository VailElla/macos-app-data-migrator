# 鸣潮 APFS 跨宗卷迁移验收记录

日期：2026-07-29

状态：迁移、运行验收、根级状态目录备份和旧源宗卷删除均已完成

用途：记录一次真实的“外接 APFS 宗卷 → 同一外接磁盘上的另一个 APFS 宗卷”迁移，以及过程中暴露的工具边界。本文使用匿名卷名，不能把示例路径直接复制到其他机器。

## 任务与边界

目标是把鸣潮 macOS 版的 `Resources` 从：

```text
/Volumes/<source-volume>/Resources
```

迁移到：

```text
/Volumes/<target-volume>/MingchaoResources/Resources
```

游戏本体继续位于另一个外接 APFS 宗卷。迁移期间：

- 数据复制与运行验收期间，源 `Resources` 始终保留，未删除、覆盖或重命名。
- 只迁移准确的 `Resources`，没有迁移整个沙盒容器或整个 `Saved`。
- 复制日志、目标数据、Swift 构建目录和缓存全部位于目标外接宗卷。
- 旧源宗卷直到完整运行验收和根级状态目录备份校验后仍作为回滚副本保留。
- 永久删除旧 APFS 宗卷作为单独的不可恢复动作，仅在用户于动作时明确授权后执行。

## 只读发现

发现结果：

| 项目 | 结果 |
| --- | --- |
| 源与目标文件系统 | APFS |
| 设备位置 | 同一块外接 SSD 上的不同 APFS 容器 |
| 文件数 | 661 |
| 目录数 | 335 |
| 软链接数（迁移负载内） | 0 |
| 逻辑大小 | 95.68 GiB |
| 最大文件 | 43.11 GiB |
| 目标迁移前可用空间 | 159.88 GiB |
| 迁移后预计余量 | 约 64 GiB |

沙盒容器中的兼容入口原本是一个指向旧外接宗卷的软链接：

```text
$HOME/Library/Containers/com.kurogame.mingchao/Data/Library/Client/Saved/Resources
  -> /Volumes/<source-volume>/Resources
```

旧启动器的 `MigrationResourcesPath` 也嵌入了旧路径，因此仅复制数据不足以完成迁移。

## 复制与数据校验

对准确源、目标路径先执行 `audit` 和 `copy` 预演，再执行 `copy --execute`。复制器报告：

```text
Copy complete; source remains untouched
```

首次正式 `verify` 在 `.DS_Store` 停止。调查发现两个 macOS 跨宗卷实例属性问题：

1. 目标端有 90 个源端不存在的受保护 `com.apple.provenance`。普通用户执行 `xattr -d` 后该属性仍立即保留。
2. macOS 重写了 992 个目标条目的 `com.apple.quarantine`。这些属性可以写回源端的准确值。

处理结果：

- 992 个目标 quarantine 已逐条恢复为源值。
- 除 90 个 destination-only provenance 外，目录树、类型、权限、ACL、其他扩展属性和硬链接拓扑差异为 0。
- 对 661 个文件重新执行诊断性全量 SHA-256，全部一致。
- 用户明确接受了这 90 个受保护 provenance 作为本次迁移的目标实例属性例外。

重要限制：当前正式数据验证规则仍要求 xattr 双向严格一致，因此迁移日志没有被标准 `verify` 标记为 `verified`。本次是经过用户明确批准的现场例外，不应静默推广为数据迁移的默认规则。项目后续需要决定是否增加一个受控、可审计、仅允许 destination-only protected provenance 的数据验证政策。

## 启动器构建问题与修复

首次生成的启动器无法在当前系统运行。现场检查发现：

```text
Info.plist LSMinimumSystemVersion = 13.0
Mach-O LC_BUILD_VERSION minos     = 28.0
当前系统                             = macOS 27.0
```

原因是 Swift 工具链默认目标随已安装 SDK 变为 macOS 28.0，而构建器只写了 Info.plist，没有给 `swiftc` 指定 deployment target。

本次在构建命令中加入：

```zsh
-target "$(uname -m)-apple-macosx13.0"
```

修复后验证：

```text
codesign --verify --deep --strict = 通过
Mach-O minos                      = 13.0
MigrationResourcesPath           = 新目标 Resources
```

两个在修复前生成、最低版本为 macOS 28.0 的本机启动器副本仍留在目标宗卷，未通过终端删除；最终可用的是修复后新建且未覆盖旧文件的启动器。

## 权限与软链接切换

首次运行新启动器时：

1. 通过 macOS 文件夹选择器只授权准确的新目标 `Resources`。
2. 在“系统设置 → 隐私与安全性 → 辅助功能”中确认新启动器条目已开启。
3. 没有给游戏或终端授予“完全磁盘访问权限”。

第一次运行仍未建立新目标文件句柄。根因是沙盒容器里的兼容软链接仍指向旧宗卷，而新启动器只授权了新目标路径。

在确认游戏和启动器完全退出、记录旧目标且新目标存在后，将这个小型可逆软链接切换为：

```text
$HOME/Library/Containers/com.kurogame.mingchao/Data/Library/Client/Saved/Resources
  -> /Volumes/<target-volume>/MingchaoResources/Resources
```

旧 `Resources` 实体目录没有删除，因此失败时仍可把链接指回旧目标。

## 真实运行验收

切换软链接后，从修复后的外接启动器精确启动游戏。验收证据：

| 验收项 | 结果 |
| --- | --- |
| 游戏进程启动并保持运行 | 通过 |
| 登录与现有角色数据读取 | 通过 |
| 进入实际世界场景 | 通过 |
| 游戏持有新目标资源句柄 | 通过，最终观测 287 个 |
| 游戏持有旧源路径句柄 | 0 |
| 启动器退出后游戏继续运行 | 通过 |
| 配置及资源侧安全写入 | 通过 |
| 完全退出 | 通过 |
| 只经新启动器再次启动 | 通过 |
| 明确的 `Sandbox: deny` | 未发现 |

测试期间观察到新目标中的 `.DS_Store`、`MountLauncher.txt`、`MountResource.txt` 等出现预期写入；沙盒容器中的偏好与本地数据库也更新，证明读写链路可用。

最终干净重启的时间点：

```text
11 秒：2 个新目标资源句柄，旧路径 0
74 秒：261 个新目标资源句柄，旧路径 0
142 秒：启动器已退出；游戏仍运行；287 个新目标资源句柄，旧路径 0
```

随后通过正常的 `⌘Q` 完全退出，游戏和启动器进程均消失。

## 内置空间与运行时增长

真实界面测试前后分别记录内置数据卷、鸣潮容器与缓存：

| 项目 | 变化 |
| --- | --- |
| 内置数据卷可用空间 | 约减少 199 MiB |
| 鸣潮沙盒容器 | 约增加 9.9 MiB |
| `Data/Library/Caches` | 约减少 2.6 MiB |
| 大型 `Resources` 回写内置盘 | 未发现 |
| 共享剪贴板归档 | 测试前后均为空 |

内置卷总变化包含 macOS 日志、TCC、安全书签和同时发生的系统活动，不能全部归因于游戏。可明确证明的是：没有重新生成一份大型内置 `Resources`，本轮鸣潮容器净增长远小于迁移负载。

## 旧宗卷收尾与当前状态

当前工作状态：

- 沙盒兼容软链接指向新目标。
- 修复后的新启动器可启动并加载新目标资源。
- 旧宗卷根目录的 `PSOReport`、`SaveGames`、`DeviceSaved`、`LocalStorage` 已逐目录备份到 `/Volumes/<target-volume>/MingchaoResources/LegacyRootState/`，共 6 个文件；四次正式完整校验均通过。
- 用户明确确认不可逆删除后，已通过 macOS“磁盘工具”永久删除旧源 APFS 宗卷。删除界面再次核对了宗卷名称、设备标识和 UUID，操作结果为成功。
- 删除后旧源设备和挂载点均不存在；同容器只剩原有的应用宗卷。
- 该 APFS 容器可用空间从约 74.0 GB 增至 176.7 GB，本次释放约 102.74 GB。
- `/Volumes/<target-volume>/MingchaoResources/Resources` 现在是唯一工作资源副本；旧宗卷回滚路径已不存在。

当前恢复边界：若 AP 上的工作副本损坏，不能再切回旧宗卷，只能依赖其他独立备份或重新下载游戏资源。四个根级小目录的已校验副本保留在 `LegacyRootState`。

## 对项目的后续建议

1. 为启动器构建测试增加 Mach-O `LC_BUILD_VERSION minos` 断言，防止只检查 Info.plist。
2. 明确数据目录遇到 destination-only protected provenance 时的政策；在政策落地前继续安全停止并要求人工复核。
3. 增加“外接宗卷到外接宗卷、原入口已经是软链接”的适配流程，显式记录旧链接目标并提供可验证回滚。
4. 运行验收时，先确认目标进程仍存在，再按 bundle ID 控制界面；某些界面控制工具会在进程退出后自动重新启动应用，可能产生不经适配器授权的假阴性实例。
5. 在删除整个旧宗卷前，独立盘点并备份宗卷根目录下不属于 `Resources` 的用户文件。

---

# English summary

This case migrated the exact Wuthering Waves `Resources` directory between two external APFS volumes. The 95.68 GiB payload contained 661 files; all file SHA-256 values matched after copying. macOS rewrote quarantine metadata and attached 90 protected destination-only provenance attributes. Quarantine was restored exactly; the user explicitly accepted the protected provenance exception after every other metadata field and hash matched.

The launcher initially failed because the installed Swift toolchain emitted a macOS 28.0 minimum deployment target while the host ran macOS 27.0. Adding `-target "$(uname -m)-apple-macosx13.0"` produced a signed launcher with Mach-O `minos 13.0`.

The sandbox container’s compatibility symlink also had to be switched from the old external resource path to the newly authorized target. After that change, the game loaded the existing account and world, held 287 handles under the new target and zero under the old path, survived launcher termination, wrote expected state, quit normally, and relaunched successfully. No explicit `Sandbox: deny` was found.

After the user explicitly confirmed the irreversible action, the four small root-level state directories were copied to `LegacyRootState` and passed four complete verifications. The old APFS volume was then permanently deleted through Disk Utility. Its device and former mount point are absent, about 102.74 GB was returned to the source APFS container, and the target is now the sole working resource copy.
