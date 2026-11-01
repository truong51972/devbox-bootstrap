# ripgrep (rg)

- **Purpose:** Search file contents recursively with regex; respects `.gitignore` by default.
- **Official project:** https://github.com/BurntSushi/ripgrep
- **Documentation:** https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- **Install:** `installers/ripgrep.sh` uses Ubuntu APT (`ripgrep`). No shell aliases or hook required.
- **Verify:** `rg --version`.

Examples:
```bash
rg 'PlatformJob'
rg -n -i 'TODO|FIXME' -g '*.py'
rg -l 'PlatformJob' | fzf
rg --hidden 'DATABASE_URL'
```

Note: `--hidden` includes hidden files but still honors ignore rules. Avoid displaying secrets when searching sensitive project directories.
