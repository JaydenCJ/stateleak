"""Render hunt results as human-readable text or machine-readable JSON.

The text report is written for a developer staring at a red CI run: it
names the exact polluter and victim, prints the minimal reproduction order,
and includes a copy-pasteable ``stateleak verify`` command. The JSON report
carries the same data for dashboards and scripted gates.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List, Optional

from .hunt import (
    KIND_ENABLER,
    KIND_FAILS_ALONE,
    KIND_FLAKY,
    KIND_POLLUTER,
    Finding,
    HuntReport,
)

_KIND_TITLES = {
    KIND_POLLUTER: "polluter -> victim",
    KIND_ENABLER: "victim depends on enabler state",
    KIND_FLAKY: "flaky (not order-dependent)",
    KIND_FAILS_ALONE: "fails alone (not order-dependent)",
}

_CULPRIT_LABELS = {KIND_POLLUTER: "polluter", KIND_ENABLER: "enabler"}


def _count(n: int, noun: str) -> str:
    """``1 test`` / ``2 tests`` — never the classic ``1 tests``."""
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def _verify_command(
    finding: Finding, runner_flag: str, rootdir: str = ".", cmd: Optional[str] = None
) -> str:
    parts = ["stateleak", "verify", "--runner", runner_flag]
    if cmd:
        parts += ["--cmd", shlex.quote(cmd)]
    if rootdir != ".":
        parts += ["--rootdir", shlex.quote(rootdir)]
    parts += [shlex.quote(t) for t in finding.repro_order()]
    return " ".join(parts)


def format_finding(
    index: int,
    finding: Finding,
    runner_flag: str,
    rootdir: str = ".",
    cmd: Optional[str] = None,
) -> List[str]:
    lines = []
    seed_note = " (seed %d)" % finding.seed if finding.seed is not None else ""
    lines.append(
        "FINDING %d: %s%s"
        % (index, _KIND_TITLES.get(finding.kind, finding.kind), seed_note)
    )
    lines.append("  victim   : %s" % finding.victim)
    label = _CULPRIT_LABELS.get(finding.kind)
    if label:
        if len(finding.culprits) == 1:
            lines.append("  %-9s: %s" % (label, finding.culprits[0]))
        else:
            lines.append(
                "  %-9s: %s" % (label + "s", _count(len(finding.culprits), "test"))
            )
            for culprit in finding.culprits:
                lines.append("      - %s" % culprit)
        lines.append(
            "  minimal repro (%s):" % _count(len(finding.repro_order()), "test")
        )
        for i, test_id in enumerate(finding.repro_order(), 1):
            lines.append("      %d. %s" % (i, test_id))
        lines.append(
            "  verify   : %s" % _verify_command(finding, runner_flag, rootdir, cmd)
        )
    lines.append("  evidence : %s" % finding.detail)
    return lines


def format_text(
    report: HuntReport, runner_flag: str, rootdir: str = ".", cmd: Optional[str] = None
) -> str:
    lines = ["stateleak report", "================"]
    lines.append("runner    : %s" % report.runner_desc)
    lines.append("suite     : %s" % _count(len(report.suite), "test"))
    if report.baseline_failures:
        lines.append(
            "baseline  : %d already failing in collected order (excluded):"
            % len(report.baseline_failures)
        )
        for test_id in report.baseline_failures:
            lines.append("    - %s" % test_id)
    else:
        lines.append("baseline  : PASS in collected order")
    if report.trials:
        failing = sum(1 for t in report.trials if t.new_failures)
        first_seed = report.trials[0].seed
        lines.append(
            "trials    : %d shuffle(s) from seed %d (%d clean, %d failing)"
            % (len(report.trials), first_seed, len(report.trials) - failing, failing)
        )
    for i, finding in enumerate(report.findings, 1):
        lines.append("")
        lines.extend(format_finding(i, finding, runner_flag, rootdir, cmd))
    lines.append("")
    dependencies = sum(1 for f in report.findings if f.is_order_dependency)
    cost = "%s, %d cached" % (_count(report.runs, "run"), report.cache_hits)
    if report.clean:
        lines.append("no order dependencies found (%s)" % cost)
    elif not report.findings:
        failing_seeds = [str(t.seed) for t in report.trials if t.new_failures]
        lines.append(
            "failing orders found at seed(s) %s; run stateleak hunt to "
            "minimize (%s)" % (", ".join(failing_seeds), cost)
        )
    else:
        lines.append(
            "order dependencies found: %d (%s)" % (dependencies, cost)
        )
    return "\n".join(lines)


def to_json(report: HuntReport, version: str) -> Dict[str, Any]:
    return {
        "stateleak": version,
        "runner": report.runner_desc,
        "suite_size": len(report.suite),
        "baseline_failures": list(report.baseline_failures),
        "trials": [
            {
                "seed": t.seed,
                "new_failures": list(t.new_failures),
                "identical_order": t.identical_order,
            }
            for t in report.trials
        ],
        "findings": [
            {
                "kind": f.kind,
                "victim": f.victim,
                "culprits": list(f.culprits),
                "seed": f.seed,
                "repro_order": f.repro_order() if f.culprits else [],
                "detail": f.detail,
            }
            for f in report.findings
        ],
        "runs": report.runs,
        "cache_hits": report.cache_hits,
        "clean": report.clean,
    }


def dumps_json(report: HuntReport, version: str) -> str:
    return json.dumps(to_json(report, version), indent=2, sort_keys=True)
