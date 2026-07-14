# Contributing to stateleak

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Getting started

You need Python ≥ 3.9. pytest is the only development dependency.

```bash
git clone https://github.com/JaydenCJ/stateleak
cd stateleak
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
bash scripts/smoke.sh
```

`scripts/smoke.sh` drives the real CLI end to end against the shipped demo
suite — hunt, JSON report, verify, bisect, and the clean path — and must
print `SMOKE OK`.

## Before you open a pull request

1. Format with `python -m black src tests` if you have it; match the
   existing style either way (formatting consistency is enforced in review).
2. Lint with `python -m ruff check src tests` if you have it; the code must
   stay warning-free.
3. `pytest` — all tests must pass, offline, with no new flakiness.
4. `bash scripts/smoke.sh` — must print `SMOKE OK`.
5. Add tests for behavior changes; keep logic in pure, unit-testable
   modules (`ddmin.py`, `shuffle.py`, and `junitxml.py` are subprocess-free
   on purpose).

## Ground rules

- **No new runtime dependencies.** The package is standard-library only;
  that is a feature, not an accident. Test-only tools belong in the `dev`
  extra and need justification in the PR.
- **No network calls, ever.** stateleak only spawns local subprocesses for
  the suite under test; nothing may phone home.
- **Determinism is the product.** Same seed + same test list = same order,
  on every platform. Anything that threatens that (unseeded randomness,
  wall-clock dependence, dict-order assumptions) will be rejected.
- Code comments and doc comments are written in English.
- Keep the three READMEs aligned: `README.md`, `README.zh.md`, and
  `README.ja.md` are line-for-line translations; update all three when you
  change one (English is authoritative).

## Reporting bugs

Please include `stateleak --version`, the exact command line, the report
output (text or `--json`), and — if you can — the failing seed and the
`stateleak verify` line from the finding, which is a complete reproduction
recipe on its own.

## Security

Please do not report security issues in public GitHub issues. Use GitHub's
private vulnerability reporting on this repository instead.
