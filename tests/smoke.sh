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

# Mock privileged installs and package-owned binary names; never modify the CI host.
export BOOTSTRAP_TARGET_SHELL=zsh
export MOCK_SUDO_LOG="$temp_home/sudo.log"
mkdir -p "$temp_home/mockbin"
cat > "$temp_home/mockbin/sudo" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_SUDO_LOG"
MOCK
cat > "$temp_home/mockbin/batcat" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK
cat > "$temp_home/mockbin/fdfind" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK
chmod +x "$temp_home/mockbin/"*
export PATH="$temp_home/mockbin:$PATH"

# A second installation must not duplicate shell hook blocks or replace symlinks.
for _attempt in 1 2; do
    # shellcheck source=installers/fzf.sh
    source "$repo_dir/installers/fzf.sh"
    # shellcheck source=installers/ripgrep.sh
    source "$repo_dir/installers/ripgrep.sh"
    # shellcheck source=installers/bat-fd.sh
    source "$repo_dir/installers/bat-fd.sh"
    # shellcheck source=installers/direnv.sh
    source "$repo_dir/installers/direnv.sh"
done
[[ "$(grep -Fc '# devbox: fzf shell integration' "$HOME/.zshrc")" -eq 1 ]]
[[ "$(grep -Fc '# devbox: direnv shell hook' "$HOME/.zshrc")" -eq 1 ]]
grep -Fq 'source <(fzf --zsh)' "$HOME/.zshrc"
grep -Fq 'eval "$(direnv hook zsh)"' "$HOME/.zshrc"
grep -Fq 'apt-get install -y fzf' "$MOCK_SUDO_LOG"
grep -Fq 'apt-get install -y ripgrep' "$MOCK_SUDO_LOG"
grep -Fq 'apt-get install -y bat fd-find' "$MOCK_SUDO_LOG"
grep -Fq 'apt-get install -y direnv' "$MOCK_SUDO_LOG"
if ! command -v bat >/dev/null 2>&1; then
    [[ -L "$HOME/.local/bin/bat" ]]
fi
if ! command -v fd >/dev/null 2>&1; then
    [[ -L "$HOME/.local/bin/fd" ]]
fi

export BOOTSTRAP_TARGET_SHELL=bash
# shellcheck source=installers/fzf.sh
source "$repo_dir/installers/fzf.sh"
# shellcheck source=installers/direnv.sh
source "$repo_dir/installers/direnv.sh"
grep -Fq 'eval "$(fzf --bash)"' "$HOME/.bashrc"
grep -Fq 'eval "$(direnv hook bash)"' "$HOME/.bashrc"

bash "$repo_dir/setup-ubuntu.sh" --help >/dev/null
printf 'Smoke tests passed.\n'
