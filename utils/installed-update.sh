#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 5 && $EUID != 0 ]] || exit 2
source "$root/utils/operation-lock.sh"
devbox_acquire_lock
cd "$root"
exec "$1" -m tui.toolkit.installed_managers "$2" "$3" "$4" "$5"
