# Docker Desktop 稀疏虚拟磁盘迁移

本流程只处理 macOS Docker Desktop 的 Linux 虚拟数据盘。Docker `.app`、系统辅助组件、CLI、bind mount 和位于虚拟盘外的用户目录不属于同一个迁移组件。

## 硬边界

- 优先使用 Docker Desktop 官方的 **Settings → Resources → Advanced → Disk image location → Browse**。Docker 官方明确警告不要直接在访达中移动磁盘镜像，否则 Docker Desktop 可能失去对它的跟踪。
- `Docker.raw` 是大型稀疏文件。逻辑大小可能远大于实际分配；不能用访达显示大小、`st_size` 或“剩余空间看起来够”代替逻辑与实际分配的双重审计。
- 通用 `migrate_app_data.py copy` 会在发现真实稀疏空洞时安全停止，因为它使用的 `ditto` 会把空洞展开。底层文件系统无法可靠检测空洞时也会停止，绝不把未知结果当作非稀疏文件。不要添加绕过参数；使用应用原生迁移，或先实现并验证专用稀疏复制器。
- 不把 Docker `.app` 与虚拟数据盘一起搬走，不修改 Docker 设置文件来伪造后台已切换，也不使用 `sudo`。
- 行为测试不能代替 SHA-256。用户明确跳过哈希时，只能报告“运行验证通过、字节级完整性未证明”，不能把状态写成 `verified`，也不能因此永久删除唯一恢复副本。

## 0. 盘点与独立恢复能力

先记录当前 Docker Desktop 版本、磁盘镜像位置、逻辑大小、实际分配、外接 APFS 可用空间，以及：

```bash
docker desktop status
docker version
docker system df -v
docker container ls -a
docker image ls
docker volume ls
```

区分虚拟盘内数据、named volumes 和 host bind mounts。容器 commit 不包含 named volume 内容；可能包含环境变量等敏感配置的镜像不得推送到公开仓库。重要镜像、Compose 定义和卷数据应另有独立备份。

Docker 无法启动且需要保全整台 VM 时，官方备份对象是 `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`。备份前必须完全停止 Docker Desktop。

## 1. 完全停止并确认无写入者

优先运行：

```bash
docker desktop stop
docker desktop status
```

再用 `pgrep` 和 `lsof` 检查 Docker Desktop、虚拟化后台和准确数据目录。`status` 显示 stopped 但仍有进程打开 `Docker.raw` 时继续等待；不要复制活动虚拟磁盘。

## 2. 使用官方磁盘位置迁移

在 Docker Desktop 设置中选择外接 APFS 上的真实目录并 Apply。不要选择软链接上级、同步目录、网络卷或会自动卸载的位置。迁移期间保持电源和外接盘稳定。

若原生迁移被终止、报错或自动回滚：

1. 停止继续写入和手工修补。
2. 重新确认 Docker 当前显示的磁盘位置。
3. 核对原 `Docker.raw` 是否仍存在、逻辑大小和实际分配是否稳定。
4. 重新启动并确认原环境仍可读，再报告失败。

不要把编辑 `settings-store.json`、直接在访达移动 `Docker.raw` 或临时创建软链接当作自动后备方案。现场已经运行的旧软链接可以作为 legacy 状态监控，但在实现独立、可测试的专用适配器前不要由本 Skill 重新创建。

## 3. 迁移后验证

完成原生迁移后，记录新 `Docker.raw` 的规范路径、设备号、逻辑大小和实际分配。实际分配不应意外接近完整逻辑上限。然后：

1. 启动 Docker Desktop，确认 `docker desktop status` 为 running，`docker info` 可读。
2. 用 `lsof` 证明虚拟化后台打开的是外接盘上的 `Docker.raw`，旧路径句柄为 0。
3. 使用已存在的小型本地镜像，或在用户同意下载后使用测试镜像，完成容器文件写入、读回、退出和再次启动。
4. 验证需要保留的镜像、容器、named volumes、Compose 项目和 bind mounts。
5. 完全停止并再次启动 Docker Desktop，重复状态、路径和读回检查。
6. 确认旧内置路径没有重新生成新的活动数据目录。

运行测试会修改新的工作虚拟盘；迁移前恢复副本不会同步这些新变化。清理恢复副本前必须披露这一时间差并再次取得用户确认。

## 4. 外接盘缺失与回滚

外接盘未挂载、UUID 不符或路径不可用时不要启动 Docker Desktop，防止它在默认内置路径创建新的空环境。先恢复准确宗卷，再启动。

原生迁移失败且已自动回滚时保留原位置。若未来的专用流程保留了 Finder 恢复副本，应把它视为迁移时点快照；恢复前先停止 Docker，移除新入口，并通过访达“放回原处”。不要自动清空废纸篓。

## 官方依据

- [Docker Desktop for Mac FAQ：磁盘镜像位置与官方移动方式](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/macfaqs/)
- [Docker Desktop 数据备份与恢复](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
- [Docker Desktop CLI](https://docs.docker.com/reference/cli/docker/desktop/)
