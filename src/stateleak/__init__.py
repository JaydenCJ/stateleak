"""stateleak — find test-order dependencies and name the exact polluter.

Public API:

* :func:`stateleak.hunt.hunt` — full pipeline (baseline, seeded shuffles,
  triage, ddmin minimization), returning a :class:`~stateleak.hunt.HuntReport`.
* :func:`stateleak.hunt.bisect_order` — minimize a known-failing order.
* :func:`stateleak.ddmin.ddmin` — the pure delta-debugging primitive.
* :func:`stateleak.shuffle.shuffled_order` — deterministic seeded shuffle.
* Runners in :mod:`stateleak.runner` — ``UnittestRunner``, ``PytestRunner``,
  ``CommandRunner``, and the memoizing ``CachingRunner``.

Everything is standard library only; the package has zero runtime
dependencies.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .ddmin import ddmin, minimal_failing_prefix
from .errors import RunTimeout, StateleakError, SuiteError, UsageError
from .hunt import Finding, HuntReport, TrialRecord, bisect_order, hunt, minimize_victim
from .runner import (
    CachingRunner,
    CommandRunner,
    PytestRunner,
    Runner,
    RunResult,
    TestOutcome,
    UnittestRunner,
)
from .shuffle import iter_trials, shuffled_order, trial_seeds

__all__ = [
    "__version__",
    "CachingRunner",
    "CommandRunner",
    "Finding",
    "HuntReport",
    "PytestRunner",
    "RunResult",
    "RunTimeout",
    "Runner",
    "StateleakError",
    "SuiteError",
    "TestOutcome",
    "TrialRecord",
    "UnittestRunner",
    "UsageError",
    "bisect_order",
    "ddmin",
    "hunt",
    "iter_trials",
    "minimal_failing_prefix",
    "minimize_victim",
    "shuffled_order",
    "trial_seeds",
]
