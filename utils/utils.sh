#!/usr/bin/env bash

# Structured events for the TUI, separate from verbose installer output.
devbox_event() {
    [[ -n "${DEVBOX_EVENT_FILE:-}" ]] || return 0
    printf 'STATUS\t%s\t%s\n' "$1" "$2" >> "$DEVBOX_EVENT_FILE" || true
}

log() { printf '[devbox] %s\n' "$*"; }
warn() { printf '[devbox] WARNING: %s\n' "$*" >&2; }
die() { printf '[devbox] ERROR: %s\n' "$*" >&2; return 1; }

confirm() {
    local answer key="${2:-}" env_name=''
    if [[ "${DEVBOX_TUI_MODE:-}" == 1 ]]; then
        # TUI selections are explicit, default-no decisions. Never read from
        # /dev/tty inside the managed installer subprocess.
        case "$key" in
            change_shell) env_name=DEVBOX_CONFIRM_CHANGE_SHELL ;;
            docker_group) env_name=DEVBOX_CONFIRM_DOCKER_GROUP ;;
            ssh_key) env_name=DEVBOX_CONFIRM_SSH_KEY ;;
            kubectl_replace) env_name=DEVBOX_CONFIRM_KUBECTL_REPLACE ;;
            *) warn "Unrecognized unattended confirmation: $1"; return 1 ;;
        esac
        if [[ "${!env_name:-no}" == yes ]]; then
            log "Confirmed by Devbox TUI: $key"
            return 0
        fi
        warn "Skipped optional change: $key"
        return 1
    fi
    if [[ ! -t 0 ]]; then
        warn "Skipping optional prompt without a TTY: $1"
        return 1
    fi
    read -r -p "$1 [y/N]: " answer || return 1
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

zsh_rc_file() {
    printf '%s\n' "${ZDOTDIR:-$HOME}/.zshrc"
}

shell_rc_file() {
    case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
        zsh) zsh_rc_file ;;
        bash) printf '%s\n' "$HOME/.bashrc" ;;
        *) die 'Only Bash and Zsh shell configuration is supported.' ;;
    esac
}

# Back up each existing rc file once per bootstrap execution before editing it.
declare -Ag __DEVBOX_BACKUPS=()
backup_shell_file() {
    local file="$1" stamp backup index
    [[ -f "$file" ]] || return 0
    [[ -n "${__DEVBOX_BACKUPS[$file]:-}" ]] && return 0
    stamp="${BOOTSTRAP_BACKUP_TIMESTAMP:-$(date +%Y%m%d-%H%M%S)}"
    backup="${file}.devbox-backup-${stamp}"
    index=1
    while [[ -e "$backup" ]]; do
        backup="${file}.devbox-backup-${stamp}-${index}"
        ((index+=1))
    done
    cp -p -- "$file" "$backup"
    __DEVBOX_BACKUPS[$file]="$backup"
    log "Backed up $file to $backup"
}

warn_legacy_shell_config() {
    local file
    for file in "$(zsh_rc_file)" "$HOME/.bashrc"; do
        [[ -f "$file" ]] || continue
        if grep -Eq '^# (Alias for uv python|Auto change to the last working directory on shell startup)$' "$file"; then
            warn "Legacy bootstrap blocks detected in $file; review old aliases or auto-cd manually."
        fi
    done
}

# Write a marked block once, without interpreting backslashes or shell expansions.
append_if_not_exists_in_script() {
    local marker="$1" content="$2" file="${3:-}"
    if [[ -z "$file" ]]; then
        file="$(shell_rc_file)" || return 1
    fi
    if [[ -f "$file" ]] && grep -Fqx -- "$marker" "$file"; then
        return 0
    fi
    # Older versions used different markers for these same integrations.
    # Preserve their contents and report them instead of duplicating shell hooks.
    if [[ -f "$file" ]]; then
        local old_marker=''
        case "$marker" in
            '# Zoxide setup') old_marker='# Zoxide setup for auto directory jumping' ;;
            '# kubectl completion and shortcut') old_marker='# For kubectl command auto-completion and alias' ;;
        esac
        if [[ -n "$old_marker" ]] && grep -Fqx -- "$old_marker" "$file"; then
            warn "Legacy shell integration detected ($old_marker). Skipping duplicate; review $file manually."
            return 0
        fi
    fi
    backup_shell_file "$file" || return 1
    touch "$file"
    printf '\n%s\n%s\n' "$marker" "$content" >> "$file"
}

# Edit the active Zsh rc (ZDOTDIR-aware) without mistaking commented plugins
# for enabled entries. Keep the original layout and create a backup first.
add_plugin_if_not_exists() {
    local plugin="$1" file status temp
    file="$(zsh_rc_file)" || return 1
    [[ "$plugin" =~ ^[a-zA-Z0-9_-]+$ ]] || { die "Invalid plugin name: $plugin"; return 1; }
    [[ -f "$file" ]] || { die "Missing $file (install Oh My Zsh first)"; return 1; }

    status=0
    awk -v target="$plugin" '
        function strip_comment(s) { sub(/#.*/, "", s); return s }
        /^[[:space:]]*plugins[[:space:]]*=\(/ && !seen { seen=1; active=1 }
        active {
            line=strip_comment($0)
            if (index(line, ")")) closed=1
            gsub(/[()]/, " ", line)
            gsub(/plugins[[:space:]]*=/, " ", line)
            count=split(line, words, /[[:space:]]+/)
            for (i=1; i<=count; i++) if (words[i]==target) present=1
            if (closed) active=0
        }
        END {
            if (!seen || !closed) exit 2
            exit present ? 0 : 1
        }
    ' "$file" || status=$?
    if (( status == 0 )); then return 0; fi
    if (( status != 1 )); then
        die "Malformed or missing plugins=(...) declaration in $file"
        return 1
    fi

    backup_shell_file "$file" || return 1
    temp="$(mktemp "${file}.XXXXXX")" || return 1
    if ! awk -v plugin="$plugin" '
        function strip_comment(s) { sub(/#.*/, "", s); return s }
        !done && /^[[:space:]]*plugins[[:space:]]*=\(/ { active=1 }
        active && index(strip_comment($0), ")") {
            if ($0 ~ /^[[:space:]]*\)/) print "  " plugin
            else sub(/\)/, " " plugin ")")
            done=1; active=0
        }
        { print }
    ' "$file" > "$temp"; then
        rm -f -- "$temp"
        return 1
    fi
    chmod --reference="$file" "$temp"
    mv -f -- "$temp" "$file"
}
