#!/usr/bin/env bash
# Upgrade only tools already installed, using their original package/source manager.
# Does not install missing tools, perform a system-wide upgrade, or modify shell rc.

UPGRADE_APT_REFRESHED=0
UPGRADE_FOUND=0
UPGRADE_CHANGED=0
UPGRADE_BLOCKED=0
UPGRADE_ACTIVE=''
declare -A UPGRADE_STATUS=()
declare -a UPGRADE_ORDER=()

upgrade_exit() {
    local result="$1" component
    if (( result != 0 )) && [[ -n "$UPGRADE_ACTIVE" ]]; then
        UPGRADE_STATUS["$UPGRADE_ACTIVE"]=FAILED
    fi
    if (( ${#UPGRADE_ORDER[@]} > 0 )); then
        printf '\n[devbox] Upgrade summary:\n'
        for component in "${UPGRADE_ORDER[@]}"; do
            printf '  %-17s %s\n' "$component" "${UPGRADE_STATUS[$component]:-UNKNOWN}"
        done
    fi
}

apt_installed() {
    [[ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)" == 'install ok installed' ]]
}

upgrade_apt() {
    local package installed candidate
    for package in "$@"; do
        apt_installed "$package" || continue
        UPGRADE_FOUND=1
        if (( BOOTSTRAP_DRY_RUN )); then
            log "[dry-run] Would check APT updates for $package (installed only)"
            continue
        fi
        if (( ! UPGRADE_APT_REFRESHED )); then
            sudo apt-get update
            UPGRADE_APT_REFRESHED=1
        fi
        installed="$(dpkg-query -W -f='${Version}' "$package")"
        candidate="$(apt-cache policy "$package" | awk '/^[[:space:]]*Candidate:/ {print $2; exit}')"
        if [[ -z "$candidate" || "$candidate" == '(none)' ]]; then
            warn "APT has no candidate for installed package $package; preserving it."
        elif dpkg --compare-versions "$candidate" gt "$installed"; then
            log "Updating $package: $installed -> $candidate"
            sudo apt-get install -y --only-upgrade "$package"
            UPGRADE_CHANGED=1
        else
            log "$package is up to date ($installed)"
        fi
    done
}

# Only fast-forward known, clean repositories. Never reset or discard user edits.
upgrade_git() {
    local dir="$1" expected="$2" origin before after
    [[ -d "$dir/.git" ]] || return 0
    UPGRADE_FOUND=1
    origin="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
    if [[ "$origin" != *"$expected"* ]]; then
        warn "Skipping $dir: unexpected git origin ($origin)."
        UPGRADE_BLOCKED=1
        return 0
    fi
    if [[ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]]; then
        warn "Skipping $dir: tracked files have local modifications."
        UPGRADE_BLOCKED=1
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log "[dry-run] Would fast-forward $dir"
        return 0
    fi
    before="$(git -C "$dir" rev-parse HEAD)"
    git -C "$dir" pull --ff-only
    after="$(git -C "$dir" rev-parse HEAD)"
    if [[ "$before" != "$after" ]]; then UPGRADE_CHANGED=1; fi
}

upgrade_zsh_framework() {
    local dir="$HOME/.oh-my-zsh" origin before after
    [[ -f "$dir/tools/upgrade.sh" && -d "$dir/.git" ]] || return 0
    UPGRADE_FOUND=1
    origin="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
    if [[ "$origin" != *ohmyzsh/ohmyzsh* || -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]]; then
        warn 'Skipping Oh My Zsh: custom repository or local modifications.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would update Oh My Zsh via its official upgrade script'
        return 0
    fi
    before="$(git -C "$dir" rev-parse HEAD)"
    zsh "$dir/tools/upgrade.sh" -v minimal
    after="$(git -C "$dir" rev-parse HEAD)"
    if [[ "$before" != "$after" ]]; then UPGRADE_CHANGED=1; fi
}

upgrade_uv() {
    local binary="$HOME/.local/bin/uv" before after
    if apt_installed uv; then
        upgrade_apt uv
    elif [[ -x "$binary" && -f "$binary" && ! -L "$binary" ]]; then
        UPGRADE_FOUND=1
        if (( BOOTSTRAP_DRY_RUN )); then
            log '[dry-run] Would run uv self update (standalone installation)'
        else
            before="$("$binary" --version)"
            # The official installer may otherwise edit shell profiles.
            UV_NO_MODIFY_PATH=1 "$binary" self update
            after="$("$binary" --version)"
            if [[ "$before" != "$after" ]]; then UPGRADE_CHANGED=1; fi
        fi
    elif command -v uv >/dev/null 2>&1; then
        warn 'uv is managed by another installer (e.g. pipx/pip/cargo); update it with that manager.'
        UPGRADE_BLOCKED=1
    fi
}

upgrade_binary() {
    local name="$1" target_version="$2" url="$3" current_version="$4"
    local dir
    if [[ "$(command -v "$name" 2>/dev/null || true)" != "/usr/local/bin/$name" ]]; then
        if command -v "$name" >/dev/null 2>&1; then
            warn "$name is outside /usr/local/bin; preserve the external installation."
            UPGRADE_BLOCKED=1
        fi
        return 0
    fi
    UPGRADE_FOUND=1
    if [[ ! "$current_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        warn "Cannot parse installed $name version; skipping automatic replacement."
        UPGRADE_BLOCKED=1
        return 0
    fi
    if [[ ! "$target_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        die "Invalid upstream $name version: $target_version"
        return 1
    fi
    if ! dpkg --compare-versions "${target_version#v}" gt "${current_version#v}"; then
        log "$name is current or newer ($current_version vs $target_version)"
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log "[dry-run] Would upgrade $name: $current_version -> $target_version"
        return 0
    fi
    dir="$(mktemp -d)"
    # Trap local downloads in a subprocess while keeping status in the caller.
    (
        set -Eeuo pipefail
        trap 'rm -rf -- "$dir"' EXIT
        curl -fsSL "$url" -o "$dir/$name"
        curl -fsSL "${url}.sha256" -o "$dir/$name.sha256"
        printf '%s  %s\n' "$(cat "$dir/$name.sha256")" "$dir/$name" | sha256sum --check --status
        sudo install -o root -g root -m 0755 "$dir/$name" "/usr/local/bin/$name"
    )
    UPGRADE_CHANGED=1
}

upgrade_kubectl() {
    local arch installed target url
    if apt_installed kubectl; then
        upgrade_apt kubectl
        return 0
    fi
    [[ -x /usr/local/bin/kubectl ]] || return 0
    UPGRADE_FOUND=1
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would check Kubernetes stable/pinned version; no downloads in dry-run'
        return 0
    fi
    command -v curl >/dev/null 2>&1 || { die 'curl required to upgrade kubectl'; return 1; }
    target="${BOOTSTRAP_KUBECTL_VERSION:-$(curl -fsSL https://dl.k8s.io/release/stable.txt)}"
    arch="$(dpkg --print-architecture)"
    case "$arch" in amd64|arm64) ;; *) die "Unsupported architecture: $arch"; return 1 ;; esac
    installed="$(kubectl version --client -o json | sed -n 's/.*"gitVersion"[[:space:]]*:[[:space:]]*"\(v[0-9][0-9.]*\)".*/\1/p' | head -n 1)"
    url="https://dl.k8s.io/release/${target}/bin/linux/${arch}/kubectl"
    upgrade_binary kubectl "$target" "$url" "$installed"
}

upgrade_minikube() {
    local arch installed latest response url
    if apt_installed minikube; then
        upgrade_apt minikube
        return 0
    fi
    [[ -x /usr/local/bin/minikube ]] || return 0
    UPGRADE_FOUND=1
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would check latest Minikube GitHub release; no downloads in dry-run'
        return 0
    fi
    command -v curl >/dev/null 2>&1 || { die 'curl required to upgrade Minikube'; return 1; }
    response="$(curl -fsSL --connect-timeout 10 --max-time 30 https://api.github.com/repos/kubernetes/minikube/releases/latest)"
    latest="$(printf '%s\n' "$response" | sed -n 's/^[[:space:]]*"tag_name":[[:space:]]*"\(v[0-9][0-9.]*\)".*/\1/p')"
    [[ "$latest" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { die 'Could not parse latest Minikube release'; return 1; }
    installed="$(minikube version --short | grep -Eo '^v[0-9]+\.[0-9]+\.[0-9]+' || true)"
    arch="$(dpkg --print-architecture)"
    case "$arch" in amd64|arm64) ;; *) die "Unsupported architecture: $arch"; return 1 ;; esac
    url="https://github.com/kubernetes/minikube/releases/download/${latest}/minikube-linux-${arch}"
    upgrade_binary minikube "$latest" "$url" "$installed"
}

upgrade_component() {
    local component="$1"
    UPGRADE_FOUND=0
    UPGRADE_CHANGED=0
    UPGRADE_BLOCKED=0
    UPGRADE_ACTIVE="$component"
    UPGRADE_ORDER+=("$component")
    UPGRADE_STATUS["$component"]=FAILED
    case "$component" in
        zsh)
            upgrade_apt zsh
            upgrade_zsh_framework
            upgrade_git "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-autosuggestions" 'zsh-users/zsh-autosuggestions' ;;
        powerlevel10k)
            upgrade_git "$HOME/powerlevel10k" 'romkatv/powerlevel10k' ;;
        uv) upgrade_uv ;;
        keychain) upgrade_apt keychain ;;
        zoxide) upgrade_apt zoxide ;;
        fzf) upgrade_apt fzf ;;
        ripgrep) upgrade_apt ripgrep ;;
        bat-fd) upgrade_apt bat fd-find ;;
        direnv) upgrade_apt direnv ;;
        docker)
            upgrade_apt docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            if (( UPGRADE_CHANGED )); then warn 'Docker packages updated; running containers/daemon may be restarted.'; fi ;;
        nvidia) upgrade_apt nvidia-container-toolkit ;;
        kubectl) upgrade_kubectl ;;
        minikube) upgrade_minikube ;;
        clean)
            log 'APT housekeeping is not an upgradeable tool.'
            ;;
        *) die "Unsupported upgrade component: $component"; return 1 ;;
    esac
    if (( BOOTSTRAP_DRY_RUN && UPGRADE_FOUND )); then
        UPGRADE_STATUS["$component"]=PLANNED
    elif (( UPGRADE_CHANGED )); then
        UPGRADE_STATUS["$component"]=UPDATED
    elif (( UPGRADE_BLOCKED )); then
        UPGRADE_STATUS["$component"]=SKIPPED
    elif (( UPGRADE_FOUND )); then
        UPGRADE_STATUS["$component"]=UP_TO_DATE
    else
        UPGRADE_STATUS["$component"]=SKIPPED
    fi
    UPGRADE_ACTIVE=''
}

upgrade_main() {
    local component
    trap 'upgrade_exit "$?"' EXIT
    log 'Upgrade installed devbox tools only; no system-wide upgrade.'
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] No package lists, downloads or files will be changed.'
    fi
    for component in zsh powerlevel10k uv keychain zoxide fzf ripgrep bat-fd docker nvidia kubectl minikube direnv; do
        if [[ -n "$ONLY_COMPONENTS" && ",$ONLY_COMPONENTS," != *",$component,"* ]]; then
            continue
        fi
        upgrade_component "$component"
    done
    log 'Upgrade finished. Restart the shell if shell-related tools changed.'
}
