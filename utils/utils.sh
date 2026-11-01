#!/usr/bin/env bash

log() { printf '[devbox] %s\n' "$*"; }
warn() { printf '[devbox] WARNING: %s\n' "$*" >&2; }
die() { printf '[devbox] ERROR: %s\n' "$*" >&2; return 1; }

confirm() {
    local answer
    if [[ ! -t 0 ]]; then
        die 'An interactive terminal is required to answer setup questions.'
        return 1
    fi
    read -r -p "$1 [y/N]: " answer || return 1
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

shell_rc_file() {
    case "${BOOTSTRAP_TARGET_SHELL:-${SHELL##*/}}" in
        zsh) printf '%s\n' "$HOME/.zshrc" ;;
        bash) printf '%s\n' "$HOME/.bashrc" ;;
        *) die 'Only Bash and Zsh shell configuration is supported.' ;;
    esac
}

# Write a marked block once, without interpreting backslashes or shell expansions.
append_if_not_exists_in_script() {
    local marker="$1" content="$2" file="${3:-}"
    if [[ -z "$file" ]]; then
        file="$(shell_rc_file)" || return 1
    fi
    touch "$file"
    if ! grep -Fqx -- "$marker" "$file"; then
        printf '\n%s\n%s\n' "$marker" "$content" >> "$file"
    fi
}

# Works with either a one-line or multiline Oh My Zsh plugins=(...) declaration.
add_plugin_if_not_exists() {
    local plugin="$1" file="$HOME/.zshrc" block temp
    [[ "$plugin" =~ ^[a-zA-Z0-9_-]+$ ]] || { die "Invalid plugin name: $plugin"; return 1; }
    [[ -f "$file" ]] || { die "Missing $file (install Oh My Zsh first)"; return 1; }

    block="$(awk '
        /^[[:space:]]*plugins=\(/ { active=1 }
        active { print; if (index($0, ")")) exit }
    ' "$file")"
    [[ -n "$block" && "$block" == *')'* ]] || { die "Cannot locate plugins=(...) in $file"; return 1; }
    if printf '%s\n' "$block" | grep -Eq "(^|[[:space:]]|\\()${plugin}($|[[:space:]]|\\))"; then
        return 0
    fi

    temp="$(mktemp "${file}.XXXXXX")" || return 1
    if ! awk -v plugin="$plugin" '
        !done && /^[[:space:]]*plugins=\(/ { active=1 }
        active && index($0, ")") {
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
