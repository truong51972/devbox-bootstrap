#!/usr/bin/env bash
# keychain: reuse SSH agents/keys across interactive shell sessions.
# Upstream: https://github.com/funtoo/keychain
key_file=''
sudo apt-get install -y keychain
if [[ -f "$HOME/.ssh/git" ]]; then
    key_file="$HOME/.ssh/git"
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then
    key_file="$HOME/.ssh/id_ed25519"
elif confirm 'Generate a new Ed25519 SSH key at ~/.ssh/git?' ssh_key; then
    mkdir -p -- "$HOME/.ssh"
    chmod 700 -- "$HOME/.ssh"
    if [[ "${DEVBOX_TUI_MODE:-}" == 1 ]]; then
        # Explicit opt-in only; the confirmation screen warns about no passphrase.
        ssh-keygen -q -t ed25519 -N '' -f "$HOME/.ssh/git"
    else
        ssh-keygen -t ed25519 -f "$HOME/.ssh/git"
    fi
    key_file="$HOME/.ssh/git"
fi
if [[ -z "$key_file" ]]; then
    warn 'No SSH private key selected; skipping keychain.'
    export DEVBOX_COMPONENT_CONFIG_SKIPPED=1
else
    key_ref="\$HOME/.ssh/${key_file##*/}"
    append_if_not_exists_in_script '# Keychain setup' \
        "eval \"\$(keychain --quiet --eval --agents ssh \"$key_ref\")\""
fi
