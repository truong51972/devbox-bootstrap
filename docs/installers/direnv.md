# direnv

- **Purpose:** Load and unload project-local environment variables when entering/leaving a directory.
- **Official website:** https://direnv.net/
- **Official project:** https://github.com/direnv/direnv
- **Shell hook docs:** https://direnv.net/docs/hook.html
- **Install:** `installers/direnv.sh` uses Ubuntu APT (`direnv`) and appends one Bash/Zsh hook, at the end of the normal bootstrap configuration sequence.
- **Verify:** `direnv version`, `direnv status`. Restart the shell to activate the hook.

Example:
```bash
mkdir -p ~/example-direnv && cd ~/example-direnv
printf '%s\n' 'export PROJECT_MODE=development' > .envrc
direnv allow
echo "$PROJECT_MODE"
cd ..
```

**Security:** `.envrc` is executable shell code. Always inspect it before `direnv allow`, especially in a repository you just cloned. Modified `.envrc` files require approval again. Never commit credentials or private `.env` files; put secrets in ignored files and audit what loads them. For Oh My Zsh, this installer uses the **shell hook** rather than the Oh My Zsh `direnv` plugin; avoid enabling both to prevent redundant initialization.
