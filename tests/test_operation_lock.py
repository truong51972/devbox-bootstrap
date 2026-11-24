import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tui.operation_lock import operation_lock


class OperationLockTests(unittest.TestCase):
    def test_shared_shell_and_python_lock(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}):
            command = ["bash", "-c", 'source "$1"; devbox_acquire_lock', "bash",
                       str(root / "utils/operation-lock.sh")]
            with operation_lock():
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Another Devbox operation", result.stderr)
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            with operation_lock():
                with self.assertRaisesRegex(RuntimeError, "Another Devbox operation"):
                    with operation_lock():
                        self.fail("overlapping operation admitted")

    def test_inherited_shell_lock_and_python_contention(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}):
            command = ["bash", "-c", 'source "$1"; devbox_acquire_lock && bash -c \'source "$1"; devbox_acquire_lock && echo ready; read -r _\' bash "$1"',
                       "bash", str(root / "utils/operation-lock.sh")]
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "ready")
                with self.assertRaisesRegex(RuntimeError, "Another Devbox operation"):
                    with operation_lock():
                        self.fail("overlapping operation admitted")
            finally:
                proc.communicate("\n", timeout=5)
            self.assertEqual(proc.returncode, 0)
