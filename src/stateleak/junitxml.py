"""Parse JUnit XML reports and match test cases back to requested ids.

pytest (and most other runners) can emit a JUnit XML report. The report
identifies a case by ``(classname, name)`` — e.g. classname
``tests.test_cart.TestCart``, name ``test_add`` — while stateleak addresses
tests by runner id, e.g. ``tests/test_cart.py::TestCart::test_add``. This
module converts between the two so that per-test outcomes survive the round
trip through any JUnit-emitting runner.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CaseResult:
    """One <testcase> element: identity plus outcome."""

    classname: str
    name: str
    status: str  # passed | failed | error | skipped
    message: str = ""

    @property
    def dotted(self) -> str:
        if self.classname:
            return "%s.%s" % (self.classname, self.name)
        return self.name


def parse_junit(xml_text: str) -> List[CaseResult]:
    """Extract all test cases from a JUnit XML document.

    Handles both a root ``<testsuites>`` wrapper (pytest's xunit2 family)
    and a bare ``<testsuite>`` root. Raises ``ValueError`` on malformed XML
    so runners can convert it into a clear infrastructure error.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("malformed JUnit XML: %s" % (exc,)) from exc
    cases: List[CaseResult] = []
    for case in root.iter("testcase"):
        status = "passed"
        message = ""
        for child in case:
            if child.tag == "failure":
                status = "failed"
            elif child.tag == "error":
                status = "error"
            elif child.tag == "skipped":
                status = "skipped"
            else:
                continue
            message = (child.get("message") or "").strip()
            break
        cases.append(
            CaseResult(
                classname=case.get("classname", "") or "",
                name=case.get("name", "") or "",
                status=status,
                message=message,
            )
        )
    return cases


def nodeid_key(nodeid: str) -> Tuple[str, str]:
    """Map a pytest-style node id to the expected ``(classname, name)``.

    ``tests/test_cart.py::TestCart::test_add[eu]`` becomes
    ``("tests.test_cart.TestCart", "test_add[eu]")``. Plain dotted unittest
    ids (``pkg.mod.Class.test_x``) are returned split on the last dot, so
    the same matcher works for JUnit reports produced by unittest wrappers.
    """
    if "::" in nodeid:
        parts = nodeid.split("::")
        path, rest = parts[0], parts[1:]
        module = path
        if module.endswith(".py"):
            module = module[: -len(".py")]
        module = module.replace("/", ".").replace("\\", ".")
        classes = rest[:-1]
        name = rest[-1]
        classname = ".".join([module] + list(classes)) if classes else module
        return classname, name
    if "." in nodeid:
        classname, name = nodeid.rsplit(".", 1)
        return classname, name
    return "", nodeid


def _classname_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    # Tolerate rootdir differences: one side may carry extra leading
    # package segments (e.g. "tests.test_cart" vs "test_cart").
    return expected.endswith("." + actual) or actual.endswith("." + expected)


def match_outcomes(
    ids: Sequence[str], cases: Sequence[CaseResult]
) -> Dict[str, Optional[CaseResult]]:
    """Pair each requested id with its JUnit case, ``None`` when absent.

    Matching is exact-first, then suffix-tolerant on the classname. Each
    case is consumed at most once so parametrized ids with identical names
    under different classes cannot double-match.
    """
    remaining = list(cases)
    matched: Dict[str, Optional[CaseResult]] = {}
    for nodeid in ids:
        classname, name = nodeid_key(nodeid)
        found = None
        for i, case in enumerate(remaining):
            if case.name == name and case.classname == classname:
                found = remaining.pop(i)
                break
        if found is None:
            for i, case in enumerate(remaining):
                if case.name == name and _classname_matches(classname, case.classname):
                    found = remaining.pop(i)
                    break
        matched[nodeid] = found
    return matched
