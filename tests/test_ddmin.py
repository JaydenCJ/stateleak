"""The delta-debugging core: correctness, minimality, and probe economy.

These tests drive ``ddmin`` with pure oracles — no subprocesses — so they
can afford property-style checks (seeded, deterministic) that would be far
too slow against a real suite.
"""

from __future__ import annotations

import random

import pytest

from stateleak.ddmin import ddmin, minimal_failing_prefix, partition

ITEMS = ["t%02d" % i for i in range(20)]


def counting(oracle):
    """Wrap an oracle to count invocations."""
    calls = {"n": 0}

    def wrapped(subset):
        calls["n"] += 1
        return oracle(subset)

    return wrapped, calls


# --- partition -------------------------------------------------------------


def test_partition_splits_evenly_and_front_loads_extras():
    assert partition([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    assert partition([1, 2, 3, 4, 5], 2) == [[1, 2, 3], [4, 5]]


def test_partition_preserves_order_covers_all_and_drops_empty_chunks():
    chunks = partition(ITEMS, 7)
    assert [x for c in chunks for x in c] == ITEMS
    assert all(partition([1, 2], 5))  # n > len: no empty chunks


def test_partition_rejects_nonpositive_count():
    with pytest.raises(ValueError):
        partition([1], 0)


# --- ddmin -----------------------------------------------------------------


def test_single_culprit_is_isolated():
    oracle = lambda s: "t07" in s
    assert ddmin(ITEMS, oracle) == ["t07"]


def test_culprit_pair_is_isolated_in_original_order():
    oracle = lambda s: "t03" in s and "t15" in s
    assert ddmin(ITEMS, oracle) == ["t03", "t15"]


def test_order_sensitive_oracle_gets_order_preserving_subsets():
    # The failure needs t02 strictly before t10 — every subset ddmin probes
    # must preserve relative order or this collapses to a wrong answer.
    def oracle(subset):
        s = list(subset)
        return "t02" in s and "t10" in s and s.index("t02") < s.index("t10")

    assert ddmin(ITEMS, oracle) == ["t02", "t10"]


def test_irreducible_inputs_are_returned_as_is():
    items = ["a", "b", "c"]
    oracle = lambda s: set(s) == {"a", "b", "c"}
    assert ddmin(items, oracle) == items
    assert ddmin(["only"], lambda s: True) == ["only"]


def test_result_is_one_minimal_for_seeded_random_scenarios():
    # Property check: for several seeded scenarios with a random culprit
    # set, ddmin must return exactly the culprits (1-minimality implies no
    # extras when the oracle is a pure superset test).
    for seed in range(6):
        rng = random.Random(seed)
        items = ["x%02d" % i for i in range(12)]
        culprits = set(rng.sample(items, rng.randint(1, 3)))
        oracle = lambda s: culprits.issubset(set(s))
        result = ddmin(items, oracle)
        assert set(result) == culprits, "seed %d" % seed
        assert result == [i for i in items if i in culprits]  # order kept


def test_probe_count_stays_logarithmic_for_single_culprit():
    # 64 candidates, one culprit: ddmin should need a few dozen probes,
    # not hundreds. This guards against regressions that quietly turn the
    # search quadratic (each probe is a full suite run in production).
    items = ["t%02d" % i for i in range(64)]
    oracle, calls = counting(lambda s: "t40" in s)
    assert ddmin(items, oracle) == ["t40"]
    assert calls["n"] <= 50


# --- minimal_failing_prefix ------------------------------------------------


def test_prefix_bisection_finds_victim_at_middle_and_both_ends():
    assert minimal_failing_prefix(ITEMS, lambda p: "t12" in p)[-1] == "t12"
    assert minimal_failing_prefix(ITEMS, lambda p: "t00" in p) == ["t00"]
    assert minimal_failing_prefix(ITEMS, lambda p: "t19" in p) == ITEMS


def test_prefix_bisection_uses_logarithmic_probes():
    order = ["t%03d" % i for i in range(100)]
    fails, calls = counting(lambda p: "t037" in p)
    assert minimal_failing_prefix(order, fails)[-1] == "t037"
    assert calls["n"] <= 9  # 1 sanity probe + ceil(log2(100))


def test_prefix_bisection_rejects_failing_empty_prefix():
    with pytest.raises(ValueError):
        minimal_failing_prefix(ITEMS, lambda p: True)
