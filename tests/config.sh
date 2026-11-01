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
# A commented plugin name must not count as enabled.
cat > "$HOME/.zshrc" <<'RC'
plugins=(
  git
  # zsh-syntax-highlighting
)
RC
add_plugin_if_not_exists zsh-syntax-highlighting
add_plugin_if_not_exists zsh-syntax-highlighting
[[ "$(grep -Fxc '  zsh-syntax-highlighting' "$HOME/.zshrc")" -eq 1 ]]

# Both plugin edits and shell-block writes must respect ZDOTDIR.
export ZDOTDIR="$HOME/.config/zsh"
mkdir -p "$ZDOTDIR"
printf 'plugins=(git)\n' > "$ZDOTDIR/.zshrc"
add_plugin_if_not_exists zsh-autosuggestions
grep -Fq 'plugins=(git zsh-autosuggestions)' "$ZDOTDIR/.zshrc"
export BOOTSTRAP_TARGET_SHELL=zsh
append_if_not_exists_in_script '# test-zdotdir' 'export ZDOTDIR_TEST=1'
grep -Fq '# test-zdotdir' "$ZDOTDIR/.zshrc"
if grep -Fq '# test-zdotdir' "$HOME/.zshrc"; then
    echo 'ZDOTDIR config leaked into ~/.zshrc' >&2
    exit 1
fi
unset ZDOTDIR BOOTSTRAP_TARGET_SHELL

printf 'Configuration backup tests passed.\n'
