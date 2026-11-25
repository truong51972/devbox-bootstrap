#!/usr/bin/env bash
# Hold the same inherited operation lock as the resource batch.
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 2 && $EUID != 0 ]] || exit 2
source "$root/utils/operation-lock.sh"
devbox_acquire_lock
cd "$root"
exec "$1" -m tui.toolkit.ai_resource_updates "$2"
