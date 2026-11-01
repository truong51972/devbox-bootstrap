#!/usr/bin/env bash
# On some Ubuntu releases the binaries are named batcat and fdfind.
sudo apt-get install -y bat fd-find

# Create user-local command aliases via symlinks, without overwriting other tools.
mkdir -p -- "$HOME/.local/bin"
if ! command -v bat >/dev/null 2>&1 && command -v batcat >/dev/null 2>&1; then
    if [[ ! -e "$HOME/.local/bin/bat" && ! -L "$HOME/.local/bin/bat" ]]; then
        ln -s -- "$(command -v batcat)" "$HOME/.local/bin/bat"
        log 'Created ~/.local/bin/bat -> batcat'
    fi
fi
if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then
    if [[ ! -e "$HOME/.local/bin/fd" && ! -L "$HOME/.local/bin/fd" ]]; then
        ln -s -- "$(command -v fdfind)" "$HOME/.local/bin/fd"
        log 'Created ~/.local/bin/fd -> fdfind'
    fi
fi
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "$HOME/.local/bin is not on PATH. Log in again or add it to PATH to use the new commands."
fi
