# NVIDIA Container Toolkit

**Script:** `installers/nvidia-container-toolkit.sh`

**Official sources:** Official: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html ; upstream: https://github.com/NVIDIA/nvidia-container-toolkit

**What it does:** Install NVIDIA APT repository/package, run nvidia-ctk runtime configure --runtime=docker, and restart Docker where possible.

**Verification:**

```bash
nvidia-ctk --version
docker info
```

**Notes and safety:** Requires Docker and a working NVIDIA host driver. On WSL, GPU passthrough and host/guest driver configuration must be checked separately.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
