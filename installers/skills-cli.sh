#!/usr/bin/env bash
# Skills CLI - https://github.com/vercel-labs/skills
# User-scoped npm install; no sudo, no agents or skills are modified.
command -v node >/dev/null 2>&1 || { die 'Skills CLI requires Node.js >= 22.20.'; return 1; }
command -v npm >/dev/null 2>&1 || { die 'Skills CLI requires npm.'; return 1; }
version="$(node -p 'process.versions.node' 2>/dev/null)" || {
    die 'Cannot determine Node.js version.'; return 1;
}
major="${version%%.*}"
minor="${version#*.}"
minor="${minor%%.*}"
if (( major < 22 || (major == 22 && minor < 20) )); then
    die "Skills CLI needs Node.js >= 22.20 (found $version)."; return 1
fi
receipt_dir="$HOME/.local/state/devbox-bootstrap/managed"
receipt="$receipt_dir/skills-cli"
target="$HOME/.local/bin/skills"
existing="$(command -v skills || true)"
if [[ -n "$existing" && "$existing" != "$target" ]]; then
    warn "Preserving externally managed Skills CLI at $existing."
    "$existing" --help >/dev/null 2>&1 || {
        die 'Existing skills command failed its smoke check.'; return 1;
    }
elif [[ -e "$target" || -L "$target" ]]; then
    # Existing user-local binary is not necessarily Devbox-owned.
    [[ -x "$target" ]] && "$target" --help >/dev/null 2>&1 || {
        die 'Existing user-local skills command failed its smoke check.'; return 1;
    }
    if [[ ! -f "$receipt" ]]; then
        warn "Preserving user-local Skills CLI without a Devbox ownership receipt."
    else
        log 'Skills CLI already installed by Devbox; use --upgrade to update.'
    fi
else
    npm install --global --prefix "$HOME/.local" --no-audit --no-fund skills@latest
    "$target" --help >/dev/null 2>&1 || {
        die 'Skills CLI verification failed.'; return 1;
    }
    mkdir -p "$receipt_dir"
    printf '%s\n' "$target" > "$receipt"
    chmod 600 "$receipt"
fi
log 'Skills CLI ready; install actual skills with: skills add <source> -g -a <agent>'
