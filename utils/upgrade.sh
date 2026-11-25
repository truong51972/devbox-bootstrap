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
        devbox_event "$UPGRADE_ACTIVE" FAILED
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
    local package installed candidate policy
    for package in "$@"; do
        apt_installed "$package" || continue
        UPGRADE_FOUND=1
        if (( BOOTSTRAP_DRY_RUN )); then
            log "[dry-run] Would check APT updates for $package (installed only)"
            continue
        fi
        if (( ! UPGRADE_APT_REFRESHED )); then
            if ! sudo apt-get update; then
                die 'APT index refresh failed; check your configured APT repositories.'
                return 1
            fi
            UPGRADE_APT_REFRESHED=1
        fi
        if ! installed="$(dpkg-query -W -f='${Version}' "$package")"; then
            warn "Could not read installed version for $package; skipping it."
            UPGRADE_BLOCKED=1
            continue
        fi
        # Consume the complete apt-cache output. Exiting awk early can SIGPIPE
        # apt-cache and abort this function under 'set -o pipefail'.
        if ! policy="$(apt-cache policy "$package")"; then
            warn "Could not read APT policy for $package; skipping it."
            UPGRADE_BLOCKED=1
            continue
        fi
        candidate="$(awk '/^[[:space:]]*Candidate:/ && !found {value=$2; found=1} END {print value}' <<< "$policy")"
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
    if ! trusted_github_origin "$origin" "$expected"; then
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
    if ! command -v zsh >/dev/null 2>&1; then
        warn 'Cannot update Oh My Zsh because Zsh is not installed.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    origin="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
    if ! trusted_github_origin "$origin" ohmyzsh/ohmyzsh || [[ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]]; then
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

# Tolerate transient TCP resets and GitHub throttling without retrying
# checksum mismatches (which must still fail before replacing a binary).
upgrade_fetch() {
    curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors --connect-timeout 10 "$@"
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
    if ! managed_binary_matches "$name" "/usr/local/bin/$name"; then
        warn "$name has no matching Devbox ownership receipt; preserve external/legacy binary."
        UPGRADE_BLOCKED=1
        return 0
    fi
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
        upgrade_fetch --max-time 300 "$url" -o "$dir/$name"
        upgrade_fetch --max-time 30 "${url}.sha256" -o "$dir/$name.sha256"
        printf '%s  %s\n' "$(cat "$dir/$name.sha256")" "$dir/$name" | sha256sum --check --status
        managed_binary_matches "$name" "/usr/local/bin/$name" || { die "Binary changed during download"; return 1; }
        sudo install -o root -g root -m 0755 "$dir/$name" "/usr/local/bin/$name"
        record_managed_binary "$name" "$dir/$name"
    )
    UPGRADE_CHANGED=1
}

upgrade_kubectl() {
    local arch installed target url
    if apt_installed kubectl; then
        if [[ -n "${BOOTSTRAP_KUBECTL_VERSION:-}" ]]; then
            die 'Pinning kubectl is only supported for Devbox-managed /usr/local/bin binaries, not APT packages.'
            return 1
        fi
        upgrade_apt kubectl
        return 0
    fi
    [[ -x /usr/local/bin/kubectl ]] || return 0
    UPGRADE_FOUND=1
    if ! managed_binary_matches kubectl /usr/local/bin/kubectl; then
        warn 'kubectl has no matching Devbox ownership receipt; preserving it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
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
    if ! managed_binary_matches minikube /usr/local/bin/minikube; then
        warn 'minikube has no matching Devbox ownership receipt; preserving it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would check latest Minikube GitHub release; no downloads in dry-run'
        return 0
    fi
    command -v curl >/dev/null 2>&1 || { die 'curl required to upgrade Minikube'; return 1; }
    response="$(upgrade_fetch --max-time 30 https://api.github.com/repos/kubernetes/minikube/releases/latest)"
    latest="$(printf '%s\n' "$response" | sed -n 's/^[[:space:]]*"tag_name":[[:space:]]*"\(v[0-9][0-9.]*\)".*/\1/p')"
    [[ "$latest" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { die 'Could not parse latest Minikube release'; return 1; }
    installed="$(minikube version --short | grep -Eo '^v[0-9]+\.[0-9]+\.[0-9]+' || true)"
    arch="$(dpkg --print-architecture)"
    case "$arch" in amd64|arm64) ;; *) die "Unsupported architecture: $arch"; return 1 ;; esac
    url="https://github.com/kubernetes/minikube/releases/download/${latest}/minikube-linux-${arch}"
    upgrade_binary minikube "$latest" "$url" "$installed"
}

