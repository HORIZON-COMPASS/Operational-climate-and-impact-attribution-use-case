"""Tests for the dependency-free part of the CDS download interface."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "daily-data"
    / "SCRIPTS"
    / "cron"
    / "cron_step_1.py"
)
SPEC = importlib.util.spec_from_file_location("compass_cron_step_1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ExpandMonthsTest(unittest.TestCase):
    def test_range(self):
        self.assertEqual(MODULE.expand_months(["1-12"]), list(range(1, 13)))

    def test_comma_list_and_deduplication(self):
        self.assertEqual(MODULE.expand_months(["1,2", "2", "3"]), [1, 2, 3])

    def test_descending_range_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.expand_months(["12-1"])


if __name__ == "__main__":
    unittest.main()

