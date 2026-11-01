#!/usr/bin/env bash
# fzf: fuzzy finder with Bash/Zsh key bindings and completion.
# Upstream: https://github.com/junegunn/fzf
sudo apt-get install -y fzf

case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
    zsh)
        append_if_not_exists_in_script '# devbox: fzf shell integration' \
            'if command -v fzf >/dev/null 2>&1; then
  if fzf --zsh >/dev/null 2>&1; then
    source <(fzf --zsh)
  else
    [[ -r /usr/share/doc/fzf/examples/key-bindings.zsh ]] && source /usr/share/doc/fzf/examples/key-bindings.zsh
    [[ -r /usr/share/doc/fzf/examples/completion.zsh ]] && source /usr/share/doc/fzf/examples/completion.zsh
  fi
fi' "$HOME/.zshrc"
        ;;
    bash)
        append_if_not_exists_in_script '# devbox: fzf shell integration' \
            'if command -v fzf >/dev/null 2>&1; then
  if fzf --bash >/dev/null 2>&1; then
    eval "$(fzf --bash)"
  else
    [[ -r /usr/share/doc/fzf/examples/key-bindings.bash ]] && source /usr/share/doc/fzf/examples/key-bindings.bash
    [[ -r /usr/share/doc/fzf/examples/completion.bash ]] && source /usr/share/doc/fzf/examples/completion.bash
  fi
fi' "$HOME/.bashrc"
        ;;
    *)
        warn 'fzf installed; shell integration skipped (supported: Bash, Zsh).'
        ;;
esac
