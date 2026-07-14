"""The standalone unittest harness, exercised exactly as runners use it:
copied into a scratch directory and executed as a plain script by a fresh
interpreter, with the suite root on PYTHONPATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from stateleak import _harness

from conftest import POLLUTER_ID, VICTIM_ID, write_leaky_suite


def run_harness(args, cwd: Path):
    harness_copy = cwd / "_stateleak_harness.py"
    shutil.copyfile(_harness.__file__, harness_copy)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(harness_copy)] + [str(a) for a in args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def harness_run(root: Path, ids):
    ids_path = root / "ids.json"
    out_path = root / "out.json"
    ids_path.write_text(json.dumps(list(ids)), encoding="utf-8")
    proc = run_harness(["run", ids_path, out_path], root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_run_records_pass_fail_statuses_with_messages(tmp_path):
    root = write_leaky_suite(tmp_path)
    data = harness_run(root, [POLLUTER_ID, VICTIM_ID])
    assert data["outcomes"][POLLUTER_ID]["status"] == "passed"
    assert data["outcomes"][VICTIM_ID]["status"] == "failed"
    assert "AssertionError" in data["outcomes"][VICTIM_ID]["message"]
    assert data["failed"] == 1


def test_run_respects_the_given_order(tmp_path):
    # Same two tests, opposite order: victim first means no pollution yet.
    root = write_leaky_suite(tmp_path)
    data = harness_run(root, [VICTIM_ID, POLLUTER_ID])
    assert data["outcomes"][VICTIM_ID]["status"] == "passed"
    assert data["failed"] == 0


def test_run_records_skip_and_expected_failure(tmp_path):
    (tmp_path / "test_statuses.py").write_text(
        "import unittest\n"
        "class T(unittest.TestCase):\n"
        "    @unittest.skip('later')\n"
        "    def test_skipped(self): pass\n"
        "    @unittest.expectedFailure\n"
        "    def test_xfail(self): self.fail('known')\n",
        encoding="utf-8",
    )
    data = harness_run(tmp_path, ["test_statuses.T.test_skipped", "test_statuses.T.test_xfail"])
    assert data["outcomes"]["test_statuses.T.test_skipped"]["status"] == "skipped"
    assert data["outcomes"]["test_statuses.T.test_xfail"]["status"] == "passed"
    assert data["failed"] == 0


def test_run_reports_unloadable_id_as_error(tmp_path):
    root = write_leaky_suite(tmp_path)
    data = harness_run(root, ["no_such_module.Nope.test_x"])
    outcome = data["outcomes"]["no_such_module.Nope.test_x"]
    assert outcome["status"] == "error"
    assert data["failed"] == 1


def test_discover_lists_ids_in_stable_alphabetical_order(tmp_path):
    root = write_leaky_suite(tmp_path)
    out_path = root / "discover.json"
    proc = run_harness(["discover", ".", "test*.py", out_path], root)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["errors"] == []
    assert data["ids"][0].startswith("test_a_victim.")
    assert data["ids"][-1].startswith("test_z_polluter.")
    assert len(data["ids"]) == 5


def test_discover_surfaces_unimportable_modules(tmp_path):
    root = write_leaky_suite(tmp_path)
    (root / "test_broken.py").write_text("import does_not_exist\n", encoding="utf-8")
    out_path = root / "discover.json"
    proc = run_harness(["discover", ".", "test*.py", out_path], root)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "test_broken" in data["errors"]


def test_bad_arguments_exit_nonzero(tmp_path):
    proc = run_harness(["frobnicate"], tmp_path)
    assert proc.returncode == _harness.HARNESS_ERROR_EXIT
    assert "usage" in proc.stderr
