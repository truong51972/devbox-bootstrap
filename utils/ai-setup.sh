#!/usr/bin/env bash
# Explicit user-local AI setup. Keep the lock across the ordered batch.
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${1:-}" == --yes ]] || { echo 'Use devbox agent setup to preview first.' >&2; exit 2; }
shift
(( $# )) || { echo 'Choose at least one setup item.' >&2; exit 2; }
(( EUID != 0 )) || { echo 'Run AI setup as a regular user.' >&2; exit 2; }
declare -A selected=()
declare -a skills=()
for key in "$@"; do
    case "$key" in
        codex|claude|copilot|opencode|gemini|rtk|skills-cli|ponytail) ;;
        skill:context-management|skill:celery-worker|skill:dependency-injection|skill:drf-api-architecture|skill:python-monorepo-architecture|skill:system-prompt-builder)
            skills+=("${key#skill:}") ;;
        *) echo "Unsupported AI setup item: $key" >&2; exit 2 ;;
    esac
    [[ -z "${selected[$key]:-}" ]] || { echo "Duplicate item: $key" >&2; exit 2; }
    selected[$key]=1
done
if (( ${#skills[@]} )); then selected[codex]=1; selected[skills-cli]=1; fi
if [[ -n "${selected[rtk]:-}${selected[ponytail]:-}" ]]; then selected[codex]=1; fi
export PATH="$PATH:$HOME/.local/bin"
# shellcheck source=utils/operation-lock.sh
source "$root/utils/operation-lock.sh"
devbox_acquire_lock
cd "$HOME"
# Check prerequisites for the full plan before changing anything.
needs_npm=0
for cli in codex claude copilot opencode gemini; do
    if [[ -n "${selected[$cli]:-}" ]] && ! command -v "$cli" >/dev/null 2>&1; then needs_npm=1; fi
done
if [[ -n "${selected[skills-cli]:-}" ]]; then
    needs_npm=1
    command -v node >/dev/null || { echo 'Skills CLI requires Node.js >=22.20.' >&2; exit 1; }
    version="$(node -p 'process.versions.node')"
    major="${version%%.*}"; minor="${version#*.}"; minor="${minor%%.*}"
    if (( major < 22 || (major == 22 && minor < 20) )); then echo 'Skills CLI requires Node.js >=22.20.' >&2; exit 1; fi
fi
if (( needs_npm )); then
    command -v npm >/dev/null && command -v node >/dev/null || { echo 'Install Node.js and npm first.' >&2; exit 1; }
fi
install_cli() {
    local cli="$1" package="$2"
    [[ -n "${selected[$cli]:-}" ]] || return 0
    if command -v "$cli" >/dev/null 2>&1; then
        echo "Preserving existing $cli: $(command -v "$cli")"
    else
        if [[ -e "$HOME/.local/bin/$cli" || -L "$HOME/.local/bin/$cli" ]]; then
            echo "Refusing to overwrite existing $cli path." >&2; return 1
        fi
        timeout 300 npm install --global --prefix "$HOME/.local" --no-audit --no-fund "$package"
        hash -r
    fi
    timeout 15 "$cli" --version
}
install_cli codex @openai/codex
install_cli claude @anthropic-ai/claude-code
install_cli copilot @github/copilot
install_cli opencode opencode-ai
install_cli gemini @google/gemini-cli
if [[ -n "${selected[skills-cli]:-}" ]]; then bash "$root/setup-ubuntu.sh" --only skills-cli; fi
if [[ -n "${selected[rtk]:-}" ]]; then bash "$root/setup-ubuntu.sh" --only rtk --agents codex; fi
if [[ -n "${selected[ponytail]:-}" ]]; then bash "$root/setup-ubuntu.sh" --only ponytail --agents codex; fi
if (( ${#skills[@]} )); then
    # Never use upstream --all, which would install for every supported agent.
    timeout 300 skills add truong51972/coding-kit --skill "${skills[@]}" -g -a codex -y
fi
echo 'AI setup commands completed. Restart the agent and inspect integration/skill inventory. Login and runtime hook trust are not verified.'
