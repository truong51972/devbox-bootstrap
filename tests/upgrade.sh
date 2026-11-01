#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT
mkdir -p "$temp_dir/bin" "$temp_dir/uv-home/.local/bin"

cat > "$temp_dir/bin/dpkg-query" <<'MOCK'
#!/usr/bin/env bash
package="${@: -1}"
case "$package" in
    fzf|bat) ;;
    *) exit 1 ;;
esac
case "$*" in
    *'${Status}'*) printf 'install ok installed' ;;
    *'${Version}'*) printf '0.1' ;;
    *) exit 2 ;;
esac
MOCK

cat > "$temp_dir/bin/apt-cache" <<'MOCK'
#!/usr/bin/env bash
case "${@: -1}" in
    fzf)
        printf '  Candidate: 0.2\n'
        # Regression: large policy table after Candidate must not SIGPIPE
        # the producer when the caller has set -o pipefail.
        if [[ "${MOCK_LARGE_APT_POLICY:-0}" == 1 ]]; then
            awk 'BEGIN {for (i=0; i<20000; i++) print "     0.2 500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages"}'
        fi ;;
    bat) printf '  Candidate: 0.1\n' ;;
    *) exit 1 ;;
esac
MOCK

cat > "$temp_dir/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
if [[ "${MOCK_SUDO_FAIL:-0}" == 1 ]]; then exit 42; fi
MOCK
chmod +x "$temp_dir/bin/"*
export PATH="$temp_dir/bin:$PATH"
export MOCK_LOG="$temp_dir/sudo.log"

output="$(bash "$repo_dir/setup-ubuntu.sh" --upgrade --dry-run --only fzf,ripgrep,bat-fd)"
[[ "$output" == *'Upgrade installed devbox tools only'* ]]
[[ "$output" == *'Would check APT updates for fzf'* ]]
[[ "$output" == *'PLANNED'* && "$output" == *'SKIPPED'* ]]
[[ ! -e "$MOCK_LOG" ]]

export MOCK_LARGE_APT_POLICY=1
output="$(bash "$repo_dir/setup-ubuntu.sh" --upgrade --only fzf,ripgrep,bat-fd)"
[[ "$output" == *'Updating fzf: 0.1 -> 0.2'* ]]
[[ "$output" == *'UPDATED'* ]]
[[ "$output" == *'UP_TO_DATE'* ]]
[[ "$output" == *'SKIPPED'* ]]
[[ "$(grep -Fc 'apt-get update' "$MOCK_LOG")" -eq 1 ]]
grep -Fxq 'apt-get install -y --only-upgrade fzf' "$MOCK_LOG"
! grep -q 'ripgrep' "$MOCK_LOG"
! grep -q 'install -y ripgrep' "$MOCK_LOG"
! grep -q 'apt-get upgrade' "$MOCK_LOG"

cat > "$temp_dir/uv-home/.local/bin/uv" <<'MOCK'
#!/usr/bin/env bash
case "$1" in
    --version)
        if [[ -f "$HOME/upgraded" ]]; then printf 'uv 0.2.0\n'; else printf 'uv 0.1.0\n'; fi ;;
    self)
        [[ "$2" == update && "${UV_NO_MODIFY_PATH:-}" == 1 ]] || exit 2
        touch "$HOME/upgraded" ;;
    *) exit 2 ;;
esac
MOCK
chmod +x "$temp_dir/uv-home/.local/bin/uv"
output="$(HOME="$temp_dir/uv-home" bash "$repo_dir/setup-ubuntu.sh" --upgrade --only uv)"
[[ "$output" == *'uv'* && "$output" == *'UPDATED'* ]]
[[ -f "$temp_dir/uv-home/upgraded" ]]

export MOCK_SUDO_FAIL=1
if output="$(bash "$repo_dir/setup-ubuntu.sh" --upgrade --only fzf 2>&1)"; then
    echo 'Upgrade unexpectedly swallowed APT failure' >&2
    exit 1
fi
[[ "$output" == *'FAILED'* && "$output" == *'fzf'* ]]

if bash "$repo_dir/setup-ubuntu.sh" --doctor --upgrade >/dev/null 2>&1; then
    echo 'Doctor incorrectly accepted upgrade mode' >&2
    exit 1
fi

printf 'Upgrade tests passed.\n'
