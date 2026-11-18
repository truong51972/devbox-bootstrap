#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

expect_fail() {
    local needle="$1"
    shift
    local output
    if output="$(bash setup-ubuntu.sh "$@" 2>&1)"; then
        echo "Expected nonzero exit: $*" >&2
        exit 1
    fi
    if [[ "$output" != *"$needle"* ]]; then
        echo "Missing '$needle' in error: $output" >&2
        exit 1
    fi
}

expect_fail 'Unsupported agent target' --dry-run --only rtk --agents unknown
expect_fail 'Duplicate agent target' --dry-run --only rtk --agents codex,codex
expect_fail '--agents requires RTK or Ponytail' --dry-run --only skills-cli --agents codex
expect_fail 'Ponytail requires --agents' --only ponytail

# No network, sudo, agent config or package changes during dry-run.
output="$(bash setup-ubuntu.sh --dry-run --only rtk,skills-cli,ponytail --agents codex,claude)"
[[ "$output" == *'Would run: installers/rtk.sh'* ]]
[[ "$output" == *'Would run: installers/skills-cli.sh'* ]]
[[ "$output" == *'Would run: installers/ponytail.sh'* ]]
echo 'Agent extensions CLI tests passed.'
