#!/usr/bin/env bash
# uv: install Python versions, manage environments and project dependencies.
# Docs: https://docs.astral.sh/uv/
if command -v uv >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/uv" ]]; then
    log 'uv already installed; skipping.'
else
    sudo apt-get install -y curl ca-certificates
    ( set -Eeuo pipefail
      temp="$(mktemp)"
      trap 'rm -f -- "$temp"' EXIT
      curl -fsSL https://astral.sh/uv/install.sh -o "$temp"
      sh "$temp"
    )
fi
