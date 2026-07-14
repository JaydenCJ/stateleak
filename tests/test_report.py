"""Text and JSON rendering of hunt reports."""

from __future__ import annotations

import json

from stateleak import __version__
from stateleak.hunt import (
    KIND_ENABLER,
    KIND_FLAKY,
    KIND_POLLUTER,
    Finding,
    HuntReport,
    TrialRecord,
)
from stateleak.report import dumps_json, format_text, to_json


def make_report(findings=(), baseline_failures=(), trials=()):
    return HuntReport(
        runner_desc="unittest (rootdir=/repo)",
        suite=["a", "b", "c", "d"],
        baseline_failures=list(baseline_failures),
        trials=list(trials),
        findings=list(findings),
        runs=9,
        cache_hits=2,
    )


def polluter_finding():
    return Finding(
        kind=KIND_POLLUTER,
        victim="tests/test_audit.py::test_empty",
        culprits=["tests/test_recv.py::test_add"],
        seed=3,
        detail="victim passes alone but fails after the polluter set",
    )


def test_text_names_polluter_and_victim():
    text = format_text(make_report([polluter_finding()]), "pytest")
    assert "polluter -> victim" in text
    assert "victim   : tests/test_audit.py::test_empty" in text
    assert "polluter : tests/test_recv.py::test_add" in text
    assert "(seed 3)" in text


def test_text_includes_copy_pasteable_verify_command():
    text = format_text(make_report([polluter_finding()]), "pytest", rootdir="my proj")
    assert (
        "stateleak verify --runner pytest --rootdir 'my proj' "
        "tests/test_recv.py::test_add tests/test_audit.py::test_empty" in text
    )
    # The command runner's template must ride along, or the printed line
    # would exit 2 when pasted back.
    text = format_text(
        make_report([polluter_finding()]),
        "command",
        cmd="python3 -m unittest {tests}",
    )
    assert (
        "stateleak verify --runner command --cmd 'python3 -m unittest {tests}' "
        "tests/test_recv.py::test_add tests/test_audit.py::test_empty" in text
    )


def test_text_renders_multi_culprit_findings_as_a_list():
    finding = Finding(
        kind=KIND_POLLUTER, victim="v", culprits=["p1", "p2"], seed=1, detail="d"
    )
    text = format_text(make_report([finding]), "unittest")
    assert "polluters: 2 tests" in text
    assert "- p1" in text and "- p2" in text
    assert "minimal repro (3 tests):" in text


def test_text_for_enabler_uses_enabler_label():
    finding = Finding(
        kind=KIND_ENABLER, victim="v", culprits=["setup_test"], seed=2, detail="d"
    )
    text = format_text(make_report([finding]), "unittest")
    assert "depends on enabler state" in text
    assert "enabler  : setup_test" in text


def test_text_for_flaky_finding_has_no_repro_section():
    finding = Finding(kind=KIND_FLAKY, victim="v", culprits=[], seed=2, detail="d")
    text = format_text(make_report([finding]), "unittest")
    assert "flaky" in text
    assert "verify" not in text
    assert "minimal repro" not in text


def test_text_summary_footer_is_honest_in_clean_and_scan_only_modes():
    text = format_text(make_report(), "unittest")
    assert "no order dependencies found (9 runs, 2 cached)" in text
    # Scan-only (shuffle) failures must not claim "found: 0" while exiting 1.
    trial = TrialRecord(seed=4, order=["b", "a"], new_failures=["a"], identical_order=False)
    text = format_text(make_report(trials=[trial]), "pytest")
    assert "failing orders found at seed(s) 4; run stateleak hunt" in text
    assert "order dependencies found: 0" not in text


def test_text_uses_singular_nouns_for_counts_of_one():
    # A single-test suite investigated in a single run must not read
    # "1 tests" / "1 runs" — the classic pluralization bug.
    report = HuntReport(
        runner_desc="unittest (rootdir=/repo)",
        suite=["only"],
        baseline_failures=[],
        runs=1,
        cache_hits=0,
    )
    text = format_text(report, "unittest")
    assert "suite     : 1 test\n" in text
    assert "no order dependencies found (1 run, 0 cached)" in text


def test_text_lists_baseline_failures():
    text = format_text(make_report(baseline_failures=["a", "b"]), "unittest")
    assert "2 already failing in collected order" in text
    assert "    - a" in text


def test_json_report_carries_all_fields():
    trial = TrialRecord(seed=5, order=["b", "a"], new_failures=["a"], identical_order=False)
    data = to_json(make_report([polluter_finding()], trials=[trial]), __version__)
    assert data["stateleak"] == __version__
    assert data["suite_size"] == 4
    assert data["clean"] is False
    assert data["trials"] == [
        {"seed": 5, "new_failures": ["a"], "identical_order": False}
    ]
    finding = data["findings"][0]
    assert finding["kind"] == "polluter"
    assert finding["repro_order"] == [
        "tests/test_recv.py::test_add",
        "tests/test_audit.py::test_empty",
    ]
    # The serialized form is stable and parseable.
    dumped = dumps_json(make_report([polluter_finding()]), __version__)
    assert dumped == dumps_json(make_report([polluter_finding()]), __version__)
    assert json.loads(dumped)["runs"] == 9
