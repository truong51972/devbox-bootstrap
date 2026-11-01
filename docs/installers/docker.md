# Docker Engine

**Script:** `installers/docker.sh`

**Official sources:** Install guide: https://docs.docker.com/engine/install/ubuntu/ ; upstream: https://github.com/moby/moby

**What it does:** Install official Docker CE packages from Docker's APT repository after checking for conflicting distro packages.

**Verification:**

```bash
docker --version
docker info
```

**Notes and safety:** Docker group is root-equivalent. Conflicting docker.io/containerd/runc packages are reported, never silently removed. Docker daemon may require a service restart or WSL systemd configuration.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
