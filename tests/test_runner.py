"""Runners against real fixture suites in temp directories.

The unittest runner is pure stdlib and exercised heavily. The pytest runner
is exercised through the pytest binary that runs this very suite (a dev
dependency, always present here). Everything is offline and hermetic.
"""

from __future__ import annotations

import sys

import pytest

from stateleak.errors import SuiteError, UsageError
from stateleak.runner import (
    CachingRunner,
    CommandRunner,
    PytestRunner,
    UnittestRunner,
)

from conftest import FakeRunner, POLLUTER_ID, Spec, VICTIM_ID, write_leaky_suite

# --- UnittestRunner ---------------------------------------------------------


def test_unittest_collect_finds_all_tests(leaky_suite):
    runner = UnittestRunner(rootdir=str(leaky_suite))
    ids = runner.collect()
    assert len(ids) == 5
    assert VICTIM_ID in ids and POLLUTER_ID in ids


def test_unittest_run_reports_per_test_outcomes(leaky_suite):
    runner = UnittestRunner(rootdir=str(leaky_suite))
    result = runner.run([POLLUTER_ID, VICTIM_ID])
    assert result.per_test
    assert result.status_of(POLLUTER_ID) == "passed"
    assert result.status_of(VICTIM_ID) == "failed"
    assert result.exit_code == 1


def test_unittest_run_order_flips_the_outcome(leaky_suite):
    runner = UnittestRunner(rootdir=str(leaky_suite))
    result = runner.run([VICTIM_ID, POLLUTER_ID])
    assert result.status_of(VICTIM_ID) == "passed"
    assert not result.any_failure()


def test_unittest_collect_raises_on_unimportable_module(leaky_suite):
    (leaky_suite / "test_broken.py").write_text("import nope_missing\n")
    runner = UnittestRunner(rootdir=str(leaky_suite))
    with pytest.raises(SuiteError, match="test_broken"):
        runner.collect()


def test_unittest_custom_pattern_narrows_discovery(leaky_suite):
    runner = UnittestRunner(rootdir=str(leaky_suite), pattern="test_a*.py")
    ids = runner.collect()
    assert ids and all(i.startswith("test_a_victim.") for i in ids)


# --- PytestRunner -----------------------------------------------------------


def test_pytest_collect_returns_node_ids(leaky_suite):
    runner = PytestRunner(rootdir=str(leaky_suite))
    ids = runner.collect()
    assert "test_a_victim.py::VictimTests::test_state_is_clean" in ids
    assert len(ids) == 5


def test_pytest_run_matches_outcomes_to_node_ids(leaky_suite):
    runner = PytestRunner(rootdir=str(leaky_suite))
    polluter = "test_z_polluter.py::PolluterTests::test_marks_state"
    victim = "test_a_victim.py::VictimTests::test_state_is_clean"
    result = runner.run([polluter, victim])
    assert result.per_test
    assert result.status_of(polluter) == "passed"
    assert result.status_of(victim) == "failed"


def test_pytest_infra_failure_raises_suite_error(leaky_suite):
    runner = PytestRunner(rootdir=str(leaky_suite))
    with pytest.raises(SuiteError):
        runner.run(["definitely/not_here.py::test_missing"])


# --- CommandRunner ----------------------------------------------------------


def test_command_template_requires_tests_placeholder(tmp_path):
    with pytest.raises(UsageError, match="tests"):
        CommandRunner("python -m pytest", rootdir=str(tmp_path))


def test_command_exit_code_mode_reports_no_per_test_data(leaky_suite):
    # `python -m unittest <ids>` is the plainest possible custom command:
    # no JUnit report, so only the exit code is observable.
    template = "%s -m unittest {tests}" % sys.executable
    runner = CommandRunner(template, rootdir=str(leaky_suite))
    failing = runner.run([POLLUTER_ID, VICTIM_ID])
    assert not failing.per_test and failing.any_failure()
    passing = runner.run([VICTIM_ID, POLLUTER_ID])
    assert not passing.any_failure()


def test_command_junit_mode_recovers_per_test_outcomes(leaky_suite):
    template = (
        "%s -m pytest -q --tb=no -o addopts= --junit-xml {junit} {tests}"
        % sys.executable
    )
    runner = CommandRunner(template, rootdir=str(leaky_suite))
    polluter = "test_z_polluter.py::PolluterTests::test_marks_state"
    victim = "test_a_victim.py::VictimTests::test_state_is_clean"
    result = runner.run([polluter, victim])
    assert result.per_test
    assert result.status_of(victim) == "failed"


def test_command_runner_cannot_collect(tmp_path):
    runner = CommandRunner("run {tests}", rootdir=str(tmp_path))
    with pytest.raises(UsageError, match="--tests"):
        runner.collect()


# --- CachingRunner ----------------------------------------------------------


def test_caching_runner_memoizes_by_exact_order():
    fake = FakeRunner({"a": Spec(), "b": Spec()})
    cache = CachingRunner(fake)
    first = cache.run(["a", "b"])
    second = cache.run(["a", "b"])
    assert first is second
    assert cache.runs == 1 and cache.hits == 1
    # A different order is a different run — order is the whole point.
    cache.run(["b", "a"])
    assert len(fake.calls) == 2 and cache.hits == 1
