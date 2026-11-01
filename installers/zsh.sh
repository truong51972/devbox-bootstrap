#!/usr/bin/env bash
sudo apt-get install -y zsh
if [[ ! -f "$HOME/.oh-my-zsh/oh-my-zsh.sh" ]]; then
    log 'Installing Oh My Zsh.'
    ( set -Eeuo pipefail
      temp="$(mktemp)"
      trap 'rm -f -- "$temp"' EXIT
      curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh -o "$temp"
      RUNZSH=no CHSH=no sh "$temp" --unattended
    )
else
    log 'Oh My Zsh already installed; leaving it in place.'
fi

custom_dir="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"
mkdir -p -- "$custom_dir/plugins"
plugin_dir="$custom_dir/plugins/zsh-autosuggestions"
if [[ ! -d "$plugin_dir" ]]; then
    git clone --depth 1 https://github.com/zsh-users/zsh-autosuggestions.git "$plugin_dir"
elif [[ ! -f "$plugin_dir/zsh-autosuggestions.plugin.zsh" ]]; then
    die "$plugin_dir exists but does not contain a valid zsh-autosuggestions plugin."
    return 1
fi
add_plugin_if_not_exists 'zsh-autosuggestions'
add_plugin_if_not_exists 'zsh-syntax-highlighting'

zsh_path="$(command -v zsh)"
if [[ "$(getent passwd "$USER" | cut -d: -f7)" != "$zsh_path" ]]; then
    log 'Changing the default login shell to Zsh.'
    chsh -s "$zsh_path"
fi
