"""Orchestration: baseline, seeded trials, victim triage, minimization.

The pipeline is:

1. **Baseline** — run the suite once in collected order. Tests that already
   fail here are reported but excluded from the order-dependency analysis
   (they fail regardless of order).
2. **Trials** — run seeded shuffles. A test that fails in a shuffle but
   passed the baseline is a *victim candidate*.
3. **Triage** — run the victim alone. Passes alone → some earlier test
   polluted it. Fails alone → it silently depended on state a predecessor
   set up (an *enabler*, aka a "brittle" test).
4. **Minimize** — delta-debug the predecessors down to the 1-minimal set
   that flips the victim. Usually a single test: the polluter.

All suite executions flow through a ``CachingRunner`` so ddmin re-probes
are free and the final report can state exactly how many real runs the
investigation cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .ddmin import ddmin, minimal_failing_prefix
from .errors import SuiteError
from .runner import CachingRunner, RunResult, Runner
from .shuffle import iter_trials

KIND_POLLUTER = "polluter"
KIND_ENABLER = "enabler"
KIND_FLAKY = "flaky"
KIND_FAILS_ALONE = "fails-alone"


@dataclass
class Finding:
    """One diagnosed order dependency (or a triage dead end)."""

    kind: str  # polluter | enabler | flaky | fails-alone
    victim: str
    culprits: List[str]
    seed: Optional[int]
    detail: str

    @property
    def is_order_dependency(self) -> bool:
        return self.kind in (KIND_POLLUTER, KIND_ENABLER)

    def repro_order(self) -> List[str]:
        return list(self.culprits) + [self.victim]


@dataclass
class TrialRecord:
    seed: int
    order: List[str]
    new_failures: List[str]
    identical_order: bool


@dataclass
class HuntReport:
    runner_desc: str
    suite: List[str]
    baseline_failures: List[str]
    trials: List[TrialRecord] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    runs: int = 0
    cache_hits: int = 0

    @property
    def clean(self) -> bool:
        return not any(f.is_order_dependency for f in self.findings) and not any(
            t.new_failures for t in self.trials
        )


def _victim_fails_after(cache: CachingRunner, victim: str, prefix: Sequence[str]) -> bool:
    """Does ``victim`` fail when run immediately after ``prefix``?"""
    result = cache.run(list(prefix) + [victim])
    if result.per_test:
        return result.failed(victim)
    return result.exit_code != 0


def _trial_victims(
    cache: CachingRunner,
    order: Sequence[str],
    result: RunResult,
    baseline_passing: frozenset,
) -> List[str]:
    """Tests that failed in this trial but passed the baseline, in order."""
    if result.per_test:
        return [t for t in order if result.failed(t) and t in baseline_passing]
    if not result.any_failure():
        return []
    # Exit-code-only runner: locate the first failing test by bisecting the
    # shortest failing prefix; its last element is the victim.
    prefix = minimal_failing_prefix(
        list(order), lambda p: cache.run(list(p)).any_failure() if p else False
    )
    victim = prefix[-1]
    return [victim] if victim in baseline_passing else []


def minimize_victim(
    cache: CachingRunner,
    order: Sequence[str],
    victim: str,
    seed: Optional[int],
    baseline_order: Optional[Sequence[str]] = None,
) -> Finding:
    """Triage one victim and minimize its culprit set with ddmin."""
    fails_alone = _victim_fails_after(cache, victim, [])

    if not fails_alone:
        prefix = list(order)[: list(order).index(victim)]
        if not _victim_fails_after(cache, victim, prefix):
            return Finding(
                kind=KIND_FLAKY,
                victim=victim,
                culprits=[],
                seed=seed,
                detail=(
                    "failure did not reproduce when the failing prefix was "
                    "re-run; the test is flaky rather than order-dependent"
                ),
            )
        culprits = ddmin(prefix, lambda s: _victim_fails_after(cache, victim, s))
        # Before blaming, re-run the minimal repro fresh (bypassing the
        # cache): a test whose outcome flips with run count — parity flakes,
        # state toggled outside the process — must not frame a bystander.
        confirm = cache.run_fresh(list(culprits) + [victim])
        reproduced = (
            confirm.failed(victim) if confirm.per_test else confirm.any_failure()
        )
        if not reproduced:
            return Finding(
                kind=KIND_FLAKY,
                victim=victim,
                culprits=[],
                seed=seed,
                detail=(
                    "the minimal repro did not fail on a fresh confirmation "
                    "run; the test is flaky rather than order-dependent"
                ),
            )
        return Finding(
            kind=KIND_POLLUTER,
            victim=victim,
            culprits=culprits,
            seed=seed,
            detail=(
                "victim passes alone but fails after the polluter set; "
                "the set is 1-minimal (removing any test makes the victim pass)"
            ),
        )

    if baseline_order is not None and victim in baseline_order:
        # Fails alone yet passed the baseline: it relied on a predecessor
        # setting state up. Minimize the enabling set from the baseline.
        predecessors = list(baseline_order)[: list(baseline_order).index(victim)]
        if predecessors and not _victim_fails_after(cache, victim, predecessors):
            enablers = ddmin(
                predecessors,
                lambda s: not _victim_fails_after(cache, victim, s),
            )
            return Finding(
                kind=KIND_ENABLER,
                victim=victim,
                culprits=enablers,
                seed=seed,
                detail=(
                    "victim fails in isolation and only passes after the "
                    "enabler set ran first; it depends on leaked state"
                ),
            )

    return Finding(
        kind=KIND_FAILS_ALONE,
        victim=victim,
        culprits=[],
        seed=seed,
        detail="test fails when run alone; not an order dependency",
    )


def hunt(
    runner: Runner,
    ids: Sequence[str],
    base_seed: int = 1,
    trials: int = 10,
    max_victims: int = 3,
    keep_going: bool = False,
    minimize: bool = True,
) -> HuntReport:
    """Run the full pipeline. ``minimize=False`` gives a shuffle-only scan."""
    cache = runner if isinstance(runner, CachingRunner) else CachingRunner(runner)
    ids = list(ids)
    report = HuntReport(
        runner_desc=cache.describe(), suite=ids, baseline_failures=[]
    )
    if len(ids) < 2:
        report.runs = cache.runs
        return report

    baseline = cache.run(ids)
    if baseline.per_test:
        report.baseline_failures = [t for t in ids if baseline.failed(t)]
        baseline_passing = frozenset(t for t in ids if not baseline.failed(t))
    else:
        if baseline.any_failure():
            raise SuiteError(
                "the baseline order already fails and the runner reports no "
                "per-test outcomes; fix the suite or use a runner with "
                "per-test results (pytest/unittest or --cmd with {junit})"
            )
        baseline_passing = frozenset(ids)

    minimized = 0
    seen_victims: set = set()
    for seed, order in iter_trials(ids, base_seed, trials):
        identical = order == ids
        result = baseline if identical else cache.run(order)
        victims = (
            [] if identical else _trial_victims(cache, order, result, baseline_passing)
        )
        report.trials.append(
            TrialRecord(
                seed=seed,
                order=order,
                new_failures=victims,
                identical_order=identical,
            )
        )
        if victims and minimize:
            for victim in victims:
                if victim in seen_victims:
                    continue  # a later seed re-finding the same victim adds nothing
                if minimized >= max_victims:
                    break
                seen_victims.add(victim)
                report.findings.append(
                    minimize_victim(cache, order, victim, seed, baseline_order=ids)
                )
                minimized += 1
            if not keep_going:
                break
    report.runs = cache.runs
    report.cache_hits = cache.hits
    return report


def bisect_order(
    runner: Runner,
    order: Sequence[str],
    victim: Optional[str] = None,
    baseline_order: Optional[Sequence[str]] = None,
) -> HuntReport:
    """Minimize a known-failing order (e.g. one found by another tool)."""
    cache = runner if isinstance(runner, CachingRunner) else CachingRunner(runner)
    order = list(order)
    report = HuntReport(
        runner_desc=cache.describe(), suite=order, baseline_failures=[]
    )
    if victim is None:
        result = cache.run(order)
        if result.per_test:
            failed = [t for t in order if result.failed(t)]
            if not failed:
                report.runs = cache.runs
                return report
            victim = failed[0]
        else:
            if not result.any_failure():
                report.runs = cache.runs
                return report
            victim = minimal_failing_prefix(
                order, lambda p: cache.run(list(p)).any_failure() if p else False
            )[-1]
    elif victim not in order:
        raise SuiteError("victim %r is not in the provided order" % (victim,))
    report.findings.append(
        minimize_victim(cache, order, victim, None, baseline_order=baseline_order)
    )
    report.runs = cache.runs
    report.cache_hits = cache.hits
    return report
