#!/usr/bin/env bash
# Read-only host inspection. No package installation or config mutation.
log 'Preflight — host inspection'
log "OS: ${PRETTY_NAME:-${ID:-unknown}}"
log "Architecture: $(uname -m)"
log "User shell: ${SHELL:-unknown}"

if [[ -r /proc/sys/kernel/osrelease ]] && grep -qi microsoft /proc/sys/kernel/osrelease; then
    log 'Environment: WSL (Windows Subsystem for Linux)'
    if ! ps -p 1 -o comm= 2>/dev/null | grep -qx systemd; then
        warn 'systemd is not PID 1. Docker service commands may require WSL systemd setup.'
    fi
else
    log 'Environment: native Linux (or non-WSL VM/container)'
fi

if command -v docker >/dev/null 2>&1; then
    log "Docker: $(docker --version 2>/dev/null || echo installed)"
    if ! docker info >/dev/null 2>&1; then
        warn 'Docker CLI exists but the current user cannot reach the Docker daemon.'
    fi
else
    log 'Docker: not installed'
fi
if command -v nvidia-smi >/dev/null 2>&1; then
    log 'NVIDIA driver utilities: available'
else
    log 'NVIDIA driver utilities: not detected'
fi
for tool in zsh uv fzf rg bat batcat fd fdfind direnv kubectl; do
    if command -v "$tool" >/dev/null 2>&1; then
        log "$tool: installed"
    fi
done
if command -v df >/dev/null 2>&1; then
    available_kib="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
    if [[ "$available_kib" =~ ^[0-9]+$ ]]; then
        log "Free space on home filesystem: $((available_kib / 1024 / 1024)) GiB"
        if (( available_kib < 5242880 )); then
            warn 'Less than 5 GiB free on home filesystem; package installations may fail.'
        fi
    fi
fi
