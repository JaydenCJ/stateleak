# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added

- `stateleak hunt`: the full pipeline — baseline run, seeded shuffle trials,
  victim triage, and ddmin minimization down to the exact polluter/victim
  pair, with `--trials`, `--seed`, `--max-victims`, and `--keep-going`.
- Order-preserving delta debugging (`ddmin`) that returns a 1-minimal
  culprit set, plus prefix bisection for runners that only report an exit
  code.
- Triage that distinguishes four diagnoses: `polluter -> victim`, enabler
  dependencies (brittle tests that fail in isolation), flaky failures
  (failing prefix re-run and the minimal repro confirmed fresh before
  blame), and tests that fail alone.
- Three runners: `unittest` (pure stdlib, via a standalone harness copied
  into the target interpreter), `pytest` (JUnit XML round trip, order
  pinned by neutralizing `addopts` and `pytest-randomly`, with
  `--pytest-args` passthrough), and `command` (any `{tests}` template,
  optional `{junit}` for per-test outcomes).
- `stateleak shuffle` (scan without minimization), `stateleak bisect`
  (minimize a known-failing order from `--order-file` or `--seed`),
  `stateleak verify` (run the printed repro), and `stateleak plan`
  (expand a seed to its exact order without running).
- Human report with a copy-pasteable `stateleak verify` reproduction line
  and run-economy accounting, plus a `--json` report for scripted gates.
- Per-order run memoization so ddmin re-probes cost zero suite runs.
- CI-friendly exit codes: 0 clean, 1 order dependencies found, 2 usage or
  infrastructure error.
- Runnable leaky example suite in `examples/demo_suite/`, algorithm notes
  in `docs/algorithm.md`, 91 pytest tests, and `scripts/smoke.sh`.

### Notes

- The repository ships no CI workflow; verification is local —
  `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.

[0.1.0]: https://github.com/JaydenCJ/stateleak/releases/tag/v0.1.0
