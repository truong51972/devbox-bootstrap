#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
export HOME="$scratch/home"
mkdir -p "$HOME/.local/bin" "$scratch/bin"
export PATH="$scratch/bin:$HOME/.local/bin:$PATH"
export DEVBOX_LOG="$scratch/commands"
: > "$DEVBOX_LOG"
log() { :; }
warn() { :; }
die() { printf '%s\n' "$*" >&2; return 1; }

# Fake agent CLIs record actions without reaching any external systems.
cat > "$scratch/bin/claude" <<'EOF'
#!/usr/bin/env bash
printf 'claude %s\n' "$*" >> "$DEVBOX_LOG"
EOF
cat > "$scratch/bin/codex" <<'EOF'
#!/usr/bin/env bash
printf 'codex %s\n' "$*" >> "$DEVBOX_LOG"
EOF
cat > "$scratch/bin/agy" <<'EOF'
#!/usr/bin/env bash
printf 'agy %s\n' "$*" >> "$DEVBOX_LOG"
EOF
cat > "$scratch/bin/node" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "-p" ]]; then printf '22.20.0\n'; fi
EOF
cat > "$scratch/bin/npm" <<'EOF'
#!/usr/bin/env bash
echo 'unexpected npm installation' >&2
exit 90
EOF
chmod +x "$scratch/bin/"*

# Ponytail should run two supported upstream commands and use --yes for headless Claude.
DEVBOX_AGENT_TARGETS_ARRAY=(claude codex agy)
source installers/ponytail.sh
grep -Fqx 'claude plugin marketplace add DietrichGebert/ponytail' "$DEVBOX_LOG"
grep -Fqx 'claude plugin install ponytail@ponytail --yes' "$DEVBOX_LOG"
grep -Fqx 'codex plugin marketplace add DietrichGebert/ponytail' "$DEVBOX_LOG"
grep -Fqx 'codex plugin add ponytail@ponytail' "$DEVBOX_LOG"
[[ -s "$HOME/.local/state/devbox-bootstrap/agent-extensions/ponytail-claude" ]]
grep -Fqx 'agy plugin install https://github.com/DietrichGebert/ponytail' "$DEVBOX_LOG"
[[ -s "$HOME/.local/state/devbox-bootstrap/agent-extensions/ponytail-agy" ]]

# Missing agent must fail before registering any plugin.
: > "$DEVBOX_LOG"
DEVBOX_AGENT_TARGETS_ARRAY=(claude does-not-exist-devbox)
if ( source installers/ponytail.sh ); then
    echo 'expected missing agent rejection' >&2; exit 1
fi
[[ ! -s "$DEVBOX_LOG" ]]

# RTK: respect existing user-local executable, do not record ownership or re-download.
cat > "$HOME/.local/bin/rtk" <<'EOF'
#!/usr/bin/env bash
case "$1" in
    gain) exit 0 ;;
    init) printf 'rtk %s\n' "$*" >> "$DEVBOX_LOG" ;;
    *) exit 0 ;;
esac
EOF
chmod +x "$HOME/.local/bin/rtk"
: > "$DEVBOX_LOG"
DEVBOX_AGENT_TARGETS_ARRAY=(codex agy)
source installers/rtk.sh
grep -Fqx 'rtk init -g --codex' "$DEVBOX_LOG"
grep -Fqx 'rtk init -g --agent antigravity' "$DEVBOX_LOG"
[[ ! -f "$HOME/.local/state/devbox-bootstrap/managed/rtk.sha256" ]]

# Skills CLI must not overwrite a user-local CLI without a receipt.
cat > "$HOME/.local/bin/skills" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == "--help" ]]
EOF
chmod +x "$HOME/.local/bin/skills"
source installers/skills-cli.sh
[[ ! -e "$HOME/.local/state/devbox-bootstrap/managed/skills-cli" ]]

# A missing RTK receipt means upgrades must refuse replacement without any fetch.
source utils/upgrade.sh
UPGRADE_BLOCKED=0
UPGRADE_FOUND=0
upgrade_rtk
[[ "$UPGRADE_BLOCKED" == 1 ]]
[[ "$UPGRADE_FOUND" == 0 ]]

echo 'Agent extension stub installer tests passed.'
