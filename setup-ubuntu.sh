#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'HELP'
Usage: bash setup-ubuntu.sh [OPTIONS]
Interactive Ubuntu workstation bootstrap (run as a regular user, not sudo).

Options:
  -h, --help                 Show this help
  --preflight                Inspect environment without modifying anything
  --dry-run                  Show selected operations without installing anything
  --only ITEMS               Comma-separated components, no component selection prompts
  --kubectl-version VERSION  Pin kubectl to a release such as v1.35.1

Components:
  zsh, powerlevel10k, uv, keychain, zoxide,
  fzf, ripgrep, bat-fd, direnv,
  docker, nvidia, kubectl, clean

Examples:
  bash setup-ubuntu.sh --preflight
  bash setup-ubuntu.sh --dry-run --only fzf,ripgrep,bat-fd,direnv
  bash setup-ubuntu.sh --only kubectl --kubectl-version v1.35.1
HELP
}

original_args=("$@")
ONLY_COMPONENTS=''
BOOTSTRAP_DRY_RUN=0
PREFLIGHT_ONLY=0
BOOTSTRAP_KUBECTL_VERSION=''
while (( $# > 0 )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) BOOTSTRAP_DRY_RUN=1; shift ;;
        --preflight) PREFLIGHT_ONLY=1; shift ;;
        --only|--kubectl-version)
            key="$1"
            if (( $# < 2 )) || [[ -z "$2" ]]; then
                printf 'Missing value for %s\n' "$key" >&2
                exit 2
            fi
            if [[ "$key" == --only ]]; then ONLY_COMPONENTS="$2"; else BOOTSTRAP_KUBECTL_VERSION="$2"; fi
            shift 2 ;;
        --only=*)
            ONLY_COMPONENTS="${1#--only=}"
            [[ -n "$ONLY_COMPONENTS" ]] || { echo '--only requires at least one component.' >&2; exit 2; }
            shift ;;
        --kubectl-version=*) BOOTSTRAP_KUBECTL_VERSION="${1#--kubectl-version=}"; shift ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -n "$BOOTSTRAP_KUBECTL_VERSION" && ! "$BOOTSTRAP_KUBECTL_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'Invalid kubectl version. Expected vMAJOR.MINOR.PATCH (e.g. v1.35.1).' >&2
    exit 2
fi
if [[ -n "$ONLY_COMPONENTS" ]]; then
    IFS=',' read -r -a requested <<< "$ONLY_COMPONENTS"
    for component in "${requested[@]}"; do
        case "$component" in
            zsh|powerlevel10k|uv|keychain|zoxide|fzf|ripgrep|bat-fd|direnv|docker|nvidia|kubectl|clean) ;;
            *) printf 'Unknown component: %s\n' "$component" >&2; exit 2 ;;
        esac
    done
fi
export BOOTSTRAP_KUBECTL_VERSION BOOTSTRAP_DRY_RUN

if (( EUID == 0 && PREFLIGHT_ONLY == 0 && BOOTSTRAP_DRY_RUN == 0 )); then
    echo 'Run as a regular user, not as root/sudo.' >&2
    exit 1
fi

# When invoked via a pipe, use a temporary checkout and preserve error codes.
SCRIPT_DIR=''
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
if [[ -z "$SCRIPT_DIR" || ! -f "$SCRIPT_DIR/utils/utils.sh" ]]; then
    if ! command -v git >/dev/null; then
        if (( BOOTSTRAP_DRY_RUN || PREFLIGHT_ONLY )); then
            echo 'Git is needed to inspect the remote checkout.' >&2
            exit 1
        fi
        sudo apt-get update
        sudo apt-get install -y git ca-certificates
    fi
    temp_dir="$(mktemp -d /tmp/devbox-bootstrap.XXXXXX)"
    trap 'rm -rf -- "$temp_dir"' EXIT
    git clone --depth 1 https://github.com/truong51972/devbox-bootstrap.git "$temp_dir"
    if [[ -t 0 || -n "$ONLY_COMPONENTS" ]] || (( PREFLIGHT_ONLY )); then
        # Targeted/preflight modes do not require a terminal for component selection.
        bash "$temp_dir/setup-ubuntu.sh" "${original_args[@]}"
    elif [[ -r /dev/tty ]]; then
        bash "$temp_dir/setup-ubuntu.sh" "${original_args[@]}" < /dev/tty
    else
        echo 'An interactive terminal is required. Run locally or use --only.' >&2
        exit 1
    fi
    exit $?
fi

