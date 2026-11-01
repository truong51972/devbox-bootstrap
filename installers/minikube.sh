#!/usr/bin/env bash
# Minikube: local Kubernetes cluster; verify upstream binary checksum.
# Docs: https://minikube.sigs.k8s.io/docs/start/
if command -v minikube >/dev/null 2>&1; then
    log 'Minikube already installed; skipping.'
else
    sudo apt-get install -y curl ca-certificates
    architecture="$(dpkg --print-architecture)"
    case "$architecture" in
        amd64|arm64) ;;
        *) die "Unsupported Minikube architecture: $architecture"; return 1 ;;
    esac
    (
        set -Eeuo pipefail
        temp_dir="$(mktemp -d)"
        trap 'rm -rf -- "$temp_dir"' EXIT
        url="https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-${architecture}"
        curl -fsSL "$url" -o "$temp_dir/minikube"
        curl -fsSL "${url}.sha256" -o "$temp_dir/minikube.sha256"
        printf '%s  %s\n' "$(cat "$temp_dir/minikube.sha256")" "$temp_dir/minikube" | sha256sum --check --status
        sudo install -o root -g root -m 0755 "$temp_dir/minikube" /usr/local/bin/minikube
    )
fi

if [[ "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" == zsh && -f "$(zsh_rc_file)" ]]; then
    add_plugin_if_not_exists minikube
fi
