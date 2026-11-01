#!/usr/bin/env bash
key_file=''
if [[ -f "$HOME/.ssh/git" ]]; then
    key_file="$HOME/.ssh/git"
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then
    key_file="$HOME/.ssh/id_ed25519"
elif confirm 'Generate a new Ed25519 SSH key at ~/.ssh/git?'; then
    mkdir -p -m 700 "$HOME/.ssh"
    ssh-keygen -t ed25519 -f "$HOME/.ssh/git"
    key_file="$HOME/.ssh/git"
fi
if [[ -z "$key_file" ]]; then
    warn 'No SSH private key selected; skipping keychain.'
else
    sudo apt-get install -y keychain
    key_ref="\$HOME/.ssh/${key_file##*/}"
    append_if_not_exists_in_script '# Keychain setup' \
        "eval \"\$(keychain --quiet --eval --agents ssh \"$key_ref\")\""
fi
