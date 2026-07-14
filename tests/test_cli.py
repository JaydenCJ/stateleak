"""The CLI end to end, driven through ``main()`` with a captured stdout.

Runs that need a real suite use the unittest runner against fixture suites
in temp directories — the same subprocess path a user exercises, minus any
network or global state.
"""

from __future__ import annotations

import io
import json

import pytest

from stateleak import __version__
from stateleak.cli import main
from stateleak.shuffle import shuffled_order

from conftest import POLLUTER_ID, VICTIM_ID


def run_cli(*argv):
    out = io.StringIO()
    code = main(list(argv), out=out)
    return code, out.getvalue()


def test_version_flag_prints_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "stateleak %s" % __version__


def test_no_command_prints_help_and_exits_2(capsys):
    code = main([])
    assert code == 2
    assert "hunt" in capsys.readouterr().out


def test_plan_is_deterministic_and_offline():
    code, out = run_cli(
        "plan", "--seed", "42", "--tests", "a", "b", "c", "d", "e"
    )
    assert code == 0
    assert out.splitlines() == shuffled_order(["a", "b", "c", "d", "e"], 42)


def test_hunt_names_the_pair_on_a_leaky_suite(leaky_suite):
    code, out = run_cli(
        "hunt", "--runner", "unittest", "--rootdir", str(leaky_suite), "--trials", "20"
    )
    assert code == 1
    assert "polluter -> victim" in out
    assert VICTIM_ID in out
    assert POLLUTER_ID in out
    assert "minimal repro (2 tests):" in out


def test_hunt_json_output_is_machine_readable(leaky_suite):
    code, out = run_cli(
        "hunt",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        "--trials",
        "20",
        "--json",
    )
    assert code == 1
    data = json.loads(out)
    assert data["clean"] is False
    finding = data["findings"][0]
    assert finding["kind"] == "polluter"
    assert finding["victim"] == VICTIM_ID
    assert finding["culprits"] == [POLLUTER_ID]


def test_hunt_exits_0_on_a_clean_suite(clean_suite):
    code, out = run_cli(
        "hunt", "--runner", "unittest", "--rootdir", str(clean_suite), "--trials", "5"
    )
    assert code == 0
    assert "no order dependencies found" in out


def test_shuffle_scan_reports_failing_seed_without_minimizing(leaky_suite):
    code, out = run_cli(
        "shuffle",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        "--trials",
        "20",
    )
    assert code == 1
    assert "failing)" in out
    assert "FINDING" not in out  # scan only: no minimization sections


def test_verify_distinguishes_failing_and_passing_orders(leaky_suite):
    code, out = run_cli(
        "verify",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        POLLUTER_ID,
        VICTIM_ID,
    )
    assert code == 1
    assert "verify: FAIL" in out and "failed" in out
    code, out = run_cli(
        "verify",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        VICTIM_ID,
        POLLUTER_ID,
    )
    assert code == 0
    assert "verify: PASS" in out


def test_bisect_from_order_file(leaky_suite, tmp_path):
    order_file = tmp_path / "order.txt"
    order_file.write_text(
        "# failing order captured elsewhere\n%s\n%s\n" % (POLLUTER_ID, VICTIM_ID),
        encoding="utf-8",
    )
    code, out = run_cli(
        "bisect",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        "--order-file",
        str(order_file),
    )
    assert code == 1
    assert POLLUTER_ID in out and VICTIM_ID in out


def test_bisect_from_seed_reconstructs_the_order(leaky_suite):
    # Find a seed whose shuffle fails (polluter before victim), then hand
    # only the seed to bisect — the order must be reconstructed identically.
    ids = None
    from stateleak.runner import UnittestRunner

    ids = UnittestRunner(rootdir=str(leaky_suite)).collect()
    seed = next(
        s
        for s in range(1, 100)
        if shuffled_order(ids, s).index(POLLUTER_ID)
        < shuffled_order(ids, s).index(VICTIM_ID)
    )
    code, out = run_cli(
        "bisect",
        "--runner",
        "unittest",
        "--rootdir",
        str(leaky_suite),
        "--seed",
        str(seed),
    )
    assert code == 1
    assert "polluter : %s" % POLLUTER_ID in out


def test_bisect_requires_exactly_one_source(leaky_suite, capsys):
    code = main(
        [
            "bisect",
            "--runner",
            "unittest",
            "--rootdir",
            str(leaky_suite),
            "--order-file",
            "x.txt",
            "--seed",
            "1",
        ]
    )
    assert code == 2
    assert "exactly one" in capsys.readouterr().err


def test_command_runner_requires_cmd_template(capsys):
    code = main(["hunt", "--runner", "command", "--tests", "a", "b"])
    assert code == 2
    assert "--cmd" in capsys.readouterr().err


def test_bad_test_selection_is_a_usage_error(tmp_path, capsys):
    tests_file = tmp_path / "ids.txt"
    tests_file.write_text("a\n", encoding="utf-8")
    code = main(
        ["plan", "--seed", "1", "--tests", "a", "--tests-file", str(tests_file)]
    )
    assert code == 2
    assert "mutually exclusive" in capsys.readouterr().err
    code = main(["plan", "--seed", "1", "--tests-file", "/nonexistent/ids.txt"])
    assert code == 2
    assert "cannot read" in capsys.readouterr().err


def test_tests_file_supports_comments_and_blank_lines(tmp_path):
    tests_file = tmp_path / "ids.txt"
    tests_file.write_text("# comment\n\na\nb\nc\n", encoding="utf-8")
    code, out = run_cli("plan", "--seed", "7", "--tests-file", str(tests_file))
    assert code == 0
    assert sorted(out.split()) == ["a", "b", "c"]
