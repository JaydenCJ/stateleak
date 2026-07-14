"""Exception hierarchy for stateleak.

Every error that should abort a command maps to exit code 2 (usage or
infrastructure problem). Findings — actual order dependencies — are not
errors; they are reported and surface as exit code 1.
"""

from __future__ import annotations


class StateleakError(Exception):
    """Base class for all stateleak errors (CLI exit code 2)."""


class UsageError(StateleakError):
    """The command line arguments are inconsistent or incomplete."""


class SuiteError(StateleakError):
    """The target suite could not be collected or executed.

    Raised for infrastructure failures: the test runner crashed, produced
    unparseable output, or timed out. Distinct from tests *failing*, which
    is a normal, expected observation.
    """


class RunTimeout(SuiteError):
    """A single suite invocation exceeded the configured timeout."""
