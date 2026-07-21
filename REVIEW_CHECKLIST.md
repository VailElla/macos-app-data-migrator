# 发布前审查清单 / Pre-publication Review Checklist

此清单是 GitHub 发布门槛。请仓库所有者逐项审查；在明确回复“审查通过”之前，不推送、不创建公开仓库、不发布 Release。

This checklist is the GitHub publication gate. The repository owner should review every item. Do not push, create a public repository, or publish a release until the owner explicitly approves.

## 1. 产品边界 / Product boundary

- [ ] Skill 一次只迁移一个准确 `.app` 或一个准确数据目录。 / The Skill handles one exact `.app` or data directory at a time.
- [ ] 程序与数据作为独立组件复制、校验和实测。 / Program and data are copied, verified, and smoke-tested independently.
- [ ] 不宣称支持所有沙盒程序；接入方式未证明时停止。 / It does not claim universal sandbox support and stops when integration is unproven.
- [ ] `SKILL.md` 和 README 对“接近零空间”与不可避免的少量 macOS 元数据写入解释准确。 / The near-zero-space and unavoidable small macOS metadata wording is accurate.

## 2. 源数据不可变 / Source immutability

- [ ] CLI 只有 `audit`、`copy`、`verify`、`reveal`、`link`。 / The CLI exposes only `audit`, `copy`, `verify`, `reveal`, and `link`.
- [ ] 没有 `move`、`restore`、源删除、源覆盖或源重命名能力。 / There is no move, restore, source-delete, source-overwrite, or source-rename capability.
- [ ] `copy --execute` 的状态、临时文件和工具缓存全部写在目标外接宗卷。 / Copy state, partials, and tool caches stay on the external destination volume.
- [ ] 目标断开、宗卷 UUID 改变、源树变化或程序重新运行时会安全停止；`verify` 在写入已校验状态前再次复查进程。 / It safely stops on disconnection, UUID change, source-tree change, or process restart; `verify` rechecks processes before committing verified state.

## 3. 数据完整性 / Data integrity

- [ ] 每个普通文件复制时和完整验证时都比较 SHA-256。 / Every regular file receives SHA-256 comparison during copy and full verification.
- [ ] 完整验证覆盖目录树、类型、权限、ACL、扩展属性/resource fork、软链接和硬链接；`.app` 根目录的已记录实例属性可不同，目标端任一应用条目新增的受保护 provenance 可存在，但源端已有 provenance 必须完全一致。 / Full verification covers the tree, types, permissions, ACLs, extended attributes/resource forks, symlinks, and hardlinks; documented app-root instance attributes may differ, and destination-only protected provenance may appear on any app entry, but source-present provenance must match exactly.
- [ ] `.app` 目标执行 `codesign --verify --deep --strict`。 / App destinations receive strict deep signature verification.
- [ ] 目标已有不同文件时拒绝覆盖。 / A differing pre-existing destination file is never overwritten.
- [ ] 中断后可使用相同日志与命令续传，源仍保持不变。 / The same journal and command resume an interruption while the source remains unchanged.

## 4. 内置空间与删除策略 / Internal space and removal policy

- [ ] 不在内置盘生成压缩包、磁盘镜像、完整副本、迁移日志、partial 或编译缓存。 / No archive, disk image, full copy, journal, partial, or compiler cache is created internally.
- [ ] 不请求管理员密码，不使用 `sudo`。 / No administrator password or `sudo` is used.
- [ ] 内置 `.app` 只由用户在访达中移到废纸篓；数据目录只在用户明确授权后由 Codex 通过访达移入废纸篓，且绝不自动清空。 / Only the user moves an internal app to Trash; Codex may move a data directory through Finder only after explicit authorization and never empties Trash automatically.
- [ ] 文档说明只有在访达中永久删除废纸篓里的内置源后才释放空间，并说明迁移不等于独立备份。 / Docs explain that space is released only after the internal source in Trash is permanently deleted in Finder and that migration is not an independent backup.
- [ ] 工具只用 `open -R` 定位路径，不用终端删除命令代替用户。 / The helper uses only `open -R` for selection and never substitutes a Terminal deletion.
- [ ] 数据目录默认经访达移入废纸篓并保留到实测完成；只有用户明确偏好时才使用同级 `.internal-backup`。 / A data directory normally stays in Trash through live testing; a sibling `.internal-backup` is used only when the user explicitly prefers it.

