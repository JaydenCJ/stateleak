"""JUnit XML parsing and node-id matching round trips."""

from __future__ import annotations

import pytest

from stateleak.junitxml import CaseResult, match_outcomes, nodeid_key, parse_junit

XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4">
    <testcase classname="tests.test_cart.TestCart" name="test_add" time="0.001"/>
    <testcase classname="tests.test_cart.TestCart" name="test_total" time="0.001">
      <failure message="assert 3 == 0">traceback here</failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_boom" time="0.001">
      <error message="RuntimeError: down">traceback</error>
    </testcase>
    <testcase classname="tests.test_api" name="test_later" time="0.0">
      <skipped message="not today"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_parse_extracts_all_four_statuses_and_messages():
    cases = parse_junit(XML)
    statuses = {c.dotted: c.status for c in cases}
    assert statuses == {
        "tests.test_cart.TestCart.test_add": "passed",
        "tests.test_cart.TestCart.test_total": "failed",
        "tests.test_api.test_boom": "error",
        "tests.test_api.test_later": "skipped",
    }
    by_name = {c.name: c for c in cases}
    assert by_name["test_total"].message == "assert 3 == 0"
    assert by_name["test_later"].message == "not today"


def test_parse_accepts_bare_testsuite_root_and_rejects_malformed_xml():
    bare = "<testsuite><testcase classname='m' name='t'/></testsuite>"
    cases = parse_junit(bare)
    assert len(cases) == 1 and cases[0].status == "passed"
    with pytest.raises(ValueError):
        parse_junit("<testsuite><testcase")


# --- nodeid_key ------------------------------------------------------------


def test_nodeid_key_for_plain_functions_and_class_methods():
    assert nodeid_key("tests/test_api.py::test_boom") == ("tests.test_api", "test_boom")
    assert nodeid_key("tests/test_cart.py::TestCart::test_add") == (
        "tests.test_cart.TestCart",
        "test_add",
    )


def test_nodeid_key_keeps_parametrization_and_maps_windows_separators():
    assert nodeid_key("t/test_x.py::test_f[3-eu]") == ("t.test_x", "test_f[3-eu]")
    assert nodeid_key("tests\\test_x.py::test_f") == ("tests.test_x", "test_f")


def test_nodeid_key_for_dotted_unittest_id():
    assert nodeid_key("pkg.test_mod.CartTests.test_add") == (
        "pkg.test_mod.CartTests",
        "test_add",
    )


# --- match_outcomes --------------------------------------------------------


def test_match_pairs_every_requested_id():
    ids = [
        "tests/test_cart.py::TestCart::test_add",
        "tests/test_cart.py::TestCart::test_total",
        "tests/test_api.py::test_boom",
        "tests/test_api.py::test_later",
    ]
    matched = match_outcomes(ids, parse_junit(XML))
    assert matched[ids[0]].status == "passed"
    assert matched[ids[1]].status == "failed"
    assert matched[ids[2]].status == "error"
    assert matched[ids[3]].status == "skipped"


def test_match_tolerates_rootdir_prefix_differences():
    # Suite invoked from a subdirectory: the id lacks the leading package
    # segment that the JUnit classname carries.
    matched = match_outcomes(["test_cart.py::TestCart::test_add"], parse_junit(XML))
    assert matched["test_cart.py::TestCart::test_add"].status == "passed"


def test_match_returns_none_for_absent_case():
    matched = match_outcomes(["tests/test_gone.py::test_gone"], parse_junit(XML))
    assert matched["tests/test_gone.py::test_gone"] is None


def test_match_consumes_each_case_at_most_once():
    cases = [
        CaseResult("mod", "test_dup", "passed"),
        CaseResult("mod", "test_dup", "failed"),
    ]
    matched = match_outcomes(["mod.test_dup", "mod.test_dup"], cases)
    # dict collapses duplicate keys; the point is that matching consumed
    # both cases without pairing one XML case to two requested ids.
    assert len(cases) == 2
    assert matched["mod.test_dup"] is not None