# RTK is only self-updated when Devbox owns the user-local binary.
upgrade_rtk() {
    local binary="$HOME/.local/bin/rtk" before after tmp
    if [[ ! -x "$binary" ]]; then
        if command -v rtk >/dev/null 2>&1; then
            warn 'RTK is externally managed; update it with its package manager.'
            UPGRADE_BLOCKED=1
        fi
        return 0
    fi
    local receipt="$HOME/.local/state/devbox-bootstrap/managed/rtk.sha256" expected current
    if [[ ! -f "$receipt" ]]; then
        warn 'RTK binary has no Devbox ownership receipt; refusing to overwrite it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    expected="$(cat "$receipt")"
    current="$(sha256sum "$binary" | awk '{print $1}')"
    if [[ ! "$expected" =~ ^[0-9a-f]{64}$ || "$expected" != "$current" ]]; then
        warn 'RTK binary differs from Devbox-installed version; refusing to overwrite it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    UPGRADE_FOUND=1
    if ! "$binary" gain >/dev/null 2>&1; then
        warn 'The user-local rtk binary is not the rtk-ai token optimizer.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would refresh RTK with upstream SHA-256 verification'
        return 0
    fi
    before="$("$binary" --version)"
    tmp="$(mktemp -d)"
    if ! upgrade_fetch --connect-timeout 10 \
        https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh -o "$tmp/install.sh"; then
        rm -rf -- "$tmp"
        die 'Unable to download RTK updater.'; return 1
    fi
    if ! RTK_SKIP_CHECKSUM=0 RTK_INSTALL_DIR="$HOME/.local/bin" sh "$tmp/install.sh"; then
        rm -rf -- "$tmp"
        die 'RTK upgrade failed.'; return 1
    fi
    rm -rf -- "$tmp"
    "$binary" gain >/dev/null 2>&1 || { die 'Upgraded RTK failed identity check.'; return 1; }
    after="$("$binary" --version)"
    sha256sum "$binary" | awk '{print $1}' > "$receipt"
    chmod 600 "$receipt"
    [[ "$before" == "$after" ]] || UPGRADE_CHANGED=1
}

upgrade_skills_cli() {
    local package="$HOME/.local/lib/node_modules/skills/package.json" before after
    if [[ ! -f "$package" || ! -x "$HOME/.local/bin/skills" ]]; then
        if command -v skills >/dev/null 2>&1; then
            warn 'Skills CLI is externally managed; update it with its original manager.'
            UPGRADE_BLOCKED=1
        fi
        return 0
    fi
    local receipt="$HOME/.local/state/devbox-bootstrap/managed/skills-cli"
    if [[ ! -f "$receipt" || "$(cat "$receipt")" != "$HOME/.local/bin/skills" ]]; then
        warn 'Skills CLI has no matching Devbox ownership receipt; refusing to overwrite it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    if [[ "$(readlink -f "$HOME/.local/bin/skills")" != "$HOME/.local/lib/node_modules/skills/bin/cli.mjs" ]]; then
        warn 'Skills CLI entrypoint differs from Devbox package; refusing to overwrite it.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    UPGRADE_FOUND=1
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        warn 'Skills CLI upgrade requires Node.js and npm.'
        UPGRADE_BLOCKED=1
        return 0
    fi
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] Would refresh user-local Skills CLI with npm'
        return 0
    fi
    before="$(node -p "require(process.argv[1]).version" "$package")"
    npm install --global --prefix "$HOME/.local" --no-audit --no-fund skills@latest
    after="$(node -p "require(process.argv[1]).version" "$package")"
    "$HOME/.local/bin/skills" --help >/dev/null 2>&1 || {
        die 'Skills CLI upgrade verification failed.'; return 1;
    }
    [[ "$before" == "$after" ]] || UPGRADE_CHANGED=1
}

upgrade_component() {
    local component="$1"
    UPGRADE_FOUND=0
    UPGRADE_CHANGED=0
    UPGRADE_BLOCKED=0
    UPGRADE_ACTIVE="$component"
    UPGRADE_ORDER+=("$component")
    UPGRADE_STATUS["$component"]=FAILED
    devbox_event "$component" RUNNING
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
        nvidia) upgrade_apt nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container1 libnvidia-container-tools ;;
        kubectl) upgrade_kubectl ;;
        minikube) upgrade_minikube ;;
        rtk) upgrade_rtk ;;
        skills-cli) upgrade_skills_cli ;;
        ponytail)
            if compgen -G "$HOME/.local/state/devbox-bootstrap/agent-extensions/ponytail-*" > /dev/null; then
                UPGRADE_FOUND=1
                UPGRADE_BLOCKED=1
                warn 'Ponytail is managed by each agent. Update it using that agent plugin manager.'
            fi ;;
        tmux|btop|gh|jq) upgrade_apt "$component" ;;
        clean)
            log 'APT housekeeping is not an upgradeable tool.'
            ;;
        *) die "Unsupported upgrade component: $component"; return 1 ;;
    esac
    if (( BOOTSTRAP_DRY_RUN && UPGRADE_BLOCKED )); then
        UPGRADE_STATUS["$component"]=SKIPPED
    elif (( BOOTSTRAP_DRY_RUN && UPGRADE_FOUND )); then
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
    devbox_event "$component" "${UPGRADE_STATUS[$component]}"
    UPGRADE_ACTIVE=''
}

upgrade_main() {
    local component
    trap 'upgrade_exit "$?"' EXIT
    log 'Upgrade installed devbox tools only; no system-wide upgrade.'
    if (( BOOTSTRAP_DRY_RUN )); then
        log '[dry-run] No package lists, downloads or files will be changed.'
    fi
    for component in zsh powerlevel10k uv keychain zoxide fzf ripgrep bat-fd docker nvidia kubectl minikube direnv rtk skills-cli ponytail tmux btop gh jq; do
        if [[ -n "$ONLY_COMPONENTS" && ",$ONLY_COMPONENTS," != *",$component,"* ]]; then
            continue
        fi
        upgrade_component "$component"
    done
    log 'Upgrade finished. Restart the shell if shell-related tools changed.'
}
