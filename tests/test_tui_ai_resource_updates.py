"""Regression tests for targeted, source-verified AI resource updates."""
import unittest
from pathlib import Path
from unittest.mock import patch
from tui.toolkit import ai_resource_updates as updates
from tui.toolkit.resources import Resource, plan

NAME = "context-management"
OLD = "a" * 40
NEW = "b" * 40
ENTRY = {"source": "truong51972/coding-kit", "sourceType": "github",
         "sourceUrl": "https://github.com/truong51972/coding-kit.git",
         "skillPath": "skills/" + NAME + "/SKILL.md", "skillFolderHash": OLD}


class AIResourceUpdatesTests(unittest.TestCase):
    def test_skill_status_and_source(self):
        with patch.object(updates, "skill_path", return_value=Path(__file__)), patch.object(updates.shutil, "which", return_value="/bin/skills"):
            current = updates.skill_update(NAME, {NAME: ENTRY}, {"skills/" + NAME: OLD})
            available = updates.skill_update(NAME, {NAME: ENTRY}, {"skills/" + NAME: NEW})
            wrong = updates.skill_update(NAME, {NAME: dict(ENTRY, source="other/repo")}, {"skills/" + NAME: NEW})
            pinned = updates.skill_update(NAME, {NAME: dict(ENTRY, ref="v1")}, {"skills/" + NAME: NEW})
            self.assertEqual(current.state, "Current")
            self.assertEqual(available.state, "Available")
            self.assertTrue(available.eligible)
            self.assertFalse(wrong.eligible)
            self.assertFalse(pinned.eligible)

    def test_skill_update_is_exact_and_global(self):
        before = updates.Update("Available", OLD, NEW, eligible=True)
        after = updates.Update("Current", NEW, NEW, eligible=True)
        with patch.object(updates, "skill_update", side_effect=[before, after]), patch.object(updates, "skill_lock", return_value={}), patch.object(updates, "kit_tree", return_value={}), patch.object(updates.subprocess, "run") as run:
            updates.execute("skill:" + NAME)
            self.assertEqual(run.call_args.args[0], ["skills", "update", NAME, "-g", "-y"])
            run.assert_called_once()

    def test_ponytail_updates_only_selected_marketplace(self):
        before = updates.Update("Available", "5.1.0", "5.2.0", eligible=True)
        after = updates.Update("Current", "5.2.0", "5.2.0", eligible=True)
        with patch.object(updates, "ponytail_update", side_effect=[before, after]), patch.object(updates, "ponytail_config", return_value=True), patch.object(updates.subprocess, "run") as run:
            updates.execute("ponytail")
            self.assertEqual([c.args[0] for c in run.call_args_list], [
                ["codex", "plugin", "marketplace", "upgrade", "ponytail"],
                ["codex", "plugin", "add", "ponytail@ponytail"]])

    def test_unverified_never_runs(self):
        with patch.object(updates, "ponytail_update", return_value=updates.Update()), patch.object(updates.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                updates.execute("ponytail")
            run.assert_not_called()

    def test_plan_dispatches_both_updates(self):
        rows = tuple(Resource(key, key, "AI", True, "Installed", update="Available", can_update=True)
                     for key in ("ponytail", "skill:" + NAME))
        ops = plan("ai", rows, [r.key for r in rows])
        for row, op in zip(rows, ops):
            self.assertEqual(op.verb, "Update")
            self.assertTrue(op.command[1].endswith("/utils/ai-resource-update.sh"))
            self.assertEqual(op.command[-1], row.key)


if __name__ == "__main__":
    unittest.main()
