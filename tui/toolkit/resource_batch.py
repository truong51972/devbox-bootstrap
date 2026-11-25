"""Adapt a reviewed mixed resource plan to the common shell event protocol."""
from __future__ import annotations

import shlex

from tui.backend import ROOT
from tui.ui import Entry


def consent_entries(operations):
    keys = {op.key for op in operations if op.verb in ("Install", "Configure")}
    labels = (("zsh", "change_shell", "Set Zsh as login shell"),
              ("docker", "docker_group", "Join docker group (root-equivalent)"),
              ("keychain", "ssh_key", "Generate unencrypted Ed25519 key if needed"))
    return [Entry(option, label) for key, option, label in labels if key in keys]


def needs_sudo(operations, scope):
    # Development package managers can require privilege. Adoption only writes
    # a user receipt; AI CLI and skill operations are user-local.
    return scope == "development" and any(op.verb in ("Install", "Configure", "Update") and op.command
                                          for op in operations)


def batch_command(operations):
    """Hold one lock and isolate child events to prevent dependency collisions.

    Backend terminal statuses are authoritative; user-local adapters without
    events are marked COMPLETED, not falsely claimed INSTALLED/UPDATED.
    """
    script = [
        "set -e",
        "source " + shlex.quote(str(ROOT / "utils/operation-lock.sh")),
        "devbox_acquire_lock",
        'batch_events="$DEVBOX_EVENT_FILE"',
        'child_events="$(mktemp)"',
        "trap 'rm -f -- \"$child_events\"' EXIT",
        'emit() { printf "STATUS\\t%s\\t%s\\n" "$1" "$2" >> "$batch_events"; }',
    ]
    for op in operations:
        key = shlex.quote(op.key)
        if not op.command:
            script.append("emit " + key + " SKIPPED")
            continue
        script.extend([
            "emit " + key + " RUNNING",
            "printf '%s\\n' " + shlex.quote(op.verb + " " + op.name),
            ': > "$child_events"',
            'rc=0',
            'DEVBOX_EVENT_FILE="$child_events" ' + shlex.join(op.command) + " || rc=$?",
            # Preserve structured details for the exact reviewed resource only.
            "awk -F '\\t' -v key=" + key + ' \'$1=="DETAIL" && $2==key {print}\' "$child_events" >> "$batch_events"',
            'if (( rc != 0 )); then emit ' + key + ' FAILED; exit "$rc"; fi',
            "state=$(awk -F '\\t' -v key=" + key + ' \'$1=="STATUS" && $2==key && $3!="RUNNING" && $3!="QUEUED" {s=$3} END {print s}\' "$child_events")',
            'case "$state" in INSTALLED|CONFIGURED|UPDATED|UP_TO_DATE|SKIPPED|FAILED|COMPLETED) ;; *) state=COMPLETED ;; esac',
            'emit ' + key + ' "$state"',
            'if [[ "$state" == FAILED ]]; then exit 1; fi',
        ])
    return ["bash", "-c", "\n".join(script)]
