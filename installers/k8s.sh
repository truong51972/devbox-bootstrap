#!/usr/bin/env bash
if ! command -v kubectl >/dev/null 2>&1; then
    architecture="$(dpkg --print-architecture)"
    case "$architecture" in
        amd64|arm64) ;;
        *) die "Unsupported kubectl architecture: $architecture"; return 1 ;;
    esac
    ( set -Eeuo pipefail
      temp_dir="$(mktemp -d)"
      trap 'rm -rf -- "$temp_dir"' EXIT
      version="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
      download_url="https://dl.k8s.io/release/${version}/bin/linux/${architecture}/kubectl"
      curl -fsSL "$download_url" -o "$temp_dir/kubectl"
      curl -fsSL "${download_url}.sha256" -o "$temp_dir/kubectl.sha256"
      printf '%s  %s\n' "$(cat "$temp_dir/kubectl.sha256")" "$temp_dir/kubectl" | sha256sum --check --status
      sudo install -o root -g root -m 0755 "$temp_dir/kubectl" /usr/local/bin/kubectl
    )
else
    log 'kubectl already installed; skipping binary download.'
fi

case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
    zsh)
        append_if_not_exists_in_script '# kubectl completion and shortcut' \
            'if command -v kubectl >/dev/null 2>&1; then
  source <(kubectl completion zsh)
  alias k=kubectl
  compdef __start_kubectl k
fi'
        ;;
    bash)
        append_if_not_exists_in_script '# kubectl completion and shortcut' \
            'if command -v kubectl >/dev/null 2>&1; then
  source <(kubectl completion bash)
  alias k=kubectl
  complete -o default -F __start_kubectl k
fi'
        ;;
    *) warn 'Skipping kubectl shell completion for unsupported shell.' ;;
esac

if confirm 'Install Minikube as well?'; then
    if command -v minikube >/dev/null 2>&1; then
        log 'Minikube already installed; skipping.'
    else
        architecture="$(dpkg --print-architecture)"
        case "$architecture" in
            amd64|arm64) ;;
            *) die "Unsupported Minikube architecture: $architecture"; return 1 ;;
        esac
        ( set -Eeuo pipefail
          temp="$(mktemp)"
          trap 'rm -f -- "$temp"' EXIT
          curl -fsSL "https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-${architecture}" -o "$temp"
          sudo install -o root -g root -m 0755 "$temp" /usr/local/bin/minikube
        )
    fi
    if [[ "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" == zsh ]]; then
        add_plugin_if_not_exists minikube
    fi
fi
