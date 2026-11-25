"""Subcommand CLI for the convenience toolkit (standard library only)."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys

from .registry import ACTIONS, BY_ID, execute
from .guidance import guide_for, command_example
from .operations import prepare, apply
from .workflows import list_workflows, run
from . import agent_setup

ROOT = Path(__file__).resolve().parents[2]
MANAGED = {"sys.terminate", "docker.start", "docker.stop", "docker.restart"}
ALIASES = {"util.json.format": "util.json-format", "util.json.minify": "util.json-minify",
           "util.base64.encode": "util.base64-encode", "util.base64.decode": "util.base64-decode",
           "util.url.encode": "util.url-encode", "util.url.decode": "util.url-decode"}
LEGACY = {
    ("env", "install"): ("--only",),
    ("env", "upgrade"): ("--upgrade",),
    ("storage", "clean"): ("--clean",),
    ("storage", "scan"): ("--clean", "--scan"),
    ("health", "doctor"): ("--doctor",),
    ("health", "preflight"): ("--preflight",),
    ("doctor",): ("--doctor",),
}


def legacy(argv):
    for prefix, flags in LEGACY.items():
        if tuple(argv[:len(prefix)]) != prefix:
            continue
        rest = argv[len(prefix):]
        if prefix == ("env", "install"):
            if not rest or any(v.startswith("-") for v in rest):
                raise ValueError("Usage: devbox env install TOOL [TOOL ...]")
            rest = [",".join(rest)]
        elif prefix == ("env", "upgrade") and rest and not rest[0].startswith("-"):
            if any(v.startswith("-") for v in rest):
                raise ValueError("Use devbox env upgrade TOOL [TOOL ...], or pass legacy flags.")
            rest = ["--only", ",".join(rest)]
        os.execv(str(ROOT / "bin/devbox"), [str(ROOT / "bin/devbox"), *flags, *rest])
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cwd = os.environ.get("DEVBOX_INVOCATION_CWD") or os.getcwd()
    try:
        if not argv or argv[0] in ("actions", "--help", "-h"):
            print("Usage: devbox CATEGORY ACTION [VALUE]\n")
            for action in ACTIONS:
                print(f"{action.id.replace('.', ' ', 1):<30} {action.description}")
            print("\nManaged: sys terminate PID, docker start|stop|restart CONTAINER (preview unless --yes)")
            print("Other: env install|upgrade, agent setup|integrate, storage scan|clean, health doctor|preflight, run [ID] [--yes]")
            return 0
        if len(argv) >= 2 and argv[-1] in ("--help", "-h"):
            key = ".".join(argv[:-1])
            key = ALIASES.get(key, key)
            guide = guide_for(key)
            if guide:
                print(f"{key}: {guide.use}\n\nExample: {command_example(key, guide)}\nResult: {guide.result}\nLimitations: {guide.limit}")
                return 0
            if len(argv) == 2:
                prefix = argv[0] + "."
                matches = [action for action in ACTIONS if action.id.startswith(prefix)]
                if matches:
                    for action in matches:
                        print(command_example(action.id, action.guide), "—", action.description)
                    return 0
        legacy(argv)
        if argv[:2] == ["agent", "setup"]:
            args = argv[2:]
            confirmed = bool(args and args[-1] == "--yes")
            if confirmed:
                args.pop()
            if args == ["--help"]:
                for item in agent_setup.ITEMS:
                    print(item.key, "—", item.description)
                return 0
            workflow = agent_setup.plan(args or agent_setup.DEFAULT)
            print(workflow.description, flush=True)
            print(shlex.join(workflow.command), flush=True)
            if confirmed:
                return run(workflow, cwd)
            print("Preview only. Add --yes to execute.")
            return 0
        if argv[:2] == ["agent", "integrate"]:
            from tui.agent_status import AGENTS
            args = argv[2:]
            confirmed = bool(args and args[-1] == "--yes")
            if confirmed:
                args.pop()
            if len(args) < 2 or args[0] not in ("rtk", "ponytail") or any(a not in AGENTS for a in args[1:]) or len(set(args[1:])) != len(args[1:]):
                raise ValueError("Usage: devbox agent integrate rtk|ponytail AGENT [AGENT ...] [--yes]")
            command = [str(ROOT / "bin/devbox"), "--only", args[0], "--agents", ",".join(args[1:])]
            print(shlex.join(command), flush=True)
            if confirmed:
                os.execv(command[0], command)
            print("Preview only. Add --yes to install this integration for the chosen agents.")
            return 0
        if argv[0] == "run":
            workflows = list_workflows()
            if len(argv) == 1:
                for w in workflows.values():
                    print(w.id, "—", w.description)
                return 0
            if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--yes"):
                raise ValueError("Usage: devbox run ID --yes")
            workflow = workflows.get(argv[1])
            if not workflow:
                raise ValueError("Unknown workflow.")
            if len(argv) == 2:
                print(shlex.join(workflow.command) + "\nPreview only. Add --yes to launch.")
                return 0
            return run(workflow, cwd)
        if len(argv) < 2:
            raise ValueError("Choose an action; run devbox actions.")
        action_id = ".".join(argv[:2])
        offset = 2
        nested = ".".join(argv[:3])
        if nested in ALIASES:
            action_id, offset = ALIASES[nested], 3
        value_args = argv[offset:]
        if action_id in MANAGED:
            confirmed = bool(value_args and value_args[-1] == "--yes")
            if confirmed:
                value_args.pop()
            if len(value_args) != 1:
                raise ValueError("Supply one exact target.")
            plan = prepare(action_id, value_args[0], cwd)
            print(plan.description)
            if confirmed:
                print(apply(plan, cwd))
            else:
                print("Preview only. Add --yes to execute after reviewing.")
            return 0
        if action_id not in BY_ID:
            raise ValueError("Unknown action; run devbox actions.")
        action = BY_ID[action_id]
        if len(value_args) > 1:
            raise ValueError("Supply one quoted value or use stdin for data utilities.")
        value = value_args[0] if value_args else ""
        if not value_args and action.prompt and action.category == "Utilities" and not sys.stdin.isatty():
            value = sys.stdin.read(1024 * 1024 + 1)
        print(execute(action_id, value, cwd))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, OverflowError) as exc:
        # Do not include exception text for secret-bearing transform inputs.
        action = BY_ID.get(locals().get("action_id"))
        detail = "Invalid input or query failed." if action and action.sensitive else str(exc)
        print("Devbox: " + detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
