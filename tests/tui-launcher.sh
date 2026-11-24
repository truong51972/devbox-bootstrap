#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
root="$temp/.local/share/devbox-bootstrap"
export HOME="$temp/home"
mkdir -p "$root/bin" "$root/tui" "$root/utils" "$root/.venv/bin" "$root/.git" "$temp/mockbin"
cp "$repo_dir/utils/operation-lock.sh" "$root/utils/"
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
    *'fetch --no-tags --no-recurse-submodules --no-write-fetch-head origin +refs/heads/main:refs/devbox/update') exit 0 ;;
    *'rev-parse refs/devbox/update') printf "%040d\n" 2 ;;
    *'rev-parse HEAD') printf "%040d\n" 1 ;;
    *'merge-base --is-ancestor'*) exit "${MOCK_ANCESTRY:-0}" ;;
    *'merge --ff-only '*) exit 0 ;;
    *) echo "Unexpected git call: $*" >&2; exit 2 ;;
esac
MOCK
chmod +x "$root/.venv/bin/python" "$temp/mockbin/git"
export MOCK_GIT_LOG="$temp/git.log" MOCK_PIP_LOG="$temp/pip.log"
export PATH="$temp/mockbin:$PATH"

out="$(bash "$root/bin/devbox" --update)"
[[ "$out" == *'Devbox code is current: abc123'* ]]
grep -Fq 'fetch --no-tags --no-recurse-submodules --no-write-fetch-head origin' "$MOCK_GIT_LOG"
grep -Fq 'merge --ff-only ' "$MOCK_GIT_LOG"
[[ -s "$root/.venv/.devbox-runtime" ]]
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

: > "$MOCK_GIT_LOG"
if bash "$root/bin/devbox" --update "$(printf '%040d' 3)" >/dev/null 2>&1; then
    echo 'Changed upstream was accepted after confirmation' >&2; exit 1
fi
! grep -q 'merge --ff-only' "$MOCK_GIT_LOG"
: > "$MOCK_GIT_LOG"
if MOCK_ANCESTRY=1 bash "$root/bin/devbox" --update >/dev/null 2>&1; then
    echo 'Diverged checkout was accepted' >&2; exit 1
fi
! grep -q 'merge --ff-only' "$MOCK_GIT_LOG"
printf 'Devbox launcher tests passed.\n'
