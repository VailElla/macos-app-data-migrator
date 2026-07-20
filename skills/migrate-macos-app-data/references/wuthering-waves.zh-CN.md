# 鸣潮 macOS 外接资源适配器

此适配器只适用于 bundle ID `com.kurogame.mingchao` 的 macOS 版本。每次都从本机只读发现实际路径，不要照抄示例路径。

## 已知边界

- 默认沙盒容器：`~/Library/Containers/com.kurogame.mingchao`
- 大型资源通常位于：`Data/Library/Client/Saved/Resources`
- 只迁移准确的 `Resources`。`Saved` 其余小型配置、状态和日志目录保留在内置盘。
- 游戏运行时还可能在 `Data/Library/Caches/Metallibs` 生成派生着色器缓存。3.5.0 的一次真机首启/重启验收生成了约 1.1 GB；实际大小会随版本、硬件和既有缓存变化。它不是重复的 `Resources`，但确实占用内置空间。
- 游戏 `.app` 可能在 `/Applications` 或已挂载宗卷；用 bundle ID 定位并验证签名。

鸣潮受 App Sandbox 约束。即使原路径软链接在访达中可正确解析，游戏仍可能收到外接目标的 `Sandbox: deny`。因此普通软链接不是完整适配器。

## 安全迁移顺序

1. 完全退出鸣潮及 `Client-Mac-Shipping` 等辅助进程。
2. 对准确的 `Resources` 先执行 `audit` 和不带 `--execute` 的 `copy` 预演；逐字符复核路径后执行相同的 `copy --execute`，最后运行 `verify`。源 `Resources` 在完整校验前保持不变。
3. 如需迁移游戏 `.app`，作为独立组件用 `--kind app` 复制、验证签名，并从外接盘实测启动。
4. 在外接 APFS 上预先建立启动器上级目录。
5. 使用下面的构建器；所有 Swift 缓存、临时文件和生成物都位于 `--output-app` 所在的目标宗卷。

```bash
skills/migrate-macos-app-data/scripts/build_wuthering_waves_launcher.sh \
  --game-app "/absolute/path/鸣潮.app" \
  --resources "/Volumes/External/WutheringWaves/Resources" \
  --output-app "/Volumes/External/Applications/鸣潮（外接数据）.app"
```

构建器不会覆盖已有 `.app`。如需处理旧启动器，请用户在访达中操作；不要添加终端覆盖/删除步骤。生成的 `.app` 嵌入本机绝对路径并使用 ad-hoc 签名，不能提交到公共仓库。

早期手工迁移生成的旧启动器可能把路径编译在二进制中，没有新版 `Migration...` Info.plist 参数。不要原地覆盖或假设可自动升级；使用新的输出名称构建、完成全部实测，再由用户在访达中处理旧启动器。

## 首次运行

1. 打开生成的“鸣潮（外接数据）”启动器。
2. 在系统文件夹选择器中只选择准确的外接 `Resources`。启动器保存安全作用域书签。
3. 在“系统设置 → 隐私与安全性 → 辅助功能”中只启用这个启动器，再启动一次。
4. 保留“无法把 Resources 当作文稿打开”的无害提示。默认等待 65 秒，让游戏建立外接文件句柄，再由启动器自动按下“好”。

不要把“完全磁盘访问权限”授予游戏或终端作为绕过方案。启动器只需要用户选择的可移动宗卷授权和辅助功能。安全书签、TCC 权限和少量偏好由 macOS 写入内置系统数据，这是不可避免的小型系统元数据，不是迁移负载。

启动前后分别测量沙盒容器和 `Data/Library/Caches`。启动器不会把迁移负载写回内置盘，但不能阻止游戏生成 Metal 着色器等运行时缓存；若剩余空间无法容纳实测增长，停止验收并保留源数据。不要把终端删除这些缓存写成迁移步骤，因为游戏可能在下次启动时再次生成。

## 实际运行验收

- 游戏进程启动并保持运行。
- 在提示关闭前后，游戏都持有外接 `Resources` 下的文件句柄。
- 登录、资源加载、场景进入、一次安全设置写入、完全退出和再次启动都成功。
- 新增或更新的大型资源写入外接盘；内置 `Saved` 下没有重新生成大型 `Resources`。
- 单独记录内置 `Data/Library/Caches` 的运行时增长，不把它误报成迁移副本，也不把它隐藏在“零内置增长”结论中。
- 最近日志中没有针对外接资源路径的新 `sandbox deny`。

这些只读命令可辅助诊断，不需要管理员密码，也不得接上删除命令：

```bash
game_pid="$(pgrep -x Client-Mac-Shipping)"
lsof -p "$game_pid" | grep -F "/Volumes/External/WutheringWaves/Resources"
du -sh "$HOME/Library/Containers/com.kurogame.mingchao/Data/Library/Caches"
log show --last 3m --style compact \
  --predicate 'eventMessage CONTAINS[c] "WutheringWaves"' | grep -Ei 'deny|sandbox'
```

启动器重建后，ad-hoc code hash 会改变。macOS 可能要求先关闭再开启辅助功能条目。只有完成以上实测，才按访达交接文档处理准确的内置 `Resources` 源目录（默认移到废纸篓；只有明确选择时才使用 `Resources.internal-backup`）或内置游戏 `.app`。
