#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT
mkdir -p "$temp_dir/bin"

cat > "$temp_dir/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
if [[ "${MOCK_FAIL:-0}" == 1 ]]; then exit 42; fi
MOCK
cat > "$temp_dir/bin/dpkg" <<'MOCK'
#!/usr/bin/env bash
echo amd64
MOCK
cat > "$temp_dir/bin/curl" <<'MOCK'
#!/usr/bin/env bash
args=("$@")
output='' url=''
for (( i=0; i<${#args[@]}; i++ )); do
    if [[ "${args[i]}" == -o ]]; then output="${args[i+1]}"; fi
    if [[ "${args[i]}" == https://* ]]; then url="${args[i]}"; fi
done
[[ -n "$output" && -n "$url" ]] || exit 10
if [[ "$url" == *.sha256 ]]; then
    sum="$(printf 'mock-minikube-binary' | sha256sum | awk '{print $1}')"
    if [[ "${MOCK_BAD_HASH:-0}" == 1 ]]; then
        sum="$(printf 'wrong' | sha256sum | awk '{print $1}')"
    fi
    printf '%s\n' "$sum" > "$output"
else
    printf 'mock-minikube-binary' > "$output"
fi
MOCK
chmod +x "$temp_dir/bin/"*
export PATH="$temp_dir/bin:$PATH"
export MOCK_LOG="$temp_dir/log"
export SHELL=/bin/bash
# shellcheck source=utils/utils.sh
source "$repo_dir/utils/utils.sh"

# Force minikube to appear absent, even if preinstalled on a CI image.
command() {
    if [[ "$1" == -v && "${2:-}" == minikube ]]; then return 1; fi
    builtin command "$@"
}
export -f command

# Correct checksum allows install; a wrong checksum must prevent installation.
source "$repo_dir/installers/minikube.sh"
grep -Fq '/usr/local/bin/minikube' "$MOCK_LOG"
: > "$MOCK_LOG"
export MOCK_BAD_HASH=1
if bash -c 'set -Eeuo pipefail; source "$1/utils/utils.sh"; source "$1/installers/minikube.sh"' bash "$repo_dir" >/dev/null 2>&1; then
    echo 'Minikube accepted an invalid checksum' >&2
    exit 1
fi
if grep -Fq '/usr/local/bin/minikube' "$MOCK_LOG"; then
    echo 'Minikube installed an unverified binary' >&2
    exit 1
fi

# Failure from a sourced installer must propagate to the main CLI.
: > "$MOCK_LOG"
export MOCK_FAIL=1
if output="$(bash "$repo_dir/setup-ubuntu.sh" --only clean 2>&1)"; then
    echo 'Bootstrap swallowed the failing installer status' >&2
    exit 1
fi
[[ "$output" == *'FAILED'* && "$output" == *'clean'* ]]
printf 'Hardening tests passed.\n'
