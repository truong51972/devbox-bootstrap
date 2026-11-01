#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT
mkdir -p "$temp/bin"
export MOCK_LOG="$temp/sudo.log"
cat > "$temp/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
MOCK
cat > "$temp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
url='' dest=''
while (( $# )); do
    case "$1" in
        -o) dest="$2"; shift 2 ;;
        https://*) url="$1"; shift ;;
        *) shift ;;
    esac
done
[[ -n "$url" && -n "$dest" ]] || exit 5
if [[ "$url" == *.sha256 ]]; then
    if [[ "${MOCK_BAD_CHECKSUM:-0}" == 1 ]]; then
        printf '%s\n' "$(printf wrong | sha256sum | cut -d' ' -f1)" > "$dest"
    else
        printf '%s\n' "$(printf 'mock-binary' | sha256sum | cut -d' ' -f1)" > "$dest"
    fi
else
    printf 'mock-binary' > "$dest"
fi
MOCK
chmod +x "$temp/bin/"*
export PATH="$temp/bin:$PATH"
# shellcheck source=utils/utils.sh
source "$repo_dir/utils/utils.sh"
# shellcheck source=utils/upgrade.sh
source "$repo_dir/utils/upgrade.sh"

# Redirect command -v for the managed binary to avoid touching the CI machine.
command() {
    if [[ "$1" == -v && "${2:-}" == kubectl ]]; then
        printf '/usr/local/bin/kubectl\n'
    else
        builtin command "$@"
    fi
}
UPGRADE_CHANGED=0
upgrade_binary kubectl v1.38.0 https://example.test/kubectl v1.37.0
[[ "$UPGRADE_CHANGED" -eq 1 ]]
grep -Fq '/usr/local/bin/kubectl' "$MOCK_LOG"

: > "$MOCK_LOG"
UPGRADE_CHANGED=0
upgrade_binary kubectl v1.37.0 https://example.test/kubectl v1.38.0
[[ "$UPGRADE_CHANGED" -eq 0 ]]
[[ ! -s "$MOCK_LOG" ]]

: > "$MOCK_LOG"
export MOCK_BAD_CHECKSUM=1
if bash -c '
    set -Eeuo pipefail
    source "$1/utils/utils.sh"
    source "$1/utils/upgrade.sh"
    command() {
        if [[ "$1" == -v && "${2:-}" == kubectl ]]; then
            printf "/usr/local/bin/kubectl\n"
        else
            builtin command "$@"
        fi
    }
    upgrade_binary kubectl v1.38.0 https://example.test/kubectl v1.37.0
' bash "$repo_dir" >/dev/null 2>&1; then
    echo 'Upgrade installed a binary with a bad checksum' >&2
    exit 1
fi
[[ ! -s "$MOCK_LOG" ]]
printf 'Upgrade checksum tests passed.\n'
