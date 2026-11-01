# Powerlevel10k terminal theme

**Script:** `installers/powerlevel10k.sh`

**Official sources:** Upstream: https://github.com/romkatv/powerlevel10k ; Fonts: https://github.com/romkatv/powerlevel10k#fonts

**What it does:** Clone to ~/powerlevel10k if missing; add Zsh config blocks and copy a starter .p10k.zsh only if none exists.

**Verification:**

```bash
test -f "$HOME/powerlevel10k/powerlevel10k.zsh-theme"
```

**Notes and safety:** Preserves an existing ~/.p10k.zsh. Requires Zsh and a Nerd Font-compatible terminal.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
