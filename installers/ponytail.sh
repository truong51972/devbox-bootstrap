#!/usr/bin/env bash
# Ponytail - https://github.com/DietrichGebert/ponytail
# Install official plugins/extensions for explicitly selected coding agents.
if (( ${#DEVBOX_AGENT_TARGETS_ARRAY[@]} == 0 )); then
    die 'Ponytail requires at least one --agents target.'; return 1
fi
# Validate *every* target before making any changes to plugin registrations.
for agent in "${DEVBOX_AGENT_TARGETS_ARRAY[@]}"; do
    command -v "$agent" >/dev/null 2>&1 || {
        die "Ponytail target $agent is not on PATH."; return 1;
    }
    case "$agent" in
        claude|codex)
            command -v node >/dev/null 2>&1 || {
                die "Ponytail $agent lifecycle hooks need Node.js on PATH."; return 1;
            } ;;
    esac
done
for agent in "${DEVBOX_AGENT_TARGETS_ARRAY[@]}"; do
    log "Installing Ponytail upstream integration for $agent"
    case "$agent" in
        claude)
            claude plugin marketplace add DietrichGebert/ponytail
            claude plugin install ponytail@ponytail --yes ;;
        codex)
            codex plugin marketplace add DietrichGebert/ponytail
            codex plugin add ponytail@ponytail ;;
        copilot)
            copilot plugin marketplace add DietrichGebert/ponytail
            copilot plugin install ponytail@ponytail ;;
        opencode)
            opencode plugin add @dietrichgebert/ponytail ;;
        gemini)
            gemini extensions install https://github.com/DietrichGebert/ponytail ;;
        agy)
            agy plugin install https://github.com/DietrichGebert/ponytail ;;
        *) die "Unsupported Ponytail agent: $agent"; return 1 ;;
    esac
    # Receipt, not an authoritative inspection of the agent's plugin state.
    marker_dir="$HOME/.local/state/devbox-bootstrap/agent-extensions"
    mkdir -p "$marker_dir"
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$marker_dir/ponytail-$agent"
    log "Ponytail command completed for $agent. Restart the agent to load it."
done
log 'Codex users: open /hooks and explicitly review/trust Ponytail lifecycle hooks.'
