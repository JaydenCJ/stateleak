# How stateleak finds the pair

This document explains the algorithm behind `stateleak hunt` — what it can
guarantee, what it costs in suite runs, and where the corner cases are.

## Terminology

Following the research literature on order-dependent (OD) tests:

- **Victim** — a test that passes in the collected order and in isolation,
  but fails when some other test runs before it.
- **Polluter** — a test that leaves shared state behind (module globals,
  environment variables, files, caches, singletons) that makes a victim fail.
- **Brittle / enabler pair** — the inverse: a test that *fails* in isolation
  because it silently depends on state that an earlier test (the enabler)
  sets up. It passes in the collected order by luck of alphabetical sorting.

`stateleak` diagnoses both directions and labels them differently in the
report (`polluter -> victim` vs `victim depends on enabler state`).

## Pipeline

### 1. Baseline

The suite runs once in collected order. Tests that already fail here are
excluded from analysis — they fail regardless of order and belong to a
normal debugging session, not an order investigation.

### 2. Seeded shuffles

Orders are produced by `random.Random(seed).shuffle`, with seeds
`--seed, --seed+1, …` for `--trials` rounds. Seeding makes every order
reproducible from two integers, so a failure found on CI can be replayed
locally with the same seed. Any test that fails in a shuffle but passed the
baseline is a victim candidate.

### 3. Triage

The victim runs alone in a fresh process:

- **Passes alone** → something before it in the shuffled order polluted it.
  The candidate set is every test that preceded it in the failing shuffle.
  Before minimizing, the failing prefix is re-run once; if the failure does
  not reproduce, the test is reported as **flaky**, not order-dependent.
  After minimizing, the minimal repro is re-run once more in a fresh,
  uncached process; a repro that no longer fails (a run-count parity flake,
  e.g. state toggled in a file between runs) is also downgraded to
  **flaky** instead of blaming a bystander.
- **Fails alone** → it needs an enabler. The candidate set is every test
  that preceded it in the *baseline* order, and the oracle is inverted
  (find the minimal set that makes it *pass*).

### 4. Minimization (ddmin)

The candidate set is minimized with the ddmin algorithm (Zeller &
Hildebrandt, *Simplifying and Isolating Failure-Inducing Input*, IEEE TSE
2002), specialized for ordered sequences: every probed subset preserves the
relative order of the failing shuffle, because pollution is order-sensitive
by definition.

The result is **1-minimal**: removing any single test from the reported
culprit set makes the victim's outcome flip back. For the overwhelmingly
common single-polluter case, that means the report names exactly one
polluter and one victim — a two-test reproduction.

### Cost model

Every probe is a fresh suite subprocess, so probes are the currency:

| Scenario | Runs (n = tests before the victim) |
|---|---|
| Single polluter | O(log n) — ddmin degenerates to binary search |
| k independent polluters (all required) | O(k · log n) typical, O(n²) worst case (Zeller's bound) |
| Victim identification with an exit-code-only runner | + O(log n) prefix bisection |
| Fresh confirmation of the minimal repro | + 1 run per polluter finding |

All runs are memoized by exact order within one invocation, so re-probed
subsets across ddmin granularity levels are free. The report prints both
numbers (`15 runs, 3 cached`).

## Guarantees and limits

- **Deterministic leaks are found and minimized exactly.** If the victim's
  failure is a pure function of which tests ran before it, the reported set
  is 1-minimal and the `verify` command will reproduce it every time.
- **Flaky tests are not blamed on order.** A failing prefix is re-run before
  minimization and the minimal repro must fail a final fresh confirmation
  run; non-reproducing failures are labeled `flaky`.
- **Non-adjacent interactions are handled.** ddmin does not assume the
  polluter is adjacent to the victim, or that there is only one.
- **Cross-process state is out of scope for detection.** stateleak controls
  in-process order; leaks through external services or databases shared
  between runs will look flaky rather than order-dependent.
- **Shuffling is sampling.** A dependency that only triggers under a rare
  permutation may survive `--trials 10`. Raise `--trials`, or feed a known
  failing order (e.g. from a parallelization incident) to `stateleak bisect`.
