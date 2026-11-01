#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT

# Dry-run must emit one PLANNED record per selected installer.
event_file="$temp/install.events"
: > "$event_file"
DEVBOX_EVENT_FILE="$event_file" bash "$repo_dir/setup-ubuntu.sh" \
    --dry-run --only fzf,direnv >/dev/null
[[ "$(grep -Fxc $'STATUS\tfzf\tPLANNED' "$event_file")" -eq 1 ]]
[[ "$(grep -Fxc $'STATUS\tdirenv\tPLANNED' "$event_file")" -eq 1 ]]
[[ "$(wc -l < "$event_file")" -eq 2 ]]

# An upgrade emits RUNNING and one final result, without install mutations.
event_file="$temp/upgrade.events"
: > "$event_file"
DEVBOX_EVENT_FILE="$event_file" bash "$repo_dir/setup-ubuntu.sh" \
    --upgrade --dry-run --only fzf >/dev/null
[[ "$(grep -Fxc $'STATUS\tfzf\tRUNNING' "$event_file")" -eq 1 ]]
[[ "$(wc -l < "$event_file")" -eq 2 ]]
grep -Eq $'^STATUS\tfzf\t(SKIPPED|PLANNED)$' "$event_file"

printf 'TUI event tests passed.\n'
