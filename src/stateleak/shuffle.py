"""Seeded, reproducible shuffling of test orders.

The whole point of seeding is that a failing order can be shared in a bug
report and reproduced byte-for-byte on another machine: the same seed and
the same collected test list always produce the same order, on every
platform and Python version stateleak supports (``random.Random.shuffle``
with an integer seed is stable across CPython versions).
"""

from __future__ import annotations

import random
from typing import Iterator, List, Sequence, Tuple


def shuffled_order(ids: Sequence[str], seed: int) -> List[str]:
    """Return a new list with ``ids`` shuffled deterministically by ``seed``.

    The input is never mutated. Equal seeds and equal inputs always yield
    the same permutation.
    """
    rng = random.Random(seed)
    order = list(ids)
    rng.shuffle(order)
    return order


def trial_seeds(base_seed: int, trials: int) -> List[int]:
    """The seeds used for a scan: ``base_seed, base_seed+1, ...``.

    Consecutive integers keep repro instructions short ("seed 7, trial 3"
    pins the exact order) while still exploring distinct permutations.
    """
    if trials < 1:
        return []
    return [base_seed + i for i in range(trials)]


def iter_trials(
    ids: Sequence[str], base_seed: int, trials: int
) -> Iterator[Tuple[int, List[str]]]:
    """Yield ``(seed, order)`` pairs for a scan.

    Orders identical to the collected order are still yielded — the caller
    decides whether running them is useful (for tiny suites a shuffle can
    collide with the original order, and skipping silently would make the
    trial count lie).
    """
    for seed in trial_seeds(base_seed, trials):
        yield seed, shuffled_order(ids, seed)
