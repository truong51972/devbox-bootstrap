#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
root="$temp/.local/share/devbox-bootstrap"
mkdir -p "$root/bin" "$root/tui" "$root/.venv/bin" "$root/.git" "$temp/mockbin"
cp "$repo_dir/bin/devbox" "$root/bin/devbox"
cp "$repo_dir/tui/requirements.txt" "$root/tui/requirements.txt"

cat > "$root/.venv/bin/python" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_PIP_LOG"
MOCK
cat > "$temp/mockbin/git" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_GIT_LOG"
case "$*" in
    *'remote get-url origin') printf '%s\n' "${MOCK_ORIGIN:-https://github.com/truong51972/devbox-bootstrap.git}" ;;
    *'symbolic-ref --quiet --short HEAD') printf 'main\n' ;;
    *'status --porcelain --untracked-files=no') printf '%s' "${MOCK_STATUS:-}" ;;
    *'rev-parse --short HEAD') printf 'abc123\n' ;;
    *'fetch --no-tags origin main'|*'merge --ff-only FETCH_HEAD') exit 0 ;;
    *) echo "Unexpected git call: $*" >&2; exit 2 ;;
esac
MOCK
chmod +x "$root/.venv/bin/python" "$temp/mockbin/git"
export MOCK_GIT_LOG="$temp/git.log" MOCK_PIP_LOG="$temp/pip.log"
export PATH="$temp/mockbin:$PATH"

out="$(bash "$root/bin/devbox" --update)"
[[ "$out" == *'Devbox code is current: abc123'* ]]
grep -Fq 'fetch --no-tags origin main' "$MOCK_GIT_LOG"
grep -Fq 'merge --ff-only FETCH_HEAD' "$MOCK_GIT_LOG"
grep -Fq -- '-m pip install' "$MOCK_PIP_LOG"

: > "$MOCK_GIT_LOG"
export MOCK_STATUS=' M README.md'
if bash "$root/bin/devbox" --update >/dev/null 2>&1; then
    echo 'Dirty worktree was updated' >&2
    exit 1
fi
if grep -q 'fetch --no-tags' "$MOCK_GIT_LOG"; then
    echo 'Dirty worktree fetched changes' >&2
    exit 1
fi
unset MOCK_STATUS

: > "$MOCK_GIT_LOG"
export MOCK_ORIGIN='https://github.com/attacker/suspicious'
if bash "$root/bin/devbox" --update >/dev/null 2>&1; then
    echo 'Unexpected origin was accepted' >&2
    exit 1
fi
if grep -q 'fetch --no-tags' "$MOCK_GIT_LOG"; then
    echo 'Unknown repository fetched changes' >&2
    exit 1
fi
unset MOCK_ORIGIN
printf 'Devbox launcher tests passed.\n'