## 5. 运行兼容 / Runtime compatibility

- [ ] 文档要求启动、读取、写入、完全退出、再次启动及更新器测试。 / Docs require launch, read, write, full quit, relaunch, and updater testing.
- [ ] `.app` 直接从外接盘启动，不建立原路径软链接。 / An `.app` launches directly from external storage without an original-path symlink.
- [ ] 非沙盒数据在证明软链接可用后才建立链接。 / Non-sandboxed data receives a link only after symlink compatibility is proven.
- [ ] 沙盒数据要求程序原生设置、文件夹授权或专用适配器。 / Sandboxed data requires a native setting, folder authorization, or a dedicated adapter.

## 6. 鸣潮适配器 / Wuthering Waves adapter

- [ ] 只迁移精确 `Saved/Resources`，不盲目迁移整个容器或 `Saved`。 / Only exact `Saved/Resources` is migrated, not the whole container or `Saved`.
- [ ] 启动器的输出、Swift module cache 和临时目录都位于目标外接盘。 / Launcher output, Swift module cache, and temp directory all stay on the target external volume.
- [ ] 构建器拒绝覆盖已有 `.app`，不包含 `--replace`。 / The builder refuses an existing `.app` and has no `--replace`.
- [ ] 只请求所选可移动宗卷与辅助功能，不把完全磁盘访问作为方案。 / It uses selected removable-volume authorization and Accessibility, not Full Disk Access as a workaround.
- [ ] 生成的本机 `.app` 被 Git 忽略，不会公开。 / Generated machine-specific `.app` bundles are Git-ignored and never published.
- [ ] 程序运行时派生缓存与迁移负载分开测量和披露，不承诺“运行时零增长”。 / Runtime-derived app caches are measured and disclosed separately from migration payload; zero runtime growth is not promised.

## 7. 双语、隐私与开源材料 / Bilingual, privacy, and open-source materials

- [ ] `SKILL.md`、README 及全部操作参考都有中文和英文。 / `SKILL.md`, README, and every operational reference are available in Chinese and English.
- [ ] 没有本机用户名、真实卷名、卷 UUID、用户数据、日志、token、cookie 或密码。 / No local username, real volume name, UUID, user data, log, token, cookie, or password is present.
- [ ] 没有提交生成的 `.app`、迁移日志、partial、缓存或 `.DS_Store`。 / No generated app, journal, partial, cache, or `.DS_Store` is committed.
- [ ] MIT License 和 GitHub Actions 验证流程符合预期。 / The MIT License and GitHub Actions validation workflow are acceptable.

## 8. 本地验证 / Local validation

审查者可在仓库根目录运行： / Reviewers can run from the repository root:

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
python3 /absolute/path/to/skill-creator/scripts/quick_validate.py \
  skills/migrate-macos-app-data
git diff --check
```

- [ ] 所有命令通过。 / Every command passes.
- [ ] 测试的目标副本、日志、partial、构建目录和缓存位于一次性外接 APFS RAM 宗卷；内置临时目录只有小型源夹具，且不接触当前真实鸣潮迁移结果。 / Test destinations, journals, partials, build directories, and caches stay on a disposable external APFS RAM volume; only small source fixtures are internal, and the current real Wuthering Waves migration is untouched.

## 9. 所有者决定 / Owner decision

- [ ] 我已审查并接受上述安全边界、功能范围、双语文案和 MIT License。 / I reviewed and accept the safety boundary, scope, bilingual wording, and MIT License.
- [ ] 我明确授权下一步发布到 GitHub。 / I explicitly authorize the next GitHub publication step.

确认方式 / Approval phrase:

```text
审查通过
```

若有修改，请引用清单编号并写明要求；修改后应重新运行全部验证。 / To request changes, cite the checklist item and describe the change; all validation must be rerun afterward.
