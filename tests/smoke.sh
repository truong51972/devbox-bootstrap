#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp_home="$(mktemp -d)"
trap 'rm -rf -- "$temp_home"' EXIT
export HOME="$temp_home"
# shellcheck source=utils/utils.sh
source "$repo_dir/utils/utils.sh"

cat > "$HOME/.zshrc" <<'RC'
plugins=(git)
RC
add_plugin_if_not_exists 'zsh-autosuggestions'
add_plugin_if_not_exists 'zsh-autosuggestions'
[[ "$(grep -o 'zsh-autosuggestions' "$HOME/.zshrc" | wc -l)" -eq 1 ]]

grep -Fq 'plugins=(git zsh-autosuggestions)' "$HOME/.zshrc"
cat > "$HOME/.zshrc" <<'RC'
plugins=(
  git
)
RC
add_plugin_if_not_exists 'zsh-syntax-highlighting'
add_plugin_if_not_exists 'zsh-syntax-highlighting'
[[ "$(grep -o 'zsh-syntax-highlighting' "$HOME/.zshrc" | wc -l)" -eq 1 ]]
grep -Fxq '  zsh-syntax-highlighting' "$HOME/.zshrc"

append_if_not_exists_in_script '# test-marker' 'eval "$(echo hello)"' "$HOME/.zshrc"
append_if_not_exists_in_script '# test-marker' 'eval "$(echo hello)"' "$HOME/.zshrc"
[[ "$(grep -Fc '# test-marker' "$HOME/.zshrc")" -eq 1 ]]
grep -Fxq 'eval "$(echo hello)"' "$HOME/.zshrc"

bash "$repo_dir/setup-ubuntu.sh" --help >/dev/null
printf 'Smoke tests passed.\n'
