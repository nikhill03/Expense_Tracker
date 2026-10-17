"""
tests/test_rupees_filter.py

Unit tests for app.rupees(), the Jinja filter that formats a plain number as
money — the amount-layer counterpart to |dmy for dates. Not tied to a numbered
step: this is the cleanup from ARCHITECTURE_REVIEW.md §4 that moved amount
formatting out of database/queries.py and into the template, the same move
already made for dates. Coverage of the formatted output in context (commas,
the ₹ sign, decimals=0 for "safe to spend per day") lives in the route tests
that render these pages; this file is just the function in isolation.
"""

import pytest

from app import rupees


class TestRupeesFilter:
    def test_formats_with_two_decimals_by_default(self):
        assert rupees(1234.5) == "₹1,234.50"

    def test_adds_thousands_separators(self):
        # Python's `,` format spec groups in 3s (1,234,567), not the Indian
        # 2-2-3 lakh/crore grouping (12,34,567) — unchanged from the f-strings
        # this filter replaced, which used the same format spec.
        assert rupees(1234567.89) == "₹1,234,567.89"

    def test_zero(self):
        assert rupees(0) == "₹0.00"

    def test_integer_input(self):
        """Query-layer sums can come back as ints (e.g. COALESCE(SUM(...), 0))."""
        assert rupees(500) == "₹500.00"

    def test_decimals_zero_rounds_to_a_whole_number(self):
        """Used for 'safe to spend per day' — a precise paise figure reads as
        noise there, not precision."""
        assert rupees(454.5454545, decimals=0) == "₹455"

    def test_none_passes_through_unchanged(self):
        """Mirrors |dmy's leniency: a field that is legitimately absent (an
        event with no budget set) must not render as 'None' or raise."""
        assert rupees(None) is None

    def test_non_numeric_string_passes_through_unchanged(self):
        assert rupees("not a number") == "not a number"
