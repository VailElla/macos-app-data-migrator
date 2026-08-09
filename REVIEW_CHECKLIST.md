# 发布前审查清单 / Pre-publication Review Checklist

此清单是 GitHub 发布门槛。请仓库所有者逐项审查；在明确回复“审查通过”之前，不推送、不创建公开仓库、不发布 Release。

This checklist is the GitHub publication gate. The repository owner should review every item. Do not push, create a public repository, or publish a release until the owner explicitly approves.

## 1. 产品边界 / Product boundary

- [ ] Skill 一次只迁移一个准确 `.app` 或一个准确数据目录。 / The Skill handles one exact `.app` or data directory at a time.
- [ ] DMG 直装一次只选择镜像中的一个准确、无需特权安装的 `.app`；`.pkg`、系统扩展和安装脚本不冒充可复制应用。 / A direct DMG install selects one exact directly runnable `.app`; packages, system extensions, and installer scripts are never treated as copyable apps.
- [ ] 程序与数据作为独立组件复制、校验和实测。 / Program and data are copied, verified, and smoke-tested independently.
- [ ] 不宣称支持所有沙盒程序；接入方式未证明时停止。 / It does not claim universal sandbox support and stops when integration is unproven.
- [ ] `SKILL.md` 和 README 对“接近零空间”与不可避免的少量 macOS 元数据写入解释准确。 / The near-zero-space and unavoidable small macOS metadata wording is accurate.

## 2. 源数据不可变 / Source immutability

- [ ] CLI 只有 `audit`、`copy`、`verify`、`reveal`、`link`。 / The CLI exposes only `audit`, `copy`, `verify`, `reveal`, and `link`.
- [ ] 没有 `move`、`restore`、源删除、源覆盖或源重命名能力。 / There is no move, restore, source-delete, source-overwrite, or source-rename capability.
- [ ] `copy --execute` 的状态、临时文件和工具缓存全部写在目标外接宗卷。 / Copy state, partials, and tool caches stay on the external destination volume.
- [ ] 目标断开、宗卷 UUID 改变、源树变化或程序重新运行时会安全停止；新建日志至少记录一个 `--process-name`，旧日志缺少进程名时 `copy`/`verify`/交接会安全停止；`verify` 在写入已校验状态前再次复查进程。 / It safely stops on disconnection, UUID change, source-tree change, or process restart; new journals require at least one `--process-name`, and copy/verify/handoff stop when a legacy journal has none; `verify` rechecks processes before committing verified state.

## 3. 数据完整性 / Data integrity

- [ ] 每个普通文件复制时和完整验证时都比较 SHA-256。 / Every regular file receives SHA-256 comparison during copy and full verification.
- [ ] 完整验证覆盖目录树、类型、权限、ACL、扩展属性/resource fork、软链接和硬链接；`.app` 根目录脚本列出的实例属性（包括 provenance）可不同，应用内部条目只允许目标端新增的受保护 provenance，源端已有 provenance 必须完全一致。 / Full verification covers the tree, types, permissions, ACLs, extended attributes/resource forks, symlinks, and hardlinks; script-listed app-root instance attributes (including provenance) may differ, while descendants allow only destination-only protected provenance and require source-present provenance to match exactly.
- [ ] `.app` 目标执行 `codesign --verify --deep --strict`。 / App destinations receive strict deep signature verification.
- [ ] 目标已有不同文件时拒绝覆盖。 / A differing pre-existing destination file is never overwritten.
- [ ] 中断后可使用相同日志与命令续传，源仍保持不变。 / The same journal and command resume an interruption while the source remains unchanged.
- [ ] 接近 APFS `NAME_MAX` 的合法源文件名不会因 partial 命名变长而复制失败；普通 `._` 前缀文件不会被当作可忽略旁车。 / A legal source filename near APFS `NAME_MAX` does not fail because the partial name grows, and ordinary `._`-prefixed files are not treated as ignorable sidecars.

## 4. 内置空间与删除策略 / Internal space and removal policy

