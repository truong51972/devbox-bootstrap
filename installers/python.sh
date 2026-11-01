#!/usr/bin/env bash
if command -v uv >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/uv" ]]; then
    log 'uv already installed; skipping.'
else
    ( set -Eeuo pipefail
      temp="$(mktemp)"
      trap 'rm -f -- "$temp"' EXIT
      curl -fsSL https://astral.sh/uv/install.sh -o "$temp"
      sh "$temp"
    )
fi
