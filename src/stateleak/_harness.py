"""Standalone unittest harness executed in the target suite's interpreter.

This file is copied into a temporary directory and run as a plain script
(``python _harness.py run ids.json out.json``) inside the suite's root
directory. It must therefore stay dependency-free and must not import
anything from the ``stateleak`` package: the target interpreter may be a
different virtualenv that has never heard of stateleak.

Commands
--------
``run <ids.json> <out.json>``
    Load the test ids from ``ids.json`` (a JSON list), run them in exactly
    that order inside one process, and write per-test outcomes to
    ``out.json``. Exit code 0 means the harness itself completed; test
    failures are data, not harness errors.

``discover <start_dir> <pattern> <out.json>``
    Discover tests with ``unittest.TestLoader.discover`` and write the
    ordered list of test ids to ``out.json``.
"""

from __future__ import annotations

import json
import sys
import traceback
import unittest

HARNESS_ERROR_EXIT = 3


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for test in _iter_tests(item):
                yield test
        else:
            yield item


def _first_line(err):
    exc_type, exc_value, _tb = err
    text = traceback.format_exception_only(exc_type, exc_value)
    return text[-1].strip() if text else exc_type.__name__


class _CollectingResult(unittest.TestResult):
    """Record a status string per test id, in execution order."""

    def __init__(self):
        super().__init__()
        self.outcomes = {}

    def _record(self, test, status, message=""):
        self.outcomes[test.id()] = {"status": status, "message": message}

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", _first_line(err))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", _first_line(err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "passed", "expected failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failed", "unexpected success")


def cmd_run(ids_path, out_path):
    with open(ids_path, "r", encoding="utf-8") as fh:
        ids = json.load(fh)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    load_errors = {}
    for test_id in ids:
        try:
            loaded = list(_iter_tests(loader.loadTestsFromName(test_id)))
        except Exception as exc:  # older Pythons raise on a bad name
            load_errors[test_id] = {
                "status": "error",
                "message": "load error: %s" % (exc,),
            }
            continue
        # Modern unittest wraps unloadable names in _FailedTest instead of
        # raising; keep the *requested* id as the outcome key so callers can
        # always look results up by what they asked for.
        if any(t.id().startswith("unittest.loader._FailedTest") for t in loaded):
            load_errors[test_id] = {
                "status": "error",
                "message": "load error: could not load %r" % (test_id,),
            }
        else:
            suite.addTests(loaded)
    result = _CollectingResult()
    suite.run(result)
    outcomes = dict(result.outcomes)
    outcomes.update(load_errors)
    failed = sum(1 for o in outcomes.values() if o["status"] in ("failed", "error"))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"outcomes": outcomes, "failed": failed}, fh, sort_keys=True)
    return 0


def cmd_discover(start_dir, pattern, out_path):
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir, pattern=pattern)
    ids = []
    errors = []
    for test in _iter_tests(suite):
        test_id = test.id()
        # unittest represents unimportable modules as _FailedTest instances
        # whose id starts with the loader module path; surface them loudly
        # instead of silently dropping tests from the scan.
        if test_id.startswith("unittest.loader._FailedTest"):
            errors.append(test_id.rsplit(".", 1)[-1])
        else:
            ids.append(test_id)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"ids": ids, "errors": errors}, fh, sort_keys=True)
    return 0


def main(argv):
    if len(argv) >= 4 and argv[1] == "run":
        return cmd_run(argv[2], argv[3])
    if len(argv) >= 5 and argv[1] == "discover":
        return cmd_discover(argv[2], argv[3], argv[4])
    sys.stderr.write("usage: _harness.py run IDS OUT | discover DIR PATTERN OUT\n")
    return HARNESS_ERROR_EXIT


if __name__ == "__main__":
    sys.exit(main(sys.argv))
