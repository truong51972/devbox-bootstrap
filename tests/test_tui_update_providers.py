"""Provider-specific regression coverage for resource update diagnostics."""
import unittest
from unittest.mock import patch
from pathlib import Path

from tui.toolkit import resources as r
from tui.toolkit import binary_adoption as adoption
from tui.app import DevboxTUI


class UpdateProviderTests(unittest.TestCase):
    def test_manual_updates_excluded_from_bulk_selection(self):
        row = r.Resource("minikube", "Minikube", "K8S", True, "Installed", update="Available", can_adopt=True)
        self.assertEqual(row.status, "Manual update")
        self.assertEqual(row.action, "")
        app = DevboxTUI()
        app.resource_rows = (row,)
        app.resource_render_rows()
        app.resource_updates()
        self.assertFalse(app.resource_list.current_values)
        app.resource_adopt()
        self.assertEqual(app.screen, "resource_confirm")
        self.assertEqual(app.resource_operations[0].verb, "Adopt")

    def test_symlink_owner(self):
        def query(*args, **kwargs):
            return "bat: /usr/bin/batcat" if args[-1] == "/usr/bin/batcat" else ""
        with patch.object(r.Path, "resolve", return_value=Path("/usr/bin/batcat")), patch.object(r, "command", side_effect=query):
            self.assertTrue(r.package_owner("/home/user/.local/bin/bat", ("bat",)))

    def test_bat_fd_requires_both_owners(self):
        row = r.Resource("bat-fd", "bat + fd", "TOOLS", True, "Installed", path="/usr/bin/batcat")
        with patch.object(r, "package_owner", side_effect=[True, False]), patch.object(r.shutil, "which", return_value="/external/fd"):
            self.assertIsNone(r.apt_probe(row))

    def test_nvidia_base_package_ownership(self):
        self.assertIn("nvidia-container-toolkit-base", r.APT["nvidia"])

    def test_external_binary_still_has_versions(self):
        row = r.Resource("minikube", "Minikube", "K8S", True, "Installed", path="/external/minikube")
        with patch.object(r, "binary_version", return_value="1.35.0"), patch.object(r, "command", return_value='{"tag_name":"v1.36.0"}'):
            result = r.release_probe(row)
        self.assertEqual((result.installed_version, result.available_version), ("1.35.0", "1.36.0"))
        self.assertEqual(result.status, "Manual update")
        self.assertFalse(result.can_update)

    def test_upstream_failure_preserves_installed_version(self):
        row = r.Resource("minikube", "Minikube", "K8S", True, "Installed", path="/external/minikube")
        with patch.object(r, "binary_version", return_value="1.35.0"), patch.object(r, "command", return_value=""):
            result = r.release_probe(row)
        self.assertEqual(result.status, "Check failed")
        self.assertEqual(result.installed_version, "1.35.0")

    def test_zsh_current_is_not_unknown(self):
        row = r.Resource("zsh", "Zsh", "SHELL", True, "Installed")
        apt = r.Resource("zsh", "Zsh", "SHELL", True, "Installed", update="Current", can_update=True)
        with patch.object(r, "apt_probe", return_value=apt), patch.object(r, "git_checkout", return_value=("Current", "abc", "abc", "repo: current", True)):
            self.assertEqual(r.zsh_probe(row).status, "Installed")

    def test_adoption_rejects_wrong_path_and_version(self):
        self.assertFalse(adoption.eligible("kubectl", "/usr/bin/kubectl"))
        with self.assertRaises(ValueError):
            adoption.adopt("kubectl", "../../bad")


if __name__ == "__main__":
    unittest.main()
