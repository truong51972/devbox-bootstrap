#!/usr/bin/env bash
# Shared per-user advisory lock; held for the lifetime of mutating processes.
devbox_acquire_lock() {
    local state="$HOME/.local/state/devbox-bootstrap" lock fd
    lock="$state/operation.lock"
    (umask 077; mkdir -p -- "$state") || return 1
    if [[ -L "$lock" || ( -e "$lock" && ! -f "$lock" ) ]]; then
        echo 'Unsafe Devbox operation lock path.' >&2
        return 1
    fi
    # Fresh runtime launcher during update inherits the same open descriptor.
    if [[ "${DEVBOX_LOCK_FD:-}" =~ ^[0-9]+$ && "/proc/$$/fd/$DEVBOX_LOCK_FD" -ef "$lock" ]]; then
        if flock -n "$DEVBOX_LOCK_FD"; then return 0; fi
    fi
    (umask 077; touch -- "$lock") || return 1
    exec {fd}>>"$lock" || return 1
    if ! flock -n "$fd"; then
        exec {fd}>&-
        echo 'Another Devbox operation is running. Try again after it completes.' >&2
        return 1
    fi
    DEVBOX_LOCK_FD="$fd"
    export DEVBOX_LOCK_FD
}
