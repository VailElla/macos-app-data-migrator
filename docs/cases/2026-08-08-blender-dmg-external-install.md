# Blender DMG 外接 APFS 安装验收记录

日期：2026-08-08

状态：外接应用安装、完整复制校验、签名/Gatekeeper 验收和本地 MCP 集成均已完成

用途：记录一次真实的“DMG 挂载源 → 外接 APFS 应用目录”安装，以及它暴露的流程文档缺口。本文使用匿名卷名和通用路径；示例不能直接复制到其他机器。

## 任务与边界

目标是把 Blender 5.2.0 Apple Silicon 版本从已挂载 DMG 中的：

```text
/Volumes/<mounted-image>/Blender.app
```

直接安装到：

```text
/Volumes/<external-apfs>/Applications/Blender.app
```

这不是从内置 `/Applications` 迁移已有程序。挂载镜像中的 `.app` 是临时只读源，因此没有内置程序删除或 Finder 交接；用户配置和后续集成作为独立状态验收。

## 复制日志与完整校验

通用迁移器使用 `kind: app` 创建了外接日志。最终日志状态为 `verified`，并记录 `source_deleted_by_tool: false`。

| 项目 | 结果 |
| --- | --- |
| 普通文件 | 6,496 |
| 目录 | 1,047 |
| 软链接 | 0 |
| 逻辑字节 | 934,330,035 |
| 最大文件 | 183,237,520 字节 |
| 每个普通文件 SHA-256 | 通过 |
| 稳定源/目标快照 | 通过 |
| 元数据、ACL、xattr | 通过 |
| 硬链接与目标隔离 | 通过 |
| 严格深层代码签名 | 通过 |

日志同时绑定了源宗卷和目标外接 APFS 宗卷身份。后续复核时 DMG 已不再挂载，因此再次执行 `verify` 会安全停止在“找不到源目录”；这说明完整校验必须在卸载镜像前完成，不能等到交付后再补。

## 签名与 Gatekeeper

外接目标通过：

```text
codesign --verify --deep --strict = 通过
spctl --assess --type execute     = accepted
Gatekeeper 来源                   = Notarized Developer ID
bundle ID                         = org.blenderfoundation.blender
版本                              = 5.2.0
```

这次历史验收使用的是 `spctl`。当前发布流程已按 Apple 后续工具指引更新：macOS 14 及以上优先运行 `syspolicy_check distribution`，只有旧系统才把 `spctl --assess --type execute` 作为后备；本案例不追溯声称运行过当时未执行的检查。

迁移日志证明挂载 `.app` 与外接目标一致，但当时的日志 schema 不保存下载 DMG 的文件 SHA-256 或 `hdiutil verify` 结果。本案例因此推动新增 DMG 专用文档门槛；本次 PR 不改变已验证的复制器或日志 schema。

## 内外盘分离状态

外接应用包约 906 MB。Blender 的用户偏好和插件仍位于：

```text
~/Library/Application Support/Blender/5.2
```

验收时该目录约 432 KiB，包含偏好和插件配置，不是第二份大型程序负载。外接 `.app`、内置小型用户状态和后续工具配置被分别记录，没有把整个 `Application Support` 迁走。

## Blender MCP 集成验收

Blender 启动并保存插件启用状态后，本地 MCP 集成完成以下验收：

| 验收项 | 结果 |
| --- | --- |
| BlenderMCP 侧栏出现并启用 | 通过 |
| 本地监听地址 | `127.0.0.1:9876` |
| MCP `initialize` | 通过 |
| `tools/list` | 返回 22 个工具 |
| 只读 `get_scene_info` | 通过 |
| Blender 用户偏好中的插件启用状态 | 已保存 |
| 外部资产服务/API key | 未启用、未写入 |

MCP 和命令行桥接配置不属于 `.app` 复制负载。它们需要单独验证监听范围、启动持久化和凭证边界，不能因应用包哈希一致就自动视为可用。

## 暴露的流程缺口

1. 主 Skill 只有“已有 `.app` 迁移”的叙述，没有把 DMG 挂载源作为第一类安装来源。
2. 普通程序交接会定位内置 `.app`，但 DMG 直装没有内置源，不能套用删除/废纸篓步骤。
3. 日志绑定挂载源宗卷，却无法在镜像卸载后重跑源目标校验；文档必须把“卸载前完成 verified”设为硬门槛。
4. 应用包、内置用户配置和 MCP/插件集成属于三个不同验收层，必须分别记录。
5. 下载 DMG 的 SHA-256 和 `hdiutil verify` 结果应成为安装记录的一部分，即使暂时不扩展日志 schema。

---

# English summary

This case installed Blender 5.2.0 for Apple Silicon from a mounted DMG directly onto external APFS. The generic app copier journal reached `verified` for 6,496 regular files and 934,330,035 logical bytes. Every file SHA-256, stable snapshot, metadata, ACL, xattr, hardlink/isolation, and strict deep code-signature gate passed; the tool did not delete its source.

The external app also passed the then-recorded `spctl` Gatekeeper assessment as a notarized Developer ID build. Current guidance prefers `syspolicy_check distribution` on macOS 14 or later and keeps `spctl` only as an older-system fallback; this historical case does not retroactively claim that newer check. Blender user preferences and plugins remained as approximately 432 KiB under `~/Library/Application Support/Blender/5.2`, separate from the roughly 906 MB external app bundle.

A local-only Blender MCP integration was then enabled and accepted independently: `initialize` succeeded, `tools/list` returned 22 tools, and a read-only scene query succeeded. No external asset service or API key was enabled.

The later review could not rerun source/destination verification because the DMG was no longer mounted, although the external journal already recorded a complete verified run and source-volume identity. The case therefore adds a first-class DMG workflow: validate and mount read-only, finish full verification before detach, skip the internal-app Finder removal handoff, preserve the downloaded installer by default, and record the external bundle, internal user configuration, and post-install integrations as separate acceptance layers.
