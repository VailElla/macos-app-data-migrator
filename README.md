# macOS App Data Migrator Skill

一个面向 Codex 的开源 Skill，用于把 macOS 应用或游戏的大型数据目录迁移到其他内置盘或外接盘，并尽量降低迁移过程中的临时磁盘占用。

它不是“把整个 `~/Library` 搬走”的脚本。Skill 会先识别精确数据边界和应用沙盒状态，再选择应用原生设置、普通软链接或专用安全书签适配器。

## 空间模型

| 场景 | 策略 | 峰值额外占用 |
|---|---|---:|
| 同一文件系统 | 原子目录移动 | 接近 0 |
| 跨文件系统 | 逐文件复制、fsync、SHA-256 校验后删除源文件 | 最大单个文件 + 约 16 MiB |

目标磁盘仍需容纳最终数据。跨磁盘复制不可能做到任何时刻绝对零额外字节，但本项目不会自动制作一份完整备份、压缩包或第三份副本。

## 功能

- 只读检查应用 bundle、沙盒 entitlement、运行进程和常见数据目录。
- APFS 与路径范围保护，拒绝 `/`、用户主目录、整个 `~/Library` 或容器根目录等宽泛目标。
- 同盘原子移动和跨盘可恢复流式迁移。
- 每个普通文件落盘后执行 SHA-256 校验，再删除对应源文件。
- 保留符号链接、硬链接、ACL、扩展属性和 resource fork。
- 使用小型 JSON 日志恢复中断操作。
- 提供鸣潮 / Wuthering Waves 的源码级安全书签启动器适配器。
- 不包含任何预编译程序、本机用户名、卷 UUID 或用户数据。

## 安装到 Codex

把 Skill 目录复制或链接到 Codex Skills 目录：

```bash
ln -s "/absolute/path/macos-app-data-migrator/skills/migrate-macos-app-data" \
  "$HOME/.codex/skills/migrate-macos-app-data"
```

随后使用：

```text
$migrate-macos-app-data 帮我把某个应用的大型数据迁移到外接 APFS 硬盘
```

Codex 会先进行只读盘点，并在跨盘流式迁移真正删除源文件前要求明确确认。

## 鸣潮适配器

鸣潮 macOS 版本受 App Sandbox 约束，普通软链接不能单独解决外接资源访问。本仓库包含一个可从源码生成的小型启动器：用户在系统文件夹选择器中授权外接 `Resources` 目录，启动器把安全作用域传给游戏，并在资源建立文件句柄后自动关闭无害的文件夹提示。

生成的 `.app` 会嵌入用户自己的绝对路径并使用 ad-hoc 签名，因此已被 `.gitignore` 排除，不应提交到公共仓库。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/skill-creator/scripts/quick_validate.py \
  skills/migrate-macos-app-data
```

测试覆盖路径保护、只读 dry-run、同盘原子移动、跨盘算法的强制流式模拟、中断续传、硬链接/符号链接保持，以及 Swift 启动器源码构建和签名。

## 安全提示

流式模式会在每个文件验证完成后逐步删除源文件，因此属于破坏性操作。不要用于仍在运行的应用、活动数据库、同步目录或尚未证明兼容方式的沙盒应用。执行前请阅读 Skill 内的兼容性和恢复文档。

## License

MIT
