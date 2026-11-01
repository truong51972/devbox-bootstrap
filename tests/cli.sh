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
printf 'CLI tests passed.\n'
