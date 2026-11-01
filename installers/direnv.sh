#!/usr/bin/env bash
# direnv: load per-project environment from explicitly approved .envrc files.
# Docs: https://direnv.net/
sudo apt-get install -y direnv

case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
    zsh)
        append_if_not_exists_in_script '# devbox: direnv shell hook' \
            'if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv hook zsh)"
fi' "$HOME/.zshrc"
        ;;
    bash)
        append_if_not_exists_in_script '# devbox: direnv shell hook' \
            'if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv hook bash)"
fi' "$HOME/.bashrc"
        ;;
    *)
        warn 'direnv installed; shell hook skipped (supported: Bash, Zsh).'
        ;;
esac
