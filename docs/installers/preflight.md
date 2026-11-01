# Read-only workstation inspection

**Script:** `installers/preflight.sh`

**Official sources:** Ubuntu environment reference: https://ubuntu.com/server/docs ; WSL: https://learn.microsoft.com/en-us/windows/wsl/

**What it does:** Inspect OS, CPU architecture, shell, WSL, Docker accessibility, NVIDIA utilities and home filesystem free space.

**Verification:**

```bash
bash setup-ubuntu.sh --preflight
```

**Notes and safety:** No sudo, installs or configuration writes. Warnings do not guarantee real hardware or daemon readiness.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
