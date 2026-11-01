#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Unknown prompts and absent explicit consent MUST be declined.
if DEVBOX_TUI_MODE=1 bash -c 'source "$1/utils/utils.sh"; confirm "change?" change_shell' bash "$repo_dir"; then
    echo "Unapproved shell change accepted" >&2
    exit 1
fi
DEVBOX_TUI_MODE=1 DEVBOX_CONFIRM_CHANGE_SHELL=yes \
    bash -c 'source "$1/utils/utils.sh"; confirm "change?" change_shell' bash "$repo_dir"
if DEVBOX_TUI_MODE=1 DEVBOX_CONFIRM_CHANGE_SHELL=yes \
    bash -c 'source "$1/utils/utils.sh"; confirm "unknown?" unknown' bash "$repo_dir"; then
    echo "Unknown confirmation was accepted" >&2
    exit 1
fi

# Check key generation in a temporary HOME without invoking real sudo/ssh-keygen.
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home"
cat > "$tmp/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf 'sudo:%s\n' "$*" >> "$MOCK_LOG"
MOCK
cat > "$tmp/bin/ssh-keygen" <<'MOCK'
#!/usr/bin/env bash
printf 'ssh-keygen:%s\n' "$*" >> "$MOCK_LOG"
while (( $# )); do
    if [[ "$1" == -f ]]; then
        touch "$2"
        break
    fi
    shift
done
MOCK
chmod +x "$tmp/bin/"*
export HOME="$tmp/home" PATH="$tmp/bin:$PATH"
export MOCK_LOG="$tmp/ops.log" BOOTSTRAP_TARGET_SHELL=bash
DEVBOX_TUI_MODE=1 DEVBOX_CONFIRM_SSH_KEY=yes \
    bash -c 'source "$1/utils/utils.sh"; source "$1/installers/keychain.sh"' bash "$repo_dir"
[[ -f "$HOME/.ssh/git" ]]
grep -Fq 'ssh-keygen:-q -t ed25519 -N  -f ' "$MOCK_LOG"
grep -Fq 'Keychain setup' "$HOME/.bashrc"
echo "TUI confirmation tests passed."
