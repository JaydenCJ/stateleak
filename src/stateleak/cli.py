"""Command-line interface for stateleak.

Subcommands:

* ``hunt``    — shuffle until an order-dependent failure appears, then
  delta-debug it down to the minimal polluter/victim pair. The flagship.
* ``shuffle`` — seeded shuffle scan only (no minimization); fast signal
  for CI gates.
* ``bisect``  — minimize a known-failing order supplied via ``--order-file``
  or reconstructed from ``--seed``.
* ``verify``  — run an explicit order once and show per-test outcomes;
  the repro command printed in every finding.
* ``plan``    — print the exact order a seed produces, without running
  anything.

Exit codes: 0 = clean, 1 = order dependencies (or failures in ``verify``),
2 = usage or infrastructure error.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List, Optional, Sequence

from . import __version__
from .errors import StateleakError, UsageError
from .hunt import bisect_order, hunt
from .report import dumps_json, format_text
from .runner import CommandRunner, PytestRunner, Runner, UnittestRunner
from .shuffle import shuffled_order

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_ERROR = 2


def _add_runner_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("runner")
    group.add_argument(
        "--runner",
        choices=("pytest", "unittest", "command"),
        default="pytest",
        help="how to execute the suite (default: pytest)",
    )
    group.add_argument(
        "--rootdir", default=".", help="suite root directory (default: .)"
    )
    group.add_argument(
        "--python",
        default=None,
        help="interpreter for the target suite (default: this one)",
    )
    group.add_argument(
        "--cmd",
        default=None,
        help="command template for --runner command; must contain {tests}, "
        "may contain {junit} for per-test outcomes",
    )
    group.add_argument(
        "--pytest-args",
        default="",
        metavar="ARGS",
        help="extra arguments appended to every pytest invocation "
        "(quoted string, split shell-style)",
    )
    group.add_argument(
        "--pattern",
        default="test*.py",
        help="unittest discovery pattern (default: test*.py)",
    )
    group.add_argument(
        "--start-dir",
        default=None,
        help="unittest discovery start directory (default: rootdir)",
    )
    group.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="per-run timeout in seconds (default: 300)",
    )


def _add_selection_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("test selection")
    group.add_argument(
        "--tests",
        nargs="+",
        default=None,
        metavar="ID",
        help="explicit test ids (skips discovery)",
    )
    group.add_argument(
        "--tests-file",
        default=None,
        help="file with one test id per line (# comments allowed)",
    )


def build_runner(args: argparse.Namespace) -> Runner:
    if args.runner == "unittest":
        return UnittestRunner(
            rootdir=args.rootdir,
            python=args.python,
            pattern=args.pattern,
            start_dir=args.start_dir,
            timeout=args.timeout,
        )
    if args.runner == "command":
        if not args.cmd:
            raise UsageError("--runner command requires --cmd")
        return CommandRunner(
            template=args.cmd, rootdir=args.rootdir, timeout=args.timeout
        )
    return PytestRunner(
        rootdir=args.rootdir,
        python=args.python,
        extra_args=shlex.split(args.pytest_args),
        timeout=args.timeout,
    )


def _read_ids_file(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise UsageError("cannot read %s: %s" % (path, exc)) from exc
    ids = [ln.strip() for ln in lines]
    return [i for i in ids if i and not i.startswith("#")]


def resolve_tests(args: argparse.Namespace, runner: Runner) -> List[str]:
    if args.tests and args.tests_file:
        raise UsageError("--tests and --tests-file are mutually exclusive")
    if args.tests:
        return list(args.tests)
    if args.tests_file:
        ids = _read_ids_file(args.tests_file)
        if not ids:
            raise UsageError("%s contains no test ids" % args.tests_file)
        return ids
    ids = runner.collect()
    if not ids:
        raise UsageError(
            "no tests collected; check --rootdir or pass --tests explicitly"
        )
    return ids


def _emit(report, args, out) -> int:
    if args.json:
        out.write(dumps_json(report, __version__) + "\n")
    else:
        cmd = args.cmd if args.runner == "command" else None
        out.write(format_text(report, args.runner, args.rootdir, cmd) + "\n")
    return EXIT_CLEAN if report.clean else EXIT_FOUND


def cmd_hunt(args: argparse.Namespace, out) -> int:
    runner = build_runner(args)
    ids = resolve_tests(args, runner)
    report = hunt(
        runner,
        ids,
        base_seed=args.seed,
        trials=args.trials,
        max_victims=args.max_victims,
        keep_going=args.keep_going,
        minimize=True,
    )
    return _emit(report, args, out)


def cmd_shuffle(args: argparse.Namespace, out) -> int:
    runner = build_runner(args)
    ids = resolve_tests(args, runner)
    report = hunt(
        runner,
        ids,
        base_seed=args.seed,
        trials=args.trials,
        minimize=False,
    )
    return _emit(report, args, out)


def cmd_bisect(args: argparse.Namespace, out) -> int:
    runner = build_runner(args)
    if bool(args.order_file) == bool(args.seed is not None):
        raise UsageError("bisect needs exactly one of --order-file or --seed")
    if args.order_file:
        order = _read_ids_file(args.order_file)
        if not order:
            raise UsageError("%s contains no test ids" % args.order_file)
        baseline: Optional[List[str]] = None
    else:
        baseline = resolve_tests(args, runner)
        order = shuffled_order(baseline, args.seed)
    report = bisect_order(runner, order, victim=args.victim, baseline_order=baseline)
    return _emit(report, args, out)


def cmd_verify(args: argparse.Namespace, out) -> int:
    runner = build_runner(args)
    result = runner.run(args.ids)
    width = max(len(i) for i in args.ids)
    for test_id in args.ids:
        status = result.status_of(test_id)
        if not result.per_test and status == "unknown":
            status = "(exit %d)" % result.exit_code
        out.write("%-*s  %s\n" % (width, test_id, status))
    failed = result.any_failure()
    out.write("verify: %s\n" % ("FAIL" if failed else "PASS"))
    return EXIT_FOUND if failed else EXIT_CLEAN


def cmd_plan(args: argparse.Namespace, out) -> int:
    runner = build_runner(args)
    ids = resolve_tests(args, runner)
    for test_id in shuffled_order(ids, args.seed):
        out.write(test_id + "\n")
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stateleak",
        description="Find test-order dependencies and name the exact "
        "polluter/victim pair via seeded shuffling and delta debugging.",
    )
    parser.add_argument(
        "--version", action="version", version="stateleak %s" % __version__
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_hunt = sub.add_parser(
        "hunt", help="shuffle until a failure appears, then minimize it"
    )
    _add_runner_options(p_hunt)
    _add_selection_options(p_hunt)
    p_hunt.add_argument("--seed", type=int, default=1, help="base seed (default: 1)")
    p_hunt.add_argument(
        "--trials", type=int, default=10, help="number of shuffles (default: 10)"
    )
    p_hunt.add_argument(
        "--max-victims",
        type=int,
        default=3,
        help="minimize at most this many victims (default: 3)",
    )
    p_hunt.add_argument(
        "--keep-going",
        action="store_true",
        help="continue trials after the first failing shuffle",
    )
    p_hunt.add_argument("--json", action="store_true", help="emit a JSON report")
    p_hunt.set_defaults(func=cmd_hunt)

    p_shuffle = sub.add_parser(
        "shuffle", help="seeded shuffle scan without minimization"
    )
    _add_runner_options(p_shuffle)
    _add_selection_options(p_shuffle)
    p_shuffle.add_argument("--seed", type=int, default=1, help="base seed (default: 1)")
    p_shuffle.add_argument(
        "--trials", type=int, default=10, help="number of shuffles (default: 10)"
    )
    p_shuffle.add_argument("--json", action="store_true", help="emit a JSON report")
    p_shuffle.set_defaults(func=cmd_shuffle)

    p_bisect = sub.add_parser("bisect", help="minimize a known-failing order")
    _add_runner_options(p_bisect)
    _add_selection_options(p_bisect)
    p_bisect.add_argument(
        "--order-file", default=None, help="file with the failing order, one id per line"
    )
    p_bisect.add_argument(
        "--seed", type=int, default=None, help="reconstruct the order from this seed"
    )
    p_bisect.add_argument(
        "--victim", default=None, help="the failing test (default: auto-detect)"
    )
    p_bisect.add_argument("--json", action="store_true", help="emit a JSON report")
    p_bisect.set_defaults(func=cmd_bisect)

    p_verify = sub.add_parser("verify", help="run an explicit order once")
    _add_runner_options(p_verify)
    p_verify.add_argument("ids", nargs="+", metavar="ID", help="test ids, in order")
    p_verify.set_defaults(func=cmd_verify)

    p_plan = sub.add_parser("plan", help="print the order for a seed (no run)")
    _add_runner_options(p_plan)
    _add_selection_options(p_plan)
    p_plan.add_argument("--seed", type=int, required=True, help="seed to expand")
    p_plan.set_defaults(func=cmd_plan)

    return parser


def main(argv: Optional[Sequence[str]] = None, out=None) -> int:
    out = out if out is not None else sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return args.func(args, out)
    except StateleakError as exc:
        sys.stderr.write("stateleak: error: %s\n" % (exc,))
        return EXIT_ERROR


def console_main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    console_main()