- [ ] 不在内置盘生成压缩包、磁盘镜像、完整副本、迁移日志、partial 或编译缓存。 / No archive, disk image, full copy, journal, partial, or compiler cache is created internally.
- [ ] 不请求管理员密码，不使用 `sudo`。 / No administrator password or `sudo` is used.
- [ ] 内置 `.app` 只由用户在访达中移到废纸篓；数据目录只在用户明确授权后由 Codex 通过访达移入废纸篓，且绝不自动清空。 / Only the user moves an internal app to Trash; Codex may move a data directory through Finder only after explicit authorization and never empties Trash automatically.
- [ ] 文档说明只有在访达中永久删除废纸篓里的内置源后才释放空间，并说明迁移不等于独立备份。 / Docs explain that space is released only after the internal source in Trash is permanently deleted in Finder and that migration is not an independent backup.
- [ ] 工具只用 `open -R` 定位路径，不用终端删除命令代替用户。 / The helper uses only `open -R` for selection and never substitutes a Terminal deletion.
- [ ] 数据目录默认经访达移入废纸篓并保留到实测完成；`link` 必须收到明确的 Finder 交接确认和准确恢复路径，并用源快照、inode、设备号证明回滚副本仍是原目录；只有用户明确偏好时才使用同级 `.internal-backup`。 / A data directory normally stays in Trash through live testing; `link` requires an explicit Finder-handoff attestation and exact recovery path, then proves the rollback copy is the journaled source by snapshot, inode, and device; a sibling `.internal-backup` is used only when the user explicitly prefers it.

## 5. 运行兼容 / Runtime compatibility

- [ ] 文档要求启动、读取、写入、完全退出、再次启动及更新器测试。 / Docs require launch, read, write, full quit, relaunch, and updater testing.
- [ ] `.app` 直接从外接盘启动，不建立原路径软链接。 / An `.app` launches directly from external storage without an original-path symlink.
- [ ] 非沙盒数据在证明软链接可用后才建立链接。 / Non-sandboxed data receives a link only after symlink compatibility is proven.
- [ ] 沙盒数据要求程序原生设置、文件夹授权或专用适配器。 / Sandboxed data requires a native setting, folder authorization, or a dedicated adapter.

## 6. DMG 直接安装 / Direct DMG installation

- [ ] 对准确 DMG 记录 SHA-256，运行 `hdiutil verify`，并使用 `-readonly -nobrowse` 挂载；挂载点来自本次命令和 `diskutil`，不猜测或复用旧路径。 / The exact DMG receives a recorded SHA-256 and `hdiutil verify`, is mounted with `-readonly -nobrowse`, and uses the current command/`diskutil` mount point rather than a guessed or stale path.
- [ ] 挂载 `.app` 作为 `--kind app` 源，通过预演、复制和完整 `verify`；日志达到 `status: verified` 后才卸载镜像。 / The mounted app is the `--kind app` source and passes dry-run, copy, and full `verify`; the image remains mounted until the journal reaches `status: verified`.
- [ ] 外接目标同时通过严格代码签名与 `spctl --assess` Gatekeeper 验收；成功启动不能替代源目标完整校验。 / The external target passes strict code-signature and `spctl --assess` Gatekeeper gates; a successful launch never substitutes for full source/destination verification.
- [ ] 没有既有内置 `.app` 时不执行 Finder 程序删除交接、不建立原路径链接；下载 DMG 默认保留，明确清理时也只经访达移入废纸篓。 / With no existing internal app, there is no Finder app-removal handoff or original-path link; the downloaded DMG is retained by default and explicit cleanup only moves it to Trash through Finder.
- [ ] 验收分别记录外接应用、内置用户配置/插件和 MCP/命令行等后续集成，并验证完全退出、再次启动和外接盘生命周期。 / Acceptance records the external app, internal user configuration/plugins, and post-install MCP/CLI integrations separately, including full quit, relaunch, and external-volume lifecycle checks.
- [ ] 双语 DMG 参考和匿名化真实案例不包含用户名、真实卷名、UUID、迁移日志或凭证。 / The bilingual DMG guides and anonymized real case contain no username, real volume name, UUID, migration journal, or credential.

## 7. 鸣潮适配器 / Wuthering Waves adapter

