#!/usr/bin/env bash
# Install the lightweight Devbox TUI into ~/.local without touching system Python.
set -Eeuo pipefail

if (( EUID == 0 )); then
    echo 'Install as your regular user, not via sudo.' >&2
    exit 1
fi

for executable in git python3; do
    if ! command -v "$executable" >/dev/null 2>&1; then
        echo "Missing $executable. On Ubuntu: sudo apt-get install -y git python3 python3-venv" >&2
        exit 1
    fi
done

app_dir="$HOME/.local/share/devbox-bootstrap"
bin_dir="$HOME/.local/bin"
mkdir -p "$HOME/.local/share" "$bin_dir"

if [[ -e "$app_dir" ]]; then
    if [[ ! -d "$app_dir/.git" || ! -f "$app_dir/bin/devbox" ]]; then
        echo "Refusing to overwrite an existing directory: $app_dir" >&2
        exit 1
    fi
    bash "$app_dir/bin/devbox" --update
else
    git clone --depth 1 --branch main \
        https://github.com/truong51972/devbox-bootstrap.git "$app_dir"
    bash "$app_dir/bin/devbox" --setup-runtime
fi

launcher="$bin_dir/devbox"
if [[ -e "$launcher" || -L "$launcher" ]]; then
    if [[ "$(readlink -f "$launcher")" != "$app_dir/bin/devbox" ]]; then
        echo "Refusing to overwrite existing command: $launcher" >&2
        exit 1
    fi
else
    ln -s "$app_dir/bin/devbox" "$launcher"
fi

printf '\nDevbox TUI installed. Run: %s\n' "$launcher"
if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
    echo "Note: $bin_dir is not in PATH; add it to your shell PATH to use 'devbox'."
fi
