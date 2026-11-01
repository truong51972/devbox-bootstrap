#!/usr/bin/env bash
# Read-only diagnostic for installed devbox tools and common configuration issues.
# Never pulls images, invokes sudo, or modifies shell/system configuration.

doctor_main() {
    local problems=0 rc zsh_rc
    log 'Devbox Health Check'
    zsh_rc="$(zsh_rc_file)"
    case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
        zsh) rc="$zsh_rc" ;;
        bash) rc="$HOME/.bashrc" ;;
        *) rc='' ;;
    esac

    doctor_bin() {
        local label="$1" cmd="$2" fallback="${3:-}"
        if command -v "$cmd" >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/$cmd" ]]; then
            log "[OK]   $label: $cmd available"
        elif [[ -n "$fallback" ]] && { command -v "$fallback" >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/$fallback" ]]; }; then
            log "[OK]   $label: $fallback available"
        else
            log "[--]   $label: not installed"
        fi
    }
    doctor_hook() {
        local label="$1" marker="$2"
        if [[ -n "$rc" && -f "$rc" ]] && grep -Fqx -- "$marker" "$rc"; then
            log "[OK]   $label: hook configured in $rc (restart shell if newly installed)"
        else
            warn "[--]   $label: no devbox-managed hook found in current shell config"
        fi
    }

    doctor_bin Zsh zsh
    if command -v zsh >/dev/null 2>&1; then
        if [[ -f "$zsh_rc" ]]; then
            log "[OK]   Zsh rc: $zsh_rc"
        else
            warn "[--]   Zsh rc missing: $zsh_rc"
        fi
        if [[ -f "$HOME/.oh-my-zsh/oh-my-zsh.sh" ]]; then
            log '[OK]   Oh My Zsh: installed'
        else
            warn '[--]   Oh My Zsh: not installed'
        fi
    fi
    doctor_bin uv uv
    doctor_bin fzf fzf
    if command -v fzf >/dev/null 2>&1; then doctor_hook fzf '# devbox: fzf shell integration'; fi
    doctor_bin ripgrep rg
    doctor_bin bat bat batcat
    doctor_bin fd fd fdfind
    doctor_bin direnv direnv
    if command -v direnv >/dev/null 2>&1; then doctor_hook direnv '# devbox: direnv shell hook'; fi
    doctor_bin zoxide zoxide
    if command -v zoxide >/dev/null 2>&1; then doctor_hook zoxide '# Zoxide setup'; fi
    doctor_bin keychain keychain
    if command -v keychain >/dev/null 2>&1; then doctor_hook keychain '# Keychain setup'; fi

    if command -v docker >/dev/null 2>&1; then
        if docker info >/dev/null 2>&1; then
            log '[OK]   Docker: daemon reachable'
            if docker compose version >/dev/null 2>&1; then
                log '[OK]   Docker Compose: available'
            else
                warn '[!!]   Docker Compose: unavailable'
                problems=$((problems+1))
            fi
        else
            warn '[!!]   Docker: CLI installed but daemon unreachable'
            problems=$((problems+1))
        fi
    else
        log '[--]   Docker: not installed'
    fi

    if command -v nvidia-ctk >/dev/null 2>&1; then
        log '[OK]   NVIDIA Container Toolkit: installed'
        if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
            if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
                log '[OK]   NVIDIA Docker runtime: registered'
            else
                warn '[!!]   NVIDIA Docker runtime: not registered'
                problems=$((problems+1))
            fi
        else
            warn '[--]   NVIDIA Docker runtime: cannot inspect without a running Docker daemon'
        fi
        if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
            log '[OK]   NVIDIA host utilities: GPU reachable'
        else
            warn '[--]   NVIDIA host utilities: no reachable GPU detected'
        fi
        log '[NOTE] Docker container GPU access is not verified (no images are pulled).'
    else
        log '[--]   NVIDIA Container Toolkit: not installed'
    fi

    if command -v kubectl >/dev/null 2>&1; then
        if kubectl version --client >/dev/null 2>&1; then
            log '[OK]   kubectl: client responds (cluster connection not tested)'
        else
            warn '[!!]   kubectl: client failed'
            problems=$((problems+1))
        fi
    else
        log '[--]   kubectl: not installed'
    fi
    doctor_bin Minikube minikube

    if (( problems > 0 )); then
        warn "Doctor detected $problems functional issue(s)."
        return 1
    fi
    log 'Doctor complete (missing optional tools are informational).'
}
