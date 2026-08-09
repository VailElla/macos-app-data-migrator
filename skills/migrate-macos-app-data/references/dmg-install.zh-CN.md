# 从 DMG 直接安装到外接 APFS

## 目录

- [适用边界](#适用边界)
- [1. 验证并只读挂载镜像](#1-验证并只读挂载镜像)
- [2. 从挂载源复制并完整校验](#2-从挂载源复制并完整校验)
- [3. 记录内外盘分离状态并实测](#3-记录内外盘分离状态并实测)
- [4. 弹出镜像与保留安装源](#4-弹出镜像与保留安装源)

## 适用边界

本流程适用于用户已经提供一个 `.dmg`，其中包含可直接运行的 macOS `.app`，并希望第一次就把程序安装到外接 APFS。挂载镜像中的 `.app` 是只读安装源，不是需要从内置 `/Applications` 删除的旧副本。

- 一次只安装镜像中的一个准确 `.app`。
- 不把 DMG 解压、转换或复制成第二份内置盘镜像。
- 目标必须是 `diskutil` 明确认定为外接的 APFS 宗卷。
- 下载的 DMG、挂载源 `.app` 和外接目标都保持原样，直到完整校验和真实运行验收完成。
- 不使用 `sudo`，不增加覆盖已有目标或跳过校验的参数。

如果内置 `/Applications` 已经存在另一个同名程序，那是独立的“已有 `.app` 迁移/交接”组件；不要因为本轮来自 DMG 就自动替换或删除它。

## 1. 验证并只读挂载镜像

先确认用户提供的准确 DMG 路径，再记录本地 SHA-256 指纹并验证映像内置校验和：

```bash
/usr/bin/shasum -a 256 "/absolute/path/App.dmg"
/usr/bin/hdiutil verify "/absolute/path/App.dmg"
/usr/sbin/diskutil image attach --plist --readOnly --nobrowse "/absolute/path/App.dmg"
```

若发布方在官方来源提供校验值，必须核对后再继续。旧版 macOS 没有 `diskutil image attach` 时，才使用 `/usr/bin/hdiutil attach -readonly -nobrowse` 兼容后备；当前命令报告真实映像错误时不得借后备绕过。映像设备和挂载点以本次命令输出为准，再用 `diskutil info` 核对；不猜测宗卷名，也不复用旧的 `/Volumes/...` 路径。

在挂载宗卷中只选择准确的 `.app`，并执行只读检查：

```bash
python3 scripts/inspect_app.py "/Volumes/ExactMountedVolume/App.app" --verify-signature

python3 scripts/migrate_app_data.py audit \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app
```

记录 DMG 指纹、挂载点、源 `.app`、bundle ID、版本、进程名、源宗卷身份、目标宗卷 UUID、外接可用空间和最大文件。发现安装器包、脚本、系统扩展或需要管理员安装的 `.pkg` 时停止；本流程只覆盖可直接复制运行的 `.app`。

## 2. 从挂载源复制并完整校验

保持镜像挂载，完全退出同名程序、更新器和辅助进程。先预演，再复核同一组路径并执行：

```bash
python3 scripts/migrate_app_data.py copy \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app \
  --process-name "ExactProcessName"

python3 scripts/migrate_app_data.py copy \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --kind app \
  --process-name "ExactProcessName" \
  --execute

python3 scripts/migrate_app_data.py verify \
  --source "/Volumes/ExactMountedVolume/App.app" \
  --destination "/Volumes/External/Applications/App.app" \
  --process-name "ExactProcessName"
```

迁移日志必须留在目标旁边并记录 `status: verified`。卸载 DMG 后源路径会消失，因此一定要在卸载前完成源目标全量 SHA-256、目录树、元数据、ACL、xattr、软/硬链接和严格代码签名校验。仅检查目标签名不能补做已经失去源路径的完整校验。

再对外接目标执行当前系统策略验收。macOS 14 及以上优先使用包含 Gatekeeper 等可信执行检查的 `syspolicy_check`：

```bash
/usr/bin/codesign --verify --deep --strict --verbose=2 "/Volumes/External/Applications/App.app"
/usr/bin/syspolicy_check distribution "/Volumes/External/Applications/App.app"
```

只有旧版 macOS 不提供 `syspolicy_check` 时，才使用旧 Gatekeeper 评估：

```bash
/usr/sbin/spctl --assess --type execute --verbose=4 "/Volumes/External/Applications/App.app"
```

严格代码签名和对应系统版本的策略检查都通过后才能启动目标。不要给复制器增加覆盖已有目标的能力；升级到新版本时，先使用新的暂存目标独立复制和校验，再设计明确、可回滚的版本交接。

## 3. 记录内外盘分离状态并实测

第一次启动前后记录内置盘可用空间和共享剪贴板归档基线，然后从准确的外接路径启动。完成启动、读取、安全写入、完全退出、再次启动和更新器检查。

程序包外置不表示所有状态都外置。偏好、插件、登录状态、小型数据库、TCC 记录和命令行工具配置通常仍位于用户目录；这些内容默认不属于本次 `.app` 安装负载。验收记录必须分别列出：

- 外接 `.app` 和目标宗卷；
- 内置用户配置、插件或偏好的实际路径与大致大小；
- 另行配置的插件、命令行桥接、MCP 或其他集成；
- 完全退出、重启程序或重新挂载外接盘后，集成是否仍然有效；
- 是否生成了超出用户可用空间的运行时派生缓存。

只有程序和必要集成都真实工作，且没有把大型程序负载重新写回内置盘，才能声明 DMG 外接安装成功。

## 4. 弹出镜像与保留安装源

完整校验和行为验收完成后，弹出 attach 命令返回的准确映像设备：

```bash
/usr/sbin/diskutil eject "/dev/diskN"
```

DMG 直装没有内置 `.app` 源，所以不执行程序迁移的 Finder 删除交接，也不建立原路径软链接。下载的 DMG 默认保留；用户明确要求清理时，只在访达中把准确 DMG 移到废纸篓，不使用终端删除，也不自动清空废纸篓。
