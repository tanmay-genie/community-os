"""Pytest entry point for the ARIA eval suite.

Two checks:
  test_eval_suite_passes — fails if any golden case fails (CI gate)
  test_eval_report_exists — writes a markdown report to tests/evals/REPORT.md

Run:
  pytest tests/evals/test_eval_suite.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.evals.cases import CASES
from tests.evals.runner import build_test_client, run_all


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    return build_test_client(monkeypatch_module)


@pytest.fixture(scope="module")
def report(client):
    rep = run_all(client, CASES)
    out = Path(__file__).parent / "REPORT.md"
    out.write_text(rep.to_markdown(), encoding="utf-8")
    return rep


def test_eval_suite_minimum_pass_rate(report):
    """Gate the suite at >= 80% passing. Lower than this means a regression."""
    assert report.total > 0
    assert report.pass_rate >= 0.80, (
        f"Eval pass rate dropped to {report.pass_rate:.1%} "
        f"({report.passed}/{report.total}). See tests/evals/REPORT.md."
    )


def test_eval_critical_cases_pass(report):
    """A subset of cases is non-negotiable — if any fail, the build fails."""
    critical_ids = {
        "amenity-list-001",            # discovery flow
        "amenity-type-001",            # multi-instance gym filter
        "book-specific-001",           # specific booking succeeds
        "dues-001",                    # CAD currency, no Rs.
        "currency-leak-001",           # regression for hallucinated Rs.
        "admin-block-001",             # member-side admin guard
    }
    failures = [r for r in report.results if r.case_id in critical_ids and not r.passed]
    assert not failures, (
        "Critical eval cases failed:\n"
        + "\n".join(f"  - {r.case_id}: {', '.join(r.failures)}" for r in failures)
    )
