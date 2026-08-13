"""Tests for inflation calculations."""
import pytest
from src.inflation import calculate_inflated_amount


class TestInflation:
    """Tests for calculate_inflated_amount function."""

    def test_no_reference_year(self):
        """Without reference year, no inflation compounding occurs."""
        # No reference year -> factor 1.0: 1000 * 1 = 1000
        assert calculate_inflated_amount(1000.0, 2030, None, 0.03) == 1000.0
        # Multiplier only: 1000 * 1.5 = 1500
        assert calculate_inflated_amount(1000.0, 2030, None, 0.03, multiplier=1.5) == 1500.0

    def test_reference_year_same_as_current(self):
        """Same year as reference should return base * multiplier."""
        # Factor (1.05)^0 = 1: 1000 * 1 = 1000
        assert calculate_inflated_amount(1000.0, 2026, 2026, 0.05) == 1000.0
        # 1000 * 2.0 = 2000
        assert calculate_inflated_amount(1000.0, 2026, 2026, 0.05, multiplier=2.0) == 2000.0

    def test_inflation_compounding_positive(self):
        """Test positive inflation compounding."""
        # Base $100 in 2026, evaluated in 2028 @ 5% inflation = $100 * (1.05)^2 = $110.25
        assert calculate_inflated_amount(100.0, 2028, 2026, 0.05) == pytest.approx(110.25)

        # Base $50,000 in 2026, evaluated in 2030 @ 2.5% inflation = 50000 * (1.025)^4
        expected = 50000.0 * (1.025 ** 4)
        assert calculate_inflated_amount(50000.0, 2030, 2026, 0.025) == pytest.approx(expected)

    def test_inflation_compounding_zero(self):
        """Zero inflation rate should return base * multiplier."""
        # Factor (1.0)^4 = 1: 1000 * 1 = 1000
        assert calculate_inflated_amount(1000.0, 2030, 2026, 0.0) == 1000.0

    def test_negative_inflation(self):
        """Negative inflation (deflation) should decrease amount."""
        # Base $100 in 2026, evaluated in 2028 @ -2% inflation = $100 * (0.98)^2 = $96.04
        assert calculate_inflated_amount(100.0, 2028, 2026, -0.02) == pytest.approx(96.04)

    def test_multiplier_applied(self):
        """Multiplier should be applied before inflation."""
        # Base $100 * multiplier 1.5 = $150, then inflated
        assert calculate_inflated_amount(100.0, 2028, 2026, 0.05, multiplier=1.5) == pytest.approx(150.0 * 1.1025)

    def test_multiplier_without_inflation(self):
        """Multiplier without reference year."""
        # No reference year -> multiplier only: 100 * 2.0 = 200
        assert calculate_inflated_amount(100.0, 2030, None, 0.03, multiplier=2.0) == 200.0

    def test_many_years(self):
        """Test compounding over many years."""
        # $1000 at 3% for 30 years = 1000 * 1.03^30
        expected = 1000.0 * (1.03 ** 30)
        assert calculate_inflated_amount(1000.0, 2056, 2026, 0.03) == pytest.approx(expected)

    def test_fractional_base_amount(self):
        """Fractional base amounts should work."""
        # 1000.50 * (1.05)^2 = 1000.50 * 1.1025
        assert calculate_inflated_amount(1000.50, 2028, 2026, 0.05) == pytest.approx(1000.50 * 1.1025)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])