# shellcheck source=utils/utils.sh
source "$SCRIPT_DIR/utils/utils.sh"
cd "$SCRIPT_DIR"

if [[ ! -r /etc/os-release ]]; then
    die 'Cannot identify Linux distribution.'
    exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
# shellcheck source=installers/preflight.sh
source "$SCRIPT_DIR/installers/preflight.sh"
if (( PREFLIGHT_ONLY )); then exit 0; fi
if [[ "${ID:-}" != ubuntu ]]; then
    die 'This installer currently supports Ubuntu only.'
    exit 1
fi
if [[ -z "$ONLY_COMPONENTS" && ! -t 0 ]]; then
    die 'Interactive mode requires a terminal. Use --only for scripted selection.'
    exit 1
fi
warn_legacy_shell_config

selected() {
    local item="$1"
    [[ ",$ONLY_COMPONENTS," == *",$item,"* ]]
}

verify_binary() {
    local component="$1"
    shift
    local binary
    for binary in "$@"; do
        if command -v "$binary" >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/$binary" ]]; then
            return 0
        fi
    done
    die "Post-install verification failed for $component (expected one of: $*)."
}

verify_component() {
    local component="$1"
    case "$component" in
        zsh) verify_binary "$component" zsh || return 1 ;;
        powerlevel10k)
            [[ -f "$HOME/powerlevel10k/powerlevel10k.zsh-theme" ]] || {
                die 'Powerlevel10k theme not found.'
                return 1
            } ;;
        uv) verify_binary "$component" uv || return 1 ;;
        keychain) verify_binary "$component" keychain || return 1 ;;
        zoxide) verify_binary "$component" zoxide || return 1 ;;
        fzf) verify_binary "$component" fzf || return 1 ;;
        ripgrep) verify_binary "$component" rg || return 1 ;;
        bat-fd)
            verify_binary "$component" bat batcat || return 1
            verify_binary "$component" fd fdfind || return 1 ;;
        direnv) verify_binary "$component" direnv || return 1 ;;
        docker) verify_binary "$component" docker || return 1 ;;
        nvidia) verify_binary "$component" nvidia-ctk || return 1 ;;
        kubectl) verify_binary "$component" kubectl || return 1 ;;
        clean) return 0 ;;
        *) die "Internal error: unknown component $component"; return 1 ;;
    esac
    log "Verified: $component"
}

run_component() {
    local component="$1" prompt="$2" installer="$3"
    if [[ -n "$ONLY_COMPONENTS" ]]; then
        selected "$component" || return 0
    elif ! confirm "$prompt"; then
        return 0
    fi

    if (( BOOTSTRAP_DRY_RUN )); then
        log "[dry-run] Would run: installers/$installer"
        return 0
    fi
    log "Installing: $component"
    # Each installer sources shared utilities and inherits fail-fast semantics.
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/installers/$installer"
    verify_component "$component"
}

if [[ -z "$ONLY_COMPONENTS" ]]; then
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would install base packages: Git, curl, wget, CA certificates, GnuPG and build tools.'
    else
        # shellcheck source=installers/basic.sh
        source "$SCRIPT_DIR/installers/basic.sh"
    fi
else
    log 'Selected components only: skipping unrelated base packages.'
fi

run_component zsh 'Install Zsh, Oh My Zsh and plugins?' zsh.sh
run_component powerlevel10k 'Install Powerlevel10k?' powerlevel10k.sh
run_component uv 'Install uv (Python manager)?' python.sh
run_component keychain 'Configure SSH keychain?' keychain.sh
run_component zoxide 'Install zoxide?' zoxide.sh
run_component fzf 'Install fzf (interactive fuzzy finder)?' fzf.sh
run_component ripgrep 'Install ripgrep (rg)?' ripgrep.sh
run_component bat-fd 'Install bat and fd?' bat-fd.sh
run_component docker 'Install Docker Engine?' docker.sh
run_component nvidia 'Install NVIDIA Container Toolkit?' nvidia-container-toolkit.sh
run_component kubectl 'Install kubectl (optionally Minikube)?' k8s.sh
run_component direnv 'Install direnv?' direnv.sh
run_component clean 'Run apt autoremove/autoclean?' clean.sh

if (( BOOTSTRAP_DRY_RUN )); then
    log 'Dry-run complete: no packages or shell configuration were changed.'
else
    log 'Setup complete. Restart your shell to apply changes.'
    if [[ -z "$ONLY_COMPONENTS" ]] && confirm 'Reboot now?'; then
        sudo reboot
    fi
fi
