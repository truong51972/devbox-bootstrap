# zoxide directory jumping

**Script:** `installers/zoxide.sh`

**Official sources:** Official: https://github.com/ajeetdsouza/zoxide

**What it does:** Install via APT and add a Bash/Zsh shell hook.

**Verification:**

```bash
zoxide --version
```

**Notes and safety:** Requires a new shell session for the hook to load. With fzf, zi enables interactive directory selection.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
