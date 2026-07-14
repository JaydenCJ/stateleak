"""The hunt pipeline against the in-process fake runner.

Every scenario here models a real-world suite shape: a lone polluter, a
brittle test relying on an enabler, a flaky test, an already-failing
baseline, and a runner that only reports exit codes.
"""

from __future__ import annotations

import pytest

from stateleak.errors import SuiteError
from stateleak.hunt import (
    KIND_ENABLER,
    KIND_FAILS_ALONE,
    KIND_FLAKY,
    KIND_POLLUTER,
    bisect_order,
    hunt,
)
from stateleak.runner import CachingRunner, RunResult

from conftest import FakeRunner, Spec


def polluted_suite(size=8, polluter="t6", victim="t2"):
    """`size` tests; `polluter` leaks a key that makes `victim` fail.

    The victim precedes the polluter in collected order, so the baseline
    passes and only (some) shuffles expose the dependency — the realistic
    shape of an undiscovered order bug.
    """
    specs = {"t%d" % i: Spec() for i in range(size)}
    specs[polluter] = Spec(sets=("dirty",))
    specs[victim] = Spec(fails_if_set=("dirty",))
    return specs


def find_failing_seed(specs, base=1, trials=50):
    """First seed whose shuffle actually triggers the failure (deterministic)."""
    from stateleak.shuffle import iter_trials

    ids = list(specs)
    for seed, order in iter_trials(ids, base, trials):
        state, failed = set(), False
        for tid in order:
            spec = specs[tid]
            failed = failed or any(k in state for k in spec.fails_if_set)
            state.update(spec.sets)
        if failed:
            return seed
    raise AssertionError("no failing seed in range")


def test_clean_suite_reports_clean():
    runner = FakeRunner({"t%d" % i: Spec() for i in range(6)})
    report = hunt(runner, runner.collect(), trials=5)
    assert report.clean
    assert report.findings == []
    assert all(not t.new_failures for t in report.trials)


def test_polluter_pair_is_named_exactly():
    specs = polluted_suite()
    runner = FakeRunner(specs)
    report = hunt(runner, list(specs), trials=50)
    assert not report.clean
    finding = report.findings[0]
    assert finding.kind == KIND_POLLUTER
    assert finding.victim == "t2"
    assert finding.culprits == ["t6"]
    assert finding.repro_order() == ["t6", "t2"]


class BothKeysVictim(FakeRunner):
    """t0 fails only when BOTH leaked keys are present — ddmin must keep both."""

    def run(self, ids):
        from stateleak.runner import TestOutcome

        self.calls.append(list(ids))
        state, outcomes, any_failed = set(), {}, False
        for tid in ids:
            failed = tid == "t0" and {"a", "b"} <= state
            any_failed = any_failed or failed
            outcomes[tid] = TestOutcome("failed" if failed else "passed")
            state.update(self.specs[tid].sets)
        return RunResult(outcomes, 1 if any_failed else 0, True)


def test_two_polluters_both_required_are_reported_together():
    specs = {"t%d" % i: Spec() for i in range(8)}
    specs["t4"] = Spec(sets=("a",))
    specs["t6"] = Spec(sets=("b",))
    runner = BothKeysVictim(specs)
    report = hunt(runner, list(specs), trials=100)
    finding = report.findings[0]
    assert finding.kind == KIND_POLLUTER
    assert finding.victim == "t0"
    assert set(finding.culprits) == {"t4", "t6"}


def test_enabler_dependency_is_classified_and_minimized():
    # t5 needs "warm" state that only t1 provides; the collected order has
    # t1 first so the baseline passes, but t5 fails alone or when shuffled
    # ahead of t1 — a brittle test, not a polluted one.
    specs = {"t%d" % i: Spec() for i in range(6)}
    specs["t1"] = Spec(sets=("warm",))
    specs["t5"] = Spec(fails_if_unset=("warm",))
    runner = FakeRunner(specs)
    report = hunt(runner, list(specs), trials=50)
    finding = report.findings[0]
    assert finding.kind == KIND_ENABLER
    assert finding.victim == "t5"
    assert finding.culprits == ["t1"]


def test_flaky_failure_is_not_blamed_on_order():
    from stateleak.runner import TestOutcome
    from stateleak.shuffle import shuffled_order

    specs = {"t%d" % i: Spec() for i in range(5)}
    ids = list(specs)
    # Pick a seed whose shuffle differs from the baseline and does not put
    # t3 last, so the re-run of "failing prefix + victim" is a fresh
    # (uncached) run — the situation where flakiness must be detected.
    seed = next(
        s
        for s in range(1, 50)
        if shuffled_order(ids, s) != ids and shuffled_order(ids, s)[-1] != "t3"
    )
    trial_order = shuffled_order(ids, seed)
    inner = FakeRunner(specs)
    flaked = {"done": False}

    class FlakyOnce(FakeRunner):
        def run(self, run_ids):
            result = inner.run(run_ids)
            # Fail t3 exactly once, on the shuffled trial run.
            if not flaked["done"] and list(run_ids) == trial_order:
                flaked["done"] = True
                outcomes = dict(result.outcomes)
                outcomes["t3"] = TestOutcome("failed", "cosmic ray")
                return RunResult(outcomes, 1, True)
            return result

    runner = FlakyOnce(specs)
    report = hunt(runner, ids, base_seed=seed, trials=1)
    assert [f.kind for f in report.findings] == [KIND_FLAKY]
    assert report.findings[0].culprits == []
    # A flaky diagnosis is still a non-clean report: the shuffle DID fail.
    assert not report.clean


