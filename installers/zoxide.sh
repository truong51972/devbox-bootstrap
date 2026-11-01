#!/usr/bin/env bash
sudo apt-get install -y zoxide
case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
    zsh) shell_name=zsh ;;
    bash) shell_name=bash ;;
    *) die 'Cannot configure zoxide for an unsupported shell'; return 1 ;;
esac
append_if_not_exists_in_script '# Zoxide setup' "eval \"\$(zoxide init $shell_name)\""
