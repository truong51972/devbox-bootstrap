#!/usr/bin/env bash
# kubectl CLI (optionally Minikube); check Kubernetes client version skew.
# Docs: https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
# Minikube: https://minikube.sigs.k8s.io/docs/start/
requested_version="${BOOTSTRAP_KUBECTL_VERSION:-}"
install_kubectl=true
if command -v kubectl >/dev/null 2>&1; then
    if [[ -z "$requested_version" ]]; then
        install_kubectl=false
        log 'kubectl already installed; no version pin requested, skipping replacement.'
    else
        existing_version="$(kubectl version --client -o json 2>/dev/null | grep -Eo '"gitVersion"[[:space:]]*:[[:space:]]*"v[0-9]+\.[0-9]+\.[0-9]+"' | head -1 || true)"
        if [[ "$existing_version" == *"\"$requested_version\"" ]]; then
            install_kubectl=false
            log "kubectl $requested_version is already installed."
        elif ! confirm "kubectl exists with a different version; replace it with $requested_version?"; then
            die 'kubectl version selection cancelled; existing binary was preserved.'
            return 1
        fi
    fi
fi

if [[ "$install_kubectl" == true ]]; then
    sudo apt-get install -y curl ca-certificates
    architecture="$(dpkg --print-architecture)"
    case "$architecture" in
        amd64|arm64) ;;
        *) die "Unsupported kubectl architecture: $architecture"; return 1 ;;
    esac
    ( set -Eeuo pipefail
      temp_dir="$(mktemp -d)"
      trap 'rm -rf -- "$temp_dir"' EXIT
      version="${requested_version:-$(curl -fsSL https://dl.k8s.io/release/stable.txt)}"
      download_url="https://dl.k8s.io/release/${version}/bin/linux/${architecture}/kubectl"
      curl -fsSL "$download_url" -o "$temp_dir/kubectl"
      curl -fsSL "${download_url}.sha256" -o "$temp_dir/kubectl.sha256"
      printf '%s  %s\n' "$(cat "$temp_dir/kubectl.sha256")" "$temp_dir/kubectl" | sha256sum --check --status
      sudo install -o root -g root -m 0755 "$temp_dir/kubectl" /usr/local/bin/kubectl
    )
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

