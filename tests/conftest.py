"""Shared fixtures: on-disk fixture suites and an in-process fake runner.

Two kinds of test doubles are used across the suite:

* ``FakeRunner`` simulates a stateful test suite entirely in-process. Each
  simulated run starts from empty state, mirroring how real runners spawn a
  fresh interpreter. This keeps the algorithm tests (hunt, ddmin
  integration) fast and fully deterministic.
* ``write_leaky_suite`` / ``write_clean_suite`` create real unittest suites
  in a temp directory for the subprocess-level tests (harness, runners,
  CLI). The leak is a module-level dict — the canonical real-world polluter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pytest

from stateleak.runner import Runner, RunResult, TestOutcome


@dataclass(frozen=True)
class Spec:
    """Behavior of one simulated test.

    ``sets`` are state keys the test leaks into the process. The test fails
    when any ``fails_if_set`` key is present (a pollution victim) or any
    ``fails_if_unset`` key is missing (a brittle test needing an enabler).
    """

    sets: Tuple[str, ...] = ()
    fails_if_set: Tuple[str, ...] = ()
    fails_if_unset: Tuple[str, ...] = ()
    always_fails: bool = False


@dataclass
class FakeRunner(Runner):
    """Deterministic in-process runner driven by ``Spec`` objects."""

    specs: Dict[str, Spec]
    per_test: bool = True
    calls: List[List[str]] = field(default_factory=list)

    name = "fake"

    def run(self, ids: Sequence[str]) -> RunResult:
        self.calls.append(list(ids))
        state: set = set()
        outcomes: Dict[str, TestOutcome] = {}
        any_failed = False
        for test_id in ids:
            spec = self.specs[test_id]
            failed = (
                spec.always_fails
                or any(k in state for k in spec.fails_if_set)
                or any(k not in state for k in spec.fails_if_unset)
            )
            any_failed = any_failed or failed
            outcomes[test_id] = TestOutcome("failed" if failed else "passed")
            state.update(spec.sets)
        exit_code = 1 if any_failed else 0
        if self.per_test:
            return RunResult(outcomes=outcomes, exit_code=exit_code, per_test=True)
        return RunResult(outcomes={}, exit_code=exit_code, per_test=False)

    def collect(self) -> List[str]:
        return list(self.specs)

    def describe(self) -> str:
        return "fake (%d tests)" % len(self.specs)


_SHARED_PY = '''\
"""Module-level shared state: the leak under test."""
STATE = {}
'''

_VICTIM_PY = '''\
import unittest

import shared


class VictimTests(unittest.TestCase):
    def test_state_is_clean(self):
        self.assertEqual(shared.STATE, {})

    def test_two_plus_two(self):
        self.assertEqual(2 + 2, 4)
'''

_NEUTRAL_PY = '''\
import unittest


class NeutralTests(unittest.TestCase):
    def test_upper(self):
        self.assertEqual("ok".upper(), "OK")

    def test_join(self):
        self.assertEqual("-".join(["a", "b"]), "a-b")
'''

_POLLUTER_PY = '''\
import unittest

import shared


class PolluterTests(unittest.TestCase):
    def test_marks_state(self):
        shared.STATE["dirty"] = True  # leaks: never cleaned up
        self.assertTrue(shared.STATE["dirty"])
'''

VICTIM_ID = "test_a_victim.VictimTests.test_state_is_clean"
POLLUTER_ID = "test_z_polluter.PolluterTests.test_marks_state"


def write_leaky_suite(root: Path) -> Path:
    """A 5-test unittest suite whose baseline (alphabetical) order passes.

    The victim sorts before the polluter, so only shuffled orders fail —
    exactly the situation stateleak exists for.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "shared.py").write_text(_SHARED_PY, encoding="utf-8")
    (root / "test_a_victim.py").write_text(_VICTIM_PY, encoding="utf-8")
    (root / "test_m_neutral.py").write_text(_NEUTRAL_PY, encoding="utf-8")
    (root / "test_z_polluter.py").write_text(_POLLUTER_PY, encoding="utf-8")
    return root


def write_clean_suite(root: Path) -> Path:
    """A 2-file suite with no shared state at all."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "test_m_neutral.py").write_text(_NEUTRAL_PY, encoding="utf-8")
    (root / "test_more.py").write_text(
        _NEUTRAL_PY.replace("NeutralTests", "MoreTests"), encoding="utf-8"
    )
    return root


@pytest.fixture
def leaky_suite(tmp_path: Path) -> Path:
    return write_leaky_suite(tmp_path / "suite")


@pytest.fixture
def clean_suite(tmp_path: Path) -> Path:
    return write_clean_suite(tmp_path / "suite")
