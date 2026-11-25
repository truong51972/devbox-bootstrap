#!/usr/bin/env bash
# Update only a verified user-local npm CLI, preserving external installations.
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 1 && $EUID != 0 ]] || exit 2
case "$1" in
    codex) package=@openai/codex ;;
    claude) package=@anthropic-ai/claude-code ;;
    copilot) package=@github/copilot ;;
    opencode) package=opencode-ai ;;
    gemini) package=@google/gemini-cli ;;
    *) exit 2 ;;
esac
source "$root/utils/operation-lock.sh"
devbox_acquire_lock
export PATH="$PATH:$HOME/.local/bin"
binary="$(command -v "$1")"
[[ "$binary" == "$HOME/.local/bin/$1" && -L "$binary" ]] || { echo 'External CLI; refusing replacement.' >&2; exit 1; }
target="$(readlink -f "$binary")"
package_root="$(readlink -f "$HOME/.local/lib/node_modules/$package")"
[[ "$target" == "$package_root/"* && -f "$package_root/package.json" ]] || exit 1
node -e 'const p=require(process.argv[1]); if(p.name!==process.argv[2]) process.exit(1)' "$package_root/package.json" "$package"
timeout 300 npm install --global --prefix "$HOME/.local" --no-audit --no-fund "$package@latest"
timeout 15 "$binary" --version
