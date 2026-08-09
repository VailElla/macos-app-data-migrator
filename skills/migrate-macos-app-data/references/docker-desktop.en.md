# Docker Desktop Sparse VM-Disk Migration

This workflow covers only the Linux VM disk used by Docker Desktop for macOS. Treat the Docker `.app`, privileged helpers, CLI, host bind mounts, and user directories outside the VM disk as separate components.

## Hard boundary

- Prefer Docker Desktop's supported **Settings → Resources → Advanced → Disk image location → Browse** workflow. Docker explicitly warns against moving the disk image directly in Finder because Desktop can lose track of it.
- `Docker.raw` is a large sparse file. Its logical size can greatly exceed physical allocation; do not substitute Finder size, `st_size`, or apparent free space for both logical and allocated-size auditing.
- Generic `migrate_app_data.py copy` stops safely when it finds real sparse holes because its `ditto` path allocates those holes. Do not add a bypass flag. Use app-native relocation or first implement and validate a dedicated sparse copier.
- Do not move the Docker `.app` with the VM disk, edit Docker settings files to pretend the backend switched, or use `sudo`.
- Behavior tests do not replace SHA-256. If the user explicitly declines hashing, report only “runtime validated; byte integrity unproven.” Never write `verified` state or permanently remove the sole recovery copy on that basis.

## 0. Inventory and independent recovery

Record the Docker Desktop version, current disk-image location, logical size, physical allocation, external APFS free space, and:

```bash
docker desktop status
docker version
docker system df -v
docker container ls -a
docker image ls
docker volume ls
```

Distinguish VM-disk data, named volumes, and host bind mounts. A container commit excludes named-volume contents; never push an image containing environment secrets or other private configuration to a public repository. Keep independent backups of important images, Compose definitions, and volume data.

When Docker cannot start and the whole VM must be preserved, Docker documents `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` as the macOS backup object. Stop Docker Desktop completely before copying it.

## 1. Stop completely and prove quiescence

Prefer:

```bash
docker desktop stop
docker desktop status
```

Then use `pgrep` and `lsof` against Docker Desktop, its virtualization backend, and the exact data directory. If status says stopped but any process still holds `Docker.raw`, wait; never copy a live VM disk.

## 2. Use the supported disk-location move

Choose a real directory on external APFS in Docker Desktop settings and Apply. Do not choose a symlinked parent, sync root, network filesystem, or intermittently mounted location. Keep power and the external disk stable throughout relocation.

If the native relocation is killed, errors, or rolls back:

1. Stop further writes and manual patching.
2. Resolve the disk location Docker currently reports.
3. Confirm the original `Docker.raw` still exists and has stable logical and allocated sizes.
4. Restart against the original environment, prove it is readable, and report the failed relocation.

Do not turn edits to `settings-store.json`, a direct Finder move of `Docker.raw`, or a temporary symlink into an automatic fallback. An already deployed field-proven symlink may be monitored as legacy state, but this Skill must not recreate one until a separate deterministic adapter and tests exist.

## 3. Verify after relocation

Record the canonical new `Docker.raw` path, device, logical size, and allocation. Physical allocation must not unexpectedly approach the entire logical ceiling. Then:

1. Start Docker Desktop; require `docker desktop status` to report running and `docker info` to succeed.
2. Use `lsof` to prove the virtualization backend holds the external `Docker.raw` and has zero handles to the old path.
3. Use an existing small local image, or a test image only after the user accepts the download, to write and read a container file, exit, and run again.
4. Check required images, containers, named volumes, Compose projects, and bind mounts.
5. Fully stop and restart Docker Desktop, then repeat status, path, and readback checks.
6. Confirm the old internal path did not regenerate a new active data directory.

Runtime testing changes the new working VM disk. A pre-migration recovery copy does not receive those writes. Disclose this time gap and obtain fresh user confirmation before removing any recovery copy.

## 4. Missing external disk and rollback

Do not start Docker Desktop when the external volume is absent, has a different UUID, or the target path is unavailable; otherwise Docker can create a new empty environment at its default internal path. Restore the exact volume first.

Keep the original location when native relocation fails and rolls back. If a future dedicated workflow leaves a Finder recovery copy, treat it as a point-in-time snapshot: stop Docker, remove the new integration, and use Finder Put Back. Never empty Trash automatically.

## Official sources

- [Docker Desktop for Mac FAQ: disk image location and supported move](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/macfaqs/)
- [Back up and restore Docker Desktop data](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
- [Docker Desktop CLI reference](https://docs.docker.com/reference/cli/docker/desktop/)
