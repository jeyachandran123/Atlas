"""
Testing prompt modules.
"""

from __future__ import annotations

UNIT_TESTING = """\
Unit testing: AAA pattern (Arrange-Act-Assert), \
one behaviour per test, descriptive names \
(test_<what>_when_<condition>_should_<expected>), \
mock at the boundary, deterministic (no random data, no unmocked time)."""

INTEGRATION_TESTING = """\
Integration testing: test real component interactions, \
use test containers for databases, \
verify API contracts, and test failure scenarios \
(network timeouts, DB unavailability)."""

E2E_TESTING = """\
E2E testing with Playwright/Cypress: page object model, \
stable selectors (data-testid), \
parallel execution, visual regression, \
and CI integration."""

PYTEST = """\
Pytest expertise: fixtures (scope: function/class/module/session), \
parametrize, conftest.py, async tests (pytest-asyncio), \
coverage reporting, and pytest-mock."""