- [ ] 只迁移精确 `Saved/Resources`，不盲目迁移整个容器或 `Saved`。 / Only exact `Saved/Resources` is migrated, not the whole container or `Saved`.
- [ ] 启动器的输出、Swift module cache 和临时目录都位于目标外接盘。 / Launcher output, Swift module cache, and temp directory all stay on the target external volume.
- [ ] 构建器拒绝覆盖已有 `.app`，不包含 `--replace`。 / The builder refuses an existing `.app` and has no `--replace`.
- [ ] 只请求所选可移动宗卷与辅助功能，不把完全磁盘访问作为方案。 / It uses selected removable-volume authorization and Accessibility, not Full Disk Access as a workaround.
- [ ] 生成的本机 `.app` 被 Git 忽略，不会公开。 / Generated machine-specific `.app` bundles are Git-ignored and never published.
- [ ] 程序运行时派生缓存与迁移负载分开测量和披露，不承诺“运行时零增长”。 / Runtime-derived app caches are measured and disclosed separately from migration payload; zero runtime growth is not promised.

## 8. 双语、隐私与开源材料 / Bilingual, privacy, and open-source materials

- [ ] `SKILL.md`、README 及全部操作参考都有中文和英文。 / `SKILL.md`, README, and every operational reference are available in Chinese and English.
- [ ] 没有本机用户名、真实卷名、卷 UUID、用户数据、日志、token、cookie 或密码。 / No local username, real volume name, UUID, user data, log, token, cookie, or password is present.
- [ ] 没有提交生成的 `.app`、迁移日志、partial、缓存或 `.DS_Store`。 / No generated app, journal, partial, cache, or `.DS_Store` is committed.
- [ ] MIT License 和 GitHub Actions 验证流程符合预期。 / The MIT License and GitHub Actions validation workflow are acceptable.

## 9. 外接 APFS 容器整合 / External APFS container consolidation

- [ ] 整盘整合是独立的低自由度参考流程；`migrate_app_data.py` 仍不接受宗卷根目录，也没有删除容器子命令。 / Whole-disk consolidation remains a separate low-freedom reference; `migrate_app_data.py` still rejects volume roots and has no container-deletion command.
- [ ] 每个删除、扩容或改名动作前按容器、宗卷和物理存储 UUID 重新解析动态 `diskN` 标识。 / Dynamic `diskN` identifiers are resolved again from container, volume, and physical-store UUIDs immediately before every delete, resize, or rename.
- [ ] `Device not configured` 或 USB 重新枚举后停止写入、重新枚举、只读检查并重新建立可信快照，不篡改日志绕过 `st_dev`/inode 身份保护。 / After `Device not configured` or USB re-enumeration, writes stop, identity is re-enumerated, read-only checks run, and a trusted snapshot is rebuilt without patching journals around `st_dev`/inode guards.
- [ ] `ditto` 后比较完整路径集合，逐个补齐被误判为 AppleDouble 的普通 `._` 文件，并恢复非 provenance xattr 和由深到浅的目录元数据。 / After `ditto`, complete path sets are compared, ordinary `._` files mistaken for AppleDouble are supplemented individually, and non-provenance xattrs plus deepest-first directory metadata are restored.
- [ ] 受保护 provenance 例外会准确披露并取得用户明确接受，不会削弱普通数据的严格校验。 / Protected provenance exceptions are disclosed exactly and explicitly accepted by the user without weakening strict data verification.
- [ ] 临时分区被明确标注为同盘暂存而非备份；只有最终行为测试、文件系统检查和完整校验通过后才删除并扩容到磁盘末尾。 / Temporary same-disk staging is explicitly not a backup and is deleted only after final behavior tests, filesystem checks, and full verification pass before resizing to the disk end.

## 10. 本地验证 / Local validation

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

## 11. 所有者决定 / Owner decision

- [ ] 我已审查并接受上述安全边界、功能范围、双语文案和 MIT License。 / I reviewed and accept the safety boundary, scope, bilingual wording, and MIT License.
- [ ] 我明确授权下一步发布到 GitHub。 / I explicitly authorize the next GitHub publication step.

确认方式 / Approval phrase:

```text
审查通过
```

若有修改，请引用清单编号并写明要求；修改后应重新运行全部验证。 / To request changes, cite the checklist item and describe the change; all validation must be rerun afterward.
