# Zsh and Oh My Zsh

**Script:** `installers/zsh.sh`

**Official sources:** Zsh: https://www.zsh.org/ ; Oh My Zsh: https://ohmyz.sh/ ; upstream: https://github.com/ohmyzsh/ohmyzsh

**What it does:** APT installs zsh; official Oh My Zsh installer is fetched; zsh-autosuggestions is cloned if missing; syntax highlighting comes from Oh My Zsh.

**Verification:**

```bash
zsh --version
test -f "$HOME/.oh-my-zsh/oh-my-zsh.sh"
```

**Notes and safety:** The shell change uses chsh. Backup ~/.zshrc before modifications. On existing Oh My Zsh installations, the script does not update the framework automatically.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
