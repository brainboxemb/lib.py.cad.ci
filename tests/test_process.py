"""Tests for the library-owned external-process boundary."""

from __future__ import annotations

import sys
import unittest

from cad_ci.execution.process import ProcessExecutionError, SubprocessRunner


class ProcessRunnerTests(unittest.TestCase):
    """Prove the adapter contract without involving CAD runtimes or Docker."""

    def test_success_returns_owned_result_shape(self):
        """Owner logic receives only the stable return-code result it needs."""

        result = SubprocessRunner().run(
            [sys.executable, "-c", "raise SystemExit(0)"],
            check=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_checked_failure_is_translated_at_boundary(self):
        """subprocess-specific checked failures do not leak into owner modules."""

        with self.assertRaisesRegex(ProcessExecutionError, "external process failed"):
            SubprocessRunner().run(
                [sys.executable, "-c", "raise SystemExit(7)"],
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
