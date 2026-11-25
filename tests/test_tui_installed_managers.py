"""Installed package manager detection and explicit updates."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tui.toolkit import installed_managers as m
from tui.toolkit.resources import Resource, plan


class InstalledManagerTests(unittest.TestCase):
    def test_npm_arbitrary_user_prefix(self):
        with TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "nvm/version"
            package = prefix / "lib/node_modules/@openai/codex"
            package.mkdir(parents=True)
            (package / "cli.js").touch()
            (package / "package.json").write_text(json.dumps({"name": "@openai/codex", "version": "1.2.3", "bin": {"codex": "cli.js"}}))
            binary = prefix / "bin/codex"
            binary.parent.mkdir()
            binary.symlink_to(package / "cli.js")
            with patch.object(m.shutil, "which", return_value="/usr/bin/npm"):
                route = m.detect("codex", str(binary))
            self.assertEqual(route.kind, "npm")
            self.assertEqual(route.prefix, str(prefix))
            self.assertEqual(route.version, "1.2.3")

    def test_unrelated_symlink_is_not_npm_install(self):
        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "bin/codex"
            binary.parent.mkdir()
            target = Path(tmp) / "external"
            target.touch()
            binary.symlink_to(target)
            self.assertIsNone(m.detect("codex", str(binary)))

    def test_current_explicit_update_not_bulk(self):
        row = Resource("codex", "Codex", "AI", True, "Installed",
                       update="Current", can_update=True, update_command=("true",))
        self.assertEqual(row.action, "Update")
        self.assertFalse(row.bulk_update)
        self.assertEqual(plan("ai", (row,), ["codex"])[0].command, ("true",))

    def test_changed_route_is_rejected(self):
        with patch.object(m.shutil, "which", return_value="/changed/codex"), patch.object(m, "detect", return_value=None), patch.object(m.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                m.execute("codex", "/old/codex", "npm", "/old")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
