# fzf

- **Purpose:** Interactive fuzzy selection of files, command history and any piped list.
- **Official project:** https://github.com/junegunn/fzf
- **Documentation:** https://junegunn.github.io/fzf/
- **Install:** `installers/fzf.sh` uses Ubuntu APT (`fzf`), then appends one Bash/Zsh shell integration block.
- **Verify:** `fzf --version`. Restart the shell and test `Ctrl-R` (history), `Ctrl-T` (files), or `Alt-C` (directories).
- **Compatibility:** New fzf versions use `fzf --zsh` / `fzf --bash`. Older Ubuntu APT releases use the packaged integration scripts when present.

Examples:
```bash
printf '%s\n' alpha beta gamma | fzf
fdfind -t f | fzf --preview 'bat --color=always --style=numbers {}'
```

If your Ubuntu package provides `fdfind`/`batcat` instead of `fd`/`bat`, the bat+fd installer provides user-local symlinks. fzf is a flat list picker, not a native expandable tree view.
