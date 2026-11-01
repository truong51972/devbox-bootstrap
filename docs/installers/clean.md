# APT housekeeping

**Script:** `installers/clean.sh`

**Official sources:** APT docs: https://ubuntu.com/server/docs/package-management

**What it does:** Run apt-get autoremove and apt-get autoclean only when selected.

**Verification:**

```bash
sudo apt-get --version
```

**Notes and safety:** autoremove can remove unused packages: inspect your package set before opting in.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
