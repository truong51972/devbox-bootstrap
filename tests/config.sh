#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp_home="$(mktemp -d)"
trap 'rm -rf -- "$temp_home"' EXIT
export HOME="$temp_home"
# shellcheck source=utils/utils.sh
source "$repo_dir/utils/utils.sh"
printf 'plugins=(git)\n' > "$HOME/.zshrc"
add_plugin_if_not_exists fzf
add_plugin_if_not_exists fzf
[[ "$(grep -Fc 'fzf' "$HOME/.zshrc")" -eq 1 ]]
shopt -s nullglob
backups=("$HOME"/.zshrc.devbox-backup-*)
[[ "${#backups[@]}" -eq 1 ]]
grep -Fxq 'plugins=(git)' "${backups[0]}"

append_if_not_exists_in_script '# devbox-test' 'export TEST_ENV=1' "$HOME/.zshrc"
append_if_not_exists_in_script '# devbox-test' 'export TEST_ENV=1' "$HOME/.zshrc"
[[ "$(grep -Fc '# devbox-test' "$HOME/.zshrc")" -eq 1 ]]
backups=("$HOME"/.zshrc.devbox-backup-*)
[[ "${#backups[@]}" -eq 1 ]]

printf '%s\n' '# Alias for uv python' >> "$HOME/.bashrc"
warning="$(warn_legacy_shell_config 2>&1)"
[[ "$warning" == *'Legacy bootstrap blocks'* ]]
printf 'Configuration backup tests passed.\n'
