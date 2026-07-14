"""Keep the shipped example (and the README quickstart) honest.

The README shows real captured output from running stateleak against
``examples/demo_suite``. These tests pin that behavior so the docs cannot
silently drift from reality.
"""

from __future__ import annotations

import io
from pathlib import Path

from stateleak.cli import main

DEMO = str(Path(__file__).resolve().parent.parent / "examples" / "demo_suite")

VICTIM = "test_audit.AuditTests.test_warehouse_starts_empty"
POLLUTER = "test_receiving.ReceivingTests.test_receiving_adds_stock"


def run_cli(*argv):
    out = io.StringIO()
    code = main(list(argv), out=out)
    return code, out.getvalue()


def test_demo_suite_baseline_order_passes():
    code, out = run_cli(
        "verify",
        "--runner",
        "unittest",
        "--rootdir",
        DEMO,
        VICTIM,
        POLLUTER,  # victim first: the polite alphabetical order
    )
    assert code == 0, out


def test_demo_suite_hunt_finds_the_documented_pair_with_two_test_repro():
    code, out = run_cli(
        "hunt", "--runner", "unittest", "--rootdir", DEMO, "--trials", "10"
    )
    assert code == 1
    assert "victim   : %s" % VICTIM in out
    assert "polluter : %s" % POLLUTER in out
    assert "minimal repro (2 tests):" in out
