#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'HELP'
Usage: bash setup-ubuntu.sh [--help]
Interactive Ubuntu developer workstation bootstrap.
Run as your regular user (not sudo); the installer requests sudo when needed.
HELP
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    '') ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if (( EUID == 0 )); then
    echo 'Run as a regular user, not as root/sudo.' >&2
    exit 1
fi

# A pipe to Bash has no script path. Bootstrap from a temporary clone in that case.
SCRIPT_DIR=''
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
if [[ -z "$SCRIPT_DIR" || ! -f "$SCRIPT_DIR/utils/utils.sh" ]]; then
    command -v git >/dev/null || {
        sudo apt-get update
        sudo apt-get install -y git ca-certificates
    }
    temp_dir="$(mktemp -d /tmp/devbox-bootstrap.XXXXXX)"
    trap 'rm -rf -- "$temp_dir"' EXIT
    git clone --depth 1 https://github.com/truong51972/devbox-bootstrap.git "$temp_dir"
    if [[ ! -r /dev/tty ]]; then
        echo 'An interactive terminal is required. Clone the repo and run setup-ubuntu.sh directly.' >&2
        exit 1
    fi
    bash "$temp_dir/setup-ubuntu.sh" < /dev/tty
    exit $?
fi

# shellcheck source=utils/utils.sh
source "$SCRIPT_DIR/utils/utils.sh"
cd "$SCRIPT_DIR"

if [[ ! -r /etc/os-release ]]; then
    die 'Cannot identify this Linux distribution.'
    exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != ubuntu ]]; then
    die 'This installer currently supports Ubuntu only.'
    exit 1
fi
if [[ ! -t 0 ]]; then
    die 'Interactive input is required. Run in a terminal.'
    exit 1
fi

log 'Installing prerequisites (no automatic full-system upgrade).'
# shellcheck source=installers/basic.sh
source "$SCRIPT_DIR/installers/basic.sh"

if confirm 'Install Zsh, Oh My Zsh and plugins?'; then
    # shellcheck source=installers/zsh.sh
    source "$SCRIPT_DIR/installers/zsh.sh"
    export BOOTSTRAP_TARGET_SHELL=zsh
    if confirm 'Install Powerlevel10k?'; then
        # shellcheck source=installers/powerlevel10k.sh
        source "$SCRIPT_DIR/installers/powerlevel10k.sh"
    fi
fi
if confirm 'Install uv (Python project and environment manager)?'; then
    # shellcheck source=installers/python.sh
    source "$SCRIPT_DIR/installers/python.sh"
fi
if confirm 'Configure SSH keychain?'; then
    # shellcheck source=installers/keychain.sh
    source "$SCRIPT_DIR/installers/keychain.sh"
fi
if confirm 'Install zoxide?'; then
    # shellcheck source=installers/zoxide.sh
    source "$SCRIPT_DIR/installers/zoxide.sh"
fi
if confirm 'Install Docker Engine?'; then
    # shellcheck source=installers/docker.sh
    source "$SCRIPT_DIR/installers/docker.sh"
    if confirm 'Install and configure NVIDIA Container Toolkit for Docker?'; then
        # shellcheck source=installers/nvidia-container-toolkit.sh
        source "$SCRIPT_DIR/installers/nvidia-container-toolkit.sh"
    fi
fi
if confirm 'Install kubectl (and optionally Minikube)?'; then
    # shellcheck source=installers/k8s.sh
    source "$SCRIPT_DIR/installers/k8s.sh"
fi
if confirm 'Run apt autoremove/autoclean?'; then
    # shellcheck source=installers/clean.sh
    source "$SCRIPT_DIR/installers/clean.sh"
fi

log 'Setup complete. Restart your shell to apply configuration changes.'
if confirm 'Reboot now?'; then
    sudo reboot
fi
