#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 3 && $EUID != 0 ]] || exit 2
source "$root/utils/operation-lock.sh"
devbox_acquire_lock
cd "$root"
exec "$1" -m tui.toolkit.binary_adoption "$2" "$3"
