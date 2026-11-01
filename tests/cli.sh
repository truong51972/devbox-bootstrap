#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output="$(bash "$repo_dir/setup-ubuntu.sh" --preflight)"
[[ "$output" == *'Preflight'* ]]
[[ "$output" == *'Architecture:'* ]]
output="$(bash "$repo_dir/setup-ubuntu.sh" --dry-run --only fzf,ripgrep,bat-fd,direnv)"
[[ "$output" == *'installers/fzf.sh'* ]]
[[ "$output" == *'installers/ripgrep.sh'* ]]
[[ "$output" == *'installers/bat-fd.sh'* ]]
[[ "$output" == *'installers/direnv.sh'* ]]
[[ "$output" != *'Would run: installers/docker.sh'* ]]
[[ "$output" == *'no packages or shell configuration were changed'* ]]
bash "$repo_dir/setup-ubuntu.sh" --help | grep -Fq -- '--kubectl-version'
if bash "$repo_dir/setup-ubuntu.sh" --only nonexistent >/dev/null 2>&1; then
    echo 'Unknown component incorrectly accepted' >&2
    exit 1
fi
if bash "$repo_dir/setup-ubuntu.sh" --only kubectl --kubectl-version fake >/dev/null 2>&1; then
    echo 'Invalid kubectl version incorrectly accepted' >&2
    exit 1
fi
output="$(bash "$repo_dir/setup-ubuntu.sh" --dry-run --only kubectl --kubectl-version v1.35.1)"
[[ "$output" == *'installers/k8s.sh'* ]]
# --doctor is read-only and detects an installed but unreachable Docker daemon.
temp_bin="$(mktemp -d)"
trap 'rm -rf -- "$temp_bin"' EXIT
cat > "$temp_bin/docker" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
chmod +x "$temp_bin/docker"
if output="$(PATH="$temp_bin:$PATH" bash "$repo_dir/setup-ubuntu.sh" --doctor 2>&1)"; then
    echo 'Doctor incorrectly accepted an unreachable Docker daemon' >&2
    exit 1
fi
[[ "$output" == *'Devbox Health Check'* ]]
[[ "$output" == *'daemon unreachable'* ]]

# Minikube is an independent component; it must not select kubectl.
output="$(bash "$repo_dir/setup-ubuntu.sh" --dry-run --only minikube)"
[[ "$output" == *'installers/minikube.sh'* ]]
[[ "$output" != *'installers/k8s.sh'* ]]

# Exercise the same pipe-to-bash argument path as the README curl command.
# Mock git clone to avoid network access; doctor must execute from the temp checkout.
mkdir -p "$temp_bin/gitmock"
export MOCK_SOURCE_REPO="$repo_dir"
export MOCK_GIT_LOG="$temp_bin/git-invocations.log"
cat > "$temp_bin/gitmock/git" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_GIT_LOG"
[[ "$1" == clone ]] || exit 2
dest="${@: -1}"
cp -a "$MOCK_SOURCE_REPO/." "$dest/"
MOCK
chmod +x "$temp_bin/gitmock/git"
piped_status=0
piped_output="$(cat "$repo_dir/setup-ubuntu.sh" | PATH="$temp_bin/gitmock:$temp_bin:$PATH" bash -s -- --doctor 2>&1)" || piped_status=$?
[[ "$piped_status" -eq 1 ]]
[[ "$piped_output" == *'Devbox Health Check'* ]]
[[ "$piped_output" == *'daemon unreachable'* ]]
grep -Fq 'clone --depth 1' "$MOCK_GIT_LOG"

# --upgrade can be piped without TTY, and forwards arguments to the checkout.
upgrade_output="$(cat "$repo_dir/setup-ubuntu.sh" | PATH="$temp_bin/gitmock:$temp_bin:$PATH" bash -s -- --upgrade --dry-run --only fzf 2>&1)"
[[ "$upgrade_output" == *'Upgrade installed devbox tools only'* ]]
[[ "$upgrade_output" == *'Upgrade summary'* ]]

printf 'CLI tests passed.\n'
