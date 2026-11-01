# bat + fd

- **Purpose:** `bat` previews files with syntax colors/line numbers; `fd` finds files/directories by name.
- **Official projects:** https://github.com/sharkdp/bat and https://github.com/sharkdp/fd
- **Documentation:** https://github.com/sharkdp/bat#readme and https://github.com/sharkdp/fd#readme
- **Install:** `installers/bat-fd.sh` uses Ubuntu APT packages `bat` and `fd-find`.
- **Verify:** `bat --version`, `fd --version` (or `batcat --version`, `fdfind --version` if your shell has not yet picked up `~/.local/bin`).
- **Compatibility:** Some Ubuntu versions name the executables `batcat` and `fdfind`. The installer safely creates `~/.local/bin/bat` and `~/.local/bin/fd` symlinks only if missing. It never overwrites existing commands, files or symlinks. Open a new login shell if `~/.local/bin` was not yet in PATH.

Examples:
```bash
fd -e py
fd -t d
bat -n main.py
bat --line-range 20:50 main.py
fd -e py | fzf --preview 'bat --color=always --style=numbers {}'
```

No aliases overwrite `cat` or `find`; those commands retain their original behavior.
