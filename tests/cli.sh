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

printf 'CLI tests passed.\n'