def test_run_count_parity_flake_is_not_blamed_on_order():
    # A test that toggles persistent external state (a lock file, say) fails
    # on every second run regardless of order. The prefix re-run reproduces
    # the failure by parity coincidence; only the fresh confirmation run of
    # the minimal repro reveals the flake. No bystander may be framed.
    from stateleak.runner import TestOutcome
    from stateleak.shuffle import shuffled_order

    specs = {"t%d" % i: Spec() for i in range(3)}
    ids = list(specs)
    mark = {"set": False}

    class ToggleRunner(FakeRunner):
        def run(self, run_ids):
            self.calls.append(list(run_ids))
            outcomes, any_failed = {}, False
            for tid in run_ids:
                failed = tid == "t2" and mark["set"]
                if tid == "t2":
                    mark["set"] = not mark["set"]
                any_failed = any_failed or failed
                outcomes[tid] = TestOutcome("failed" if failed else "passed")
            return RunResult(outcomes, 1 if any_failed else 0, True)

    # A seed whose shuffle differs from the baseline and puts exactly one
    # test ahead of t2, so the trace is deterministic.
    seed = next(
        s
        for s in range(1, 100)
        if shuffled_order(ids, s) != ids and shuffled_order(ids, s).index("t2") == 1
    )
    report = hunt(ToggleRunner(specs), ids, base_seed=seed, trials=1)
    assert [f.kind for f in report.findings] == [KIND_FLAKY]
    assert report.findings[0].culprits == []
    assert "confirmation" in report.findings[0].detail


def test_baseline_failures_are_excluded_from_victims():
    specs = {"t%d" % i: Spec() for i in range(5)}
    specs["t2"] = Spec(always_fails=True)
    runner = FakeRunner(specs)
    report = hunt(runner, list(specs), trials=5)
    assert report.baseline_failures == ["t2"]
    assert all(f.victim != "t2" for f in report.findings)


def test_tiny_suite_is_trivially_clean():
    runner = FakeRunner({"only": Spec()})
    report = hunt(runner, ["only"], trials=5)
    assert report.clean and report.runs == 0


def test_hunt_stops_after_first_failing_trial_by_default():
    specs = polluted_suite()
    runner = FakeRunner(specs)
    report = hunt(runner, list(specs), trials=50)
    failing_trials = [t for t in report.trials if t.new_failures]
    assert len(failing_trials) == 1
    assert report.trials[-1] is failing_trials[0]


def test_keep_going_scans_more_trials_than_the_first_failure():
    specs = polluted_suite()
    runner = FakeRunner(specs)
    stop = hunt(runner, list(specs), trials=12)
    cont = hunt(FakeRunner(specs), list(specs), trials=12, keep_going=True)
    assert len(cont.trials) == 12
    assert len(stop.trials) < 12


def test_max_victims_caps_minimization_work():
    # Three independent polluter/victim pairs; only one may be minimized.
    specs = {"t%d" % i: Spec() for i in range(9)}
    specs["t0"] = Spec(fails_if_set=("a",))
    specs["t1"] = Spec(fails_if_set=("b",))
    specs["t2"] = Spec(fails_if_set=("c",))
    specs["t6"] = Spec(sets=("a",))
    specs["t7"] = Spec(sets=("b",))
    specs["t8"] = Spec(sets=("c",))
    runner = FakeRunner(specs)
    report = hunt(runner, list(specs), trials=100, keep_going=True, max_victims=1)
    assert len(report.findings) == 1


def test_exit_code_only_runner_finds_the_pair_via_prefix_bisection():
    specs = polluted_suite()
    runner = FakeRunner(specs, per_test=False)
    report = hunt(runner, list(specs), trials=50)
    finding = report.findings[0]
    assert finding.kind == KIND_POLLUTER
    assert (finding.victim, finding.culprits) == ("t2", ["t6"])


def test_exit_code_only_runner_with_failing_baseline_is_an_error():
    specs = {"a": Spec(always_fails=True), "b": Spec()}
    runner = FakeRunner(specs, per_test=False)
    with pytest.raises(SuiteError, match="baseline"):
        hunt(runner, list(specs), trials=2)


def test_runs_counter_matches_actual_subprocess_equivalents():
    specs = polluted_suite()
    fake = FakeRunner(specs)
    cache = CachingRunner(fake)
    report = hunt(cache, list(specs), trials=50)
    assert report.runs == len(fake.calls)


# --- bisect_order -----------------------------------------------------------


def test_bisect_order_minimizes_a_known_failing_order():
    specs = polluted_suite()
    seed = find_failing_seed(specs)
    from stateleak.shuffle import shuffled_order

    order = shuffled_order(list(specs), seed)
    report = bisect_order(FakeRunner(specs), order)
    finding = report.findings[0]
    assert finding.victim == "t2" and finding.culprits == ["t6"]


def test_bisect_order_with_explicit_victim():
    specs = polluted_suite()
    seed = find_failing_seed(specs)
    from stateleak.shuffle import shuffled_order

    order = shuffled_order(list(specs), seed)
    report = bisect_order(FakeRunner(specs), order, victim="t2")
    assert report.findings[0].culprits == ["t6"]


def test_bisect_order_rejects_victim_not_in_order():
    specs = polluted_suite()
    with pytest.raises(SuiteError, match="not in the provided order"):
        bisect_order(FakeRunner(specs), list(specs), victim="ghost")


def test_bisect_order_on_passing_order_reports_clean():
    specs = {"a": Spec(), "b": Spec()}
    report = bisect_order(FakeRunner(specs), ["a", "b"])
    assert report.clean and report.findings == []


def test_bisect_fails_alone_victim_without_baseline_context():
    specs = {"a": Spec(), "b": Spec(always_fails=True)}
    report = bisect_order(FakeRunner(specs), ["a", "b"])
    assert report.findings[0].kind == KIND_FAILS_ALONE
