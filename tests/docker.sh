#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT
export MOCK_SUDO_LOG="$temp_dir/sudo.log"
mkdir -p "$temp_dir/bin"
cat > "$temp_dir/bin/dpkg-query" <<'MOCK'
#!/usr/bin/env bash
case "${*: -1}" in
    docker.io) echo 'install ok installed' ;;
    *) exit 1 ;;
esac
MOCK
cat > "$temp_dir/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_SUDO_LOG"
MOCK
chmod +x "$temp_dir/bin/"*
export PATH="$temp_dir/bin:$PATH"
# shellcheck source=utils/utils.sh
source "$repo_dir/utils/utils.sh"
if (source "$repo_dir/installers/docker.sh") >"$temp_dir/stdout" 2>"$temp_dir/stderr"; then
    echo 'Docker conflict was not detected' >&2
    exit 1
fi
grep -Fq 'docker.io' "$temp_dir/stderr"
[[ ! -e "$MOCK_SUDO_LOG" ]]
printf 'Docker conflict tests passed.\n'
