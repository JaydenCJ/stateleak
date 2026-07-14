"""Runners: execute an ordered list of tests in a fresh subprocess.

A runner does exactly one thing: given test ids in a specific order, run
them once in a *fresh interpreter* and report which passed. Fresh processes
are non-negotiable — the entire methodology depends on every run starting
from clean state, so that any failure observed is caused by tests *within*
that run, not residue from a previous one.

Three runners ship in 0.1.0:

* ``UnittestRunner`` — pure stdlib. Copies ``_harness.py`` next to a JSON
  id list and runs it with the target interpreter, so the target
  environment never needs stateleak installed.
* ``PytestRunner`` — invokes ``python -m pytest`` with a JUnit XML report
  and maps cases back to node ids. pytest must be installed in the target
  interpreter (it usually is — it runs the suite being diagnosed).
* ``CommandRunner`` — any command template with ``{tests}`` (and optional
  ``{junit}``) placeholders. Without ``{junit}`` only the exit code is
  observed; stateleak then falls back to prefix bisection to attribute
  failures.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import _harness, junitxml
from .errors import RunTimeout, SuiteError, UsageError

PASS_STATUSES = frozenset({"passed", "skipped"})
FAIL_STATUSES = frozenset({"failed", "error"})


@dataclass(frozen=True)
class TestOutcome:
    status: str  # passed | failed | error | skipped | unknown
    message: str = ""


@dataclass
class RunResult:
    """Outcome of one suite invocation."""

    outcomes: Dict[str, TestOutcome]
    exit_code: int
    per_test: bool  # True when `outcomes` covers every requested id

    def status_of(self, test_id: str) -> str:
        outcome = self.outcomes.get(test_id)
        return outcome.status if outcome else "unknown"

    def failed(self, test_id: str) -> bool:
        return self.status_of(test_id) in FAIL_STATUSES

    def any_failure(self) -> bool:
        if self.per_test:
            return any(o.status in FAIL_STATUSES for o in self.outcomes.values())
        return self.exit_code != 0

    def failed_ids(self) -> List[str]:
        return [i for i, o in self.outcomes.items() if o.status in FAIL_STATUSES]


class Runner:
    """Interface every runner implements."""

    name = "abstract"

    def run(self, ids: Sequence[str]) -> RunResult:
        raise NotImplementedError

    def collect(self) -> List[str]:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


def _run_subprocess(
    argv: Sequence[str], cwd: Path, timeout: float, env: Optional[dict] = None
) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunTimeout(
            "suite run exceeded %.0fs timeout: %s" % (timeout, " ".join(argv))
        ) from exc
    except OSError as exc:
        raise SuiteError("could not start runner process: %s" % (exc,)) from exc


class UnittestRunner(Runner):
    """Run unittest test ids through the bundled standalone harness."""

    name = "unittest"

    def __init__(
        self,
        rootdir: str = ".",
        python: Optional[str] = None,
        pattern: str = "test*.py",
        start_dir: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        self.rootdir = Path(rootdir).resolve()
        self.rootdir_display = rootdir
        self.python = python or sys.executable
        self.pattern = pattern
        self.start_dir = start_dir or "."
        self.timeout = timeout

    def _env(self) -> dict:
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        root = str(self.rootdir)
        env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
        return env

    def _harness_call(self, args: Sequence[str], workdir: Path) -> None:
        harness_copy = workdir / "_stateleak_harness.py"
        shutil.copyfile(_harness.__file__, harness_copy)
        proc = _run_subprocess(
            [self.python, str(harness_copy)] + list(args),
            cwd=self.rootdir,
            timeout=self.timeout,
            env=self._env(),
        )
        if proc.returncode != 0:
            raise SuiteError(
                "unittest harness failed (exit %d): %s"
                % (proc.returncode, (proc.stderr or proc.stdout).strip()[:2000])
            )

    def run(self, ids: Sequence[str]) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="stateleak-") as tmp:
            workdir = Path(tmp)
            ids_path = workdir / "ids.json"
            out_path = workdir / "out.json"
            ids_path.write_text(json.dumps(list(ids)), encoding="utf-8")
            self._harness_call(["run", str(ids_path), str(out_path)], workdir)
            data = json.loads(out_path.read_text(encoding="utf-8"))
        outcomes = {
            test_id: TestOutcome(o["status"], o.get("message", ""))
            for test_id, o in data["outcomes"].items()
        }
        exit_code = 1 if data.get("failed", 0) else 0
        return RunResult(outcomes=outcomes, exit_code=exit_code, per_test=True)

    def collect(self) -> List[str]:
        with tempfile.TemporaryDirectory(prefix="stateleak-") as tmp:
            workdir = Path(tmp)
            out_path = workdir / "discover.json"
            self._harness_call(
                ["discover", self.start_dir, self.pattern, str(out_path)], workdir
            )
            data = json.loads(out_path.read_text(encoding="utf-8"))
        if data.get("errors"):
            raise SuiteError(
                "unittest discovery could not import: %s" % ", ".join(data["errors"])
            )
        return list(data["ids"])

    def describe(self) -> str:
        return "unittest (rootdir=%s)" % (self.rootdir_display,)


class PytestRunner(Runner):
    """Run pytest node ids with a JUnit XML report for per-test outcomes."""

    name = "pytest"

    # 2=interrupted, 3=internal error, 4=usage error: infrastructure, not
    # test outcomes. 0/1/5 are normal observations.
    _INFRA_EXIT_CODES = (2, 3, 4)

    def __init__(
        self,
        rootdir: str = ".",
        python: Optional[str] = None,
        extra_args: Optional[Sequence[str]] = None,
        timeout: float = 300.0,
    ) -> None:
        self.rootdir = Path(rootdir).resolve()
        self.rootdir_display = rootdir
        self.python = python or sys.executable
        self.extra_args = list(extra_args or [])
        self.timeout = timeout

    def _base_argv(self) -> List[str]:
        return [
            self.python,
            "-m",
            "pytest",
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
            # Neutralize order-randomizing plugins and any ini `addopts`
            # (e.g. `-n auto` or `-p randomly`): stateleak must own the
            # order, otherwise seeds are not reproducible. Flags a suite
            # genuinely needs can be restored via --pytest-args.
            "-p",
            "no:randomly",
            # Pin pytest's rootdir to the invocation directory so collected
            # node ids resolve when passed back on later runs, even when a
            # config file higher up the tree would move the rootdir.
            "--rootdir",
            ".",
            "-o",
            "addopts=",
            "-o",
            "junit_family=xunit2",
        ] + self.extra_args

    def run(self, ids: Sequence[str]) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="stateleak-") as tmp:
            junit_path = Path(tmp) / "report.xml"
            argv = self._base_argv() + ["--junit-xml", str(junit_path)] + list(ids)
            proc = _run_subprocess(argv, cwd=self.rootdir, timeout=self.timeout)
            if proc.returncode in self._INFRA_EXIT_CODES:
                raise SuiteError(
                    "pytest failed to run (exit %d): %s"
                    % (proc.returncode, (proc.stderr or proc.stdout).strip()[:2000])
                )
            if not junit_path.exists():
                raise SuiteError("pytest produced no JUnit report")
            xml_text = junit_path.read_text(encoding="utf-8")
        try:
            cases = junitxml.parse_junit(xml_text)
        except ValueError as exc:
            raise SuiteError(str(exc)) from exc
        matched = junitxml.match_outcomes(ids, cases)
        outcomes: Dict[str, TestOutcome] = {}
        complete = True
        for test_id in ids:
            case = matched[test_id]
            if case is None:
                complete = False
                outcomes[test_id] = TestOutcome("unknown", "not in JUnit report")
            else:
                outcomes[test_id] = TestOutcome(case.status, case.message)
        return RunResult(
            outcomes=outcomes, exit_code=proc.returncode, per_test=complete
        )

    def collect(self) -> List[str]:
        argv = self._base_argv() + ["--collect-only"]
        proc = _run_subprocess(argv, cwd=self.rootdir, timeout=self.timeout)
        if proc.returncode not in (0, 5):
            raise SuiteError(
                "pytest collection failed (exit %d): %s"
                % (proc.returncode, (proc.stderr or proc.stdout).strip()[:2000])
            )
        ids = [
            line.strip()
            for line in proc.stdout.splitlines()
            if "::" in line and not line.startswith(("=", "<", " ", "warning"))
        ]
        return ids

    def describe(self) -> str:
        return "pytest (rootdir=%s)" % (self.rootdir_display,)


class CommandRunner(Runner):
    """Run an arbitrary shell command template.

    ``{tests}`` expands to the shell-quoted, space-separated ordered ids.
    ``{junit}`` (optional) expands to a temporary path; if present, the
    command is expected to write a JUnit XML report there, which unlocks
    per-test outcomes. Without it, only the exit code is observed and
    stateleak attributes failures by prefix bisection.
    """

    name = "command"

    def __init__(
        self, template: str, rootdir: str = ".", timeout: float = 300.0
    ) -> None:
        if "{tests}" not in template:
            raise UsageError("--cmd template must contain the {tests} placeholder")
        self.template = template
        self.rootdir = Path(rootdir).resolve()
        self.timeout = timeout
        self.uses_junit = "{junit}" in template

    def run(self, ids: Sequence[str]) -> RunResult:
        tests_arg = " ".join(shlex.quote(i) for i in ids)
        with tempfile.TemporaryDirectory(prefix="stateleak-") as tmp:
            junit_path = Path(tmp) / "report.xml"
            command = self.template.replace("{tests}", tests_arg).replace(
                "{junit}", shlex.quote(str(junit_path))
            )
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(self.rootdir),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RunTimeout(
                    "command exceeded %.0fs timeout: %s" % (self.timeout, command)
                ) from exc
            if self.uses_junit and junit_path.exists():
                xml_text = junit_path.read_text(encoding="utf-8")
                try:
                    cases = junitxml.parse_junit(xml_text)
                except ValueError as exc:
                    raise SuiteError(str(exc)) from exc
                matched = junitxml.match_outcomes(ids, cases)
                outcomes = {
                    test_id: (
                        TestOutcome(case.status, case.message)
                        if case
                        else TestOutcome("unknown", "not in JUnit report")
                    )
                    for test_id, case in matched.items()
                }
                complete = all(o.status != "unknown" for o in outcomes.values())
                return RunResult(
                    outcomes=outcomes, exit_code=proc.returncode, per_test=complete
                )
        return RunResult(outcomes={}, exit_code=proc.returncode, per_test=False)

    def collect(self) -> List[str]:
        raise UsageError(
            "the command runner cannot discover tests; "
            "pass --tests or --tests-file"
        )

    def describe(self) -> str:
        return "command (%s)" % (self.template,)


@dataclass
class CachingRunner(Runner):
    """Memoize runs by exact order so ddmin never re-runs a probed subset.

    Sound because runs are hermetic: a fresh process given the same ordered
    ids is deterministic for order-dependent failures (true flakiness is
    detected separately, before minimization starts).
    """

    inner: Runner
    _cache: Dict[Tuple[str, ...], RunResult] = field(default_factory=dict)
    runs: int = 0
    hits: int = 0

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.inner.name

    def run(self, ids: Sequence[str]) -> RunResult:
        key = tuple(ids)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        result = self.inner.run(ids)
        self.runs += 1
        self._cache[key] = result
        return result

    def run_fresh(self, ids: Sequence[str]) -> RunResult:
        """Bypass the cache for a confirmation run; the fresh result wins."""
        result = self.inner.run(ids)
        self.runs += 1
        self._cache[tuple(ids)] = result
        return result

    def collect(self) -> List[str]:
        return self.inner.collect()

    def describe(self) -> str:
        return self.inner.describe()
