"""Delta debugging (ddmin) and prefix bisection over ordered test lists.

This module is pure: it knows nothing about subprocesses or test runners.
The oracle is any callable ``test(subset) -> bool`` that returns ``True``
when the subset is still "interesting" (for stateleak: the victim still
fails after running exactly these tests, in this relative order).

``ddmin`` implements the minimizing delta debugging algorithm of Zeller &
Hildebrandt ("Simplifying and Isolating Failure-Inducing Input", TSE 2002),
specialized for ordered sequences: every candidate subset preserves the
relative order of the original list, because test pollution is order
sensitive by definition. The result is 1-minimal — removing any single
element makes the oracle return ``False`` — which is exactly the guarantee
that lets stateleak print "this is *the* polluter" instead of "somewhere in
these 40 tests".
"""

from __future__ import annotations

from typing import Callable, List, Sequence, TypeVar

T = TypeVar("T")

Oracle = Callable[[Sequence[T]], bool]


def partition(items: Sequence[T], n: int) -> List[List[T]]:
    """Split ``items`` into ``n`` contiguous, order-preserving chunks.

    Chunk sizes differ by at most one, and no chunk is empty as long as
    ``n <= len(items)``. Contiguity matters: a polluter pair that must run
    adjacently should survive into the same chunk as often as possible.
    """
    if n <= 0:
        raise ValueError("partition count must be positive")
    length = len(items)
    n = min(n, length) if length else 1
    base, extra = divmod(length, n)
    chunks: List[List[T]] = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks.append(list(items[start : start + size]))
        start += size
    return [c for c in chunks if c]


def ddmin(items: Sequence[T], test: Oracle) -> List[T]:
    """Return a 1-minimal, order-preserving subset for which ``test`` holds.

    Precondition: ``test(items)`` is ``True``. The caller is expected to
    have verified this (stateleak re-runs the failing prefix before
    minimizing, so a flaky failure never reaches this function).

    The oracle is invoked with lists that preserve the relative order of
    ``items``. Callers should memoize the oracle if invocations are
    expensive — ddmin can probe the same subset more than once across
    granularity changes.
    """
    current = list(items)
    n = 2
    while len(current) >= 2:
        chunks = partition(current, n)
        reduced = False

        # 1. Reduce to subset: some single chunk alone reproduces.
        for chunk in chunks:
            if len(chunk) < len(current) and test(chunk):
                current = chunk
                n = 2
                reduced = True
                break

        # 2. Reduce to complement: removing one chunk keeps it reproducing.
        if not reduced and len(chunks) > 2:
            for i in range(len(chunks)):
                complement = [x for j, c in enumerate(chunks) if j != i for x in c]
                if complement and len(complement) < len(current) and test(complement):
                    current = complement
                    n = max(n - 1, 2)
                    reduced = True
                    break

        # 3. Increase granularity, or stop at single-element chunks.
        if not reduced:
            if n >= len(current):
                break
            n = min(len(current), 2 * n)
    return current


def minimal_failing_prefix(order: Sequence[T], fails: Oracle) -> List[T]:
    """Binary-search the shortest failing prefix of ``order``.

    Used when the runner only reports a whole-run exit code (no per-test
    outcomes): the last element of the minimal failing prefix is the first
    test that fails, i.e. the victim. Correctness relies on monotonicity —
    if a prefix fails, every longer prefix contains it and fails too, which
    holds because tests that run *after* a failure cannot un-fail it.

    Precondition: ``fails(order)`` is ``True``. Raises ``ValueError`` if the
    empty prefix already "fails", which would mean the oracle is broken.
    """
    if fails(list(order[:0])):
        raise ValueError("oracle reports failure for the empty prefix")
    lo, hi = 1, len(order)  # invariant: fails(order[:hi]) is True
    while lo < hi:
        mid = (lo + hi) // 2
        if fails(list(order[:mid])):
            hi = mid
        else:
            lo = mid + 1
    return list(order[:lo])
