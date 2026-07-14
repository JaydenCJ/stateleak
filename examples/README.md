# Examples

## `demo_suite/` — a realistic leaky suite

Seven tests over a tiny inventory module with a module-level cache:

- `test_receiving.py` mutates the shared `_STOCK` dict and never resets it
  (**the polluter**).
- `test_audit.py` asserts the warehouse starts empty (**the victim**).
- `test_pricing.py` is pure (**innocent bystanders** the minimizer must
  eliminate).

The alphabetical collected order runs the victim before the polluter, so a
plain `pytest` or `python -m unittest discover` run is green — exactly the
kind of latent bug that detonates the day the suite is parallelized or
shuffled.

Hunt it down from the repository root (no install needed):

```bash
PYTHONPATH=src python3 -m stateleak hunt \
  --runner unittest --rootdir examples/demo_suite --trials 10
```

Expected: exit code 1 and a finding that names
`test_receiving.ReceivingTests.test_receiving_adds_stock` as the polluter of
`test_audit.AuditTests.test_warehouse_starts_empty`, with a two-test repro.

The same suite works with the pytest runner:

```bash
PYTHONPATH=src python3 -m stateleak hunt \
  --rootdir examples/demo_suite --trials 10
```

Fix the leak (add `self.addCleanup(inventory.reset)` in
`ReceivingTests.test_receiving_adds_stock`), re-run the hunt, and the report
flips to `no order dependencies found` with exit code 0.

These example tests are excluded from the package's own pytest run
(`testpaths = ["tests"]`) because failing in a shuffled order is their job.
