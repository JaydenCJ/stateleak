"""Seeded shuffling must be deterministic, non-mutating, and shareable."""

from __future__ import annotations

from stateleak.shuffle import iter_trials, shuffled_order, trial_seeds

IDS = ["t%02d" % i for i in range(10)]


def test_same_seed_same_order_and_result_is_a_permutation():
    assert shuffled_order(IDS, 7) == shuffled_order(IDS, 7)
    assert sorted(shuffled_order(IDS, 7)) == sorted(IDS)


def test_different_seeds_give_different_orders():
    # Ten elements have 3.6M permutations; two seeds colliding would point
    # at a broken RNG wiring, not bad luck.
    assert shuffled_order(IDS, 1) != shuffled_order(IDS, 2)


def test_input_list_is_not_mutated():
    original = list(IDS)
    shuffled_order(IDS, 5)
    assert IDS == original


def test_known_seed_pins_exact_order():
    # Regression pin: random.Random(42).shuffle is stable across supported
    # CPython versions, which is what makes seeds shareable in bug reports.
    assert shuffled_order(["a", "b", "c", "d", "e"], 42) == ["d", "b", "c", "e", "a"]


def test_trial_seeds_are_consecutive_and_empty_for_nonpositive_counts():
    assert trial_seeds(10, 4) == [10, 11, 12, 13]
    assert trial_seeds(1, 0) == []
    assert trial_seeds(1, -3) == []


def test_iter_trials_matches_shuffled_order_per_seed_and_count():
    trials = list(iter_trials(IDS, 4, 3))
    assert len(trials) == 3
    for seed, order in trials:
        assert order == shuffled_order(IDS, seed)
