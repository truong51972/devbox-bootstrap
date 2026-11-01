#!/usr/bin/env bash
if ! command -v zsh >/dev/null 2>&1; then
    die 'Powerlevel10k requires Zsh; install the zsh component first.'
    return 1
fi
if [[ ! -f "$HOME/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
    if [[ -e "$HOME/powerlevel10k" ]]; then
        die "$HOME/powerlevel10k exists but does not look like a Powerlevel10k checkout."
        return 1
    fi
    git clone --depth 1 https://github.com/romkatv/powerlevel10k.git "$HOME/powerlevel10k"
fi
append_if_not_exists_in_script '# Powerlevel10k theme setup' \
    'source "$HOME/powerlevel10k/powerlevel10k.zsh-theme"' "$HOME/.zshrc"

if [[ ! -e "$HOME/.p10k.zsh" ]]; then
    cp -- "$SCRIPT_DIR/config/.p10k.zsh" "$HOME/.p10k.zsh"
else
    log 'Keeping existing ~/.p10k.zsh (not overwriting personal theme settings).'
fi
append_if_not_exists_in_script '# Powerlevel10k configuration setup' \
    '[[ ! -f "$HOME/.p10k.zsh" ]] || source "$HOME/.p10k.zsh"' "$HOME/.zshrc"
