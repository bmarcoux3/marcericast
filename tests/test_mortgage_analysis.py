"""
Tests for mortgage analysis sidecar module.
"""
import pytest
from src.mortgage_analysis import (
    MortgageParams,
    AffordabilityResult,
    AmortizationRow,
    calculate_monthly_payment,
    calculate_affordability,
    generate_amortization_schedule,
    compare_scenarios,
    _reverse_calculate_max_price,
)


class TestMonthlyPayment:
    """Test monthly payment calculation."""

    def test_standard_mortgage(self):
        """Test standard 30-year mortgage payment."""
        payment = calculate_monthly_payment(400000, 0.065, 30)
        # $400k at 6.5% for 30 years = $2,528.27
        assert payment == pytest.approx(2528.27, rel=0.01)

    def test_zero_rate(self):
        """Test zero interest rate."""
        payment = calculate_monthly_payment(360000, 0.0, 30)
        # $360k / 360 months = $1000
        assert payment == 1000.0

    def test_short_term(self):
        """Test 15-year mortgage."""
        payment = calculate_monthly_payment(300000, 0.05, 15)
        # PMT = 300000 * (0.05/12) / (1 - (1 + 0.05/12)^-180) = 2,372.38
        assert payment == pytest.approx(2372.38, rel=0.01)

    def test_zero_principal(self):
        """Test zero principal returns zero."""
        payment = calculate_monthly_payment(0, 0.065, 30)
        # 0 principal -> 0 payment regardless of rate/term
        assert payment == 0.0


class TestAffordability:
    """Test affordability calculations."""

    def test_basic_affordability(self):
        """Test basic affordability calculation."""
        params = MortgageParams(
            home_price=500000,
            down_payment=100000,
            interest_rate=0.065,
            term_years=30,
        )
        result = calculate_affordability(
            monthly_income=10000,
            max_dti_ratio=0.36,
            existing_monthly_debts=0,
            params=params,
        )

        # Loan = 500000 - 100000 = 400000; PMT at 6.5%/30yr = 2,528.27
        assert result.monthly_principal_interest == pytest.approx(2528.27, rel=0.01)
        # 500000 home - 100000 down = 400000 loan
        assert result.loan_amount == 400000
        # 100000 / 500000 = 0.20 (20% down)
        assert result.down_payment_pct == 0.20
        # With no tax/insurance/HOA/PMI, total = P&I
        assert result.total_monthly == result.monthly_principal_interest

    def test_affordability_with_tax_insurance(self):
        """Test affordability with property tax and insurance."""
        params = MortgageParams(
            home_price=500000,
            down_payment=100000,
            interest_rate=0.065,
            term_years=30,
            property_tax_rate=0.02,      # 2% = $10k/year
            insurance_rate=0.005,        # 0.5% = $2.5k/year
            hoa_fee=300,
        )
        result = calculate_affordability(
            monthly_income=10000,
            max_dti_ratio=0.36,
            existing_monthly_debts=0,
            params=params,
        )

        # Tax: $500k * 0.02 / 12 = $833.33
        assert result.monthly_property_tax == pytest.approx(833.33, rel=0.01)
        # Insurance: $500k * 0.005 / 12 = $208.33
        assert result.monthly_insurance == pytest.approx(208.33, rel=0.01)
        assert result.monthly_hoa == 300  # Pass-through of hoa_fee=300
        # 100000/500000 = 20% down >= 20% threshold -> no PMI -> 0
        assert result.monthly_pmi == 0  # 20% down, no PMI

        # Total = 2528.27 + 833.33 + 208.33 + 300 = 3869.93
        assert result.total_monthly == pytest.approx(3869.93, rel=0.01)

    def test_affordability_with_pmi(self):
        """Test affordability with PMI (down payment < 20%)."""
        params = MortgageParams(
            home_price=500000,
            down_payment=50000,  # 10% down
            interest_rate=0.065,
            term_years=30,
            pmi_rate=0.005,  # 0.5% PMI
        )
        result = calculate_affordability(
            monthly_income=10000,
            max_dti_ratio=0.36,
            existing_monthly_debts=0,
            params=params,
        )

        # 50000 / 500000 = 0.10 (10% down)
        assert result.down_payment_pct == 0.10
        # PMI: $450k * 0.005 / 12 = $187.50
        assert result.monthly_pmi == pytest.approx(187.50, rel=0.01)

    def test_max_affordable_price_calculation(self):
        """Test reverse calculation of max affordable price."""
        params = MortgageParams(
            home_price=600000,  # Too expensive for income
            down_payment=120000,
            interest_rate=0.065,
            term_years=30,
            property_tax_rate=0.02,
            insurance_rate=0.005,
        )
        result = calculate_affordability(
            monthly_income=8000,  # $8k/month income
            max_dti_ratio=0.36,
            existing_monthly_debts=500,  # $500 other debts
            params=params,
        )

        # Max DTI budget = 8000 * 0.36 = 2880, minus 500 existing debts = 2380 available.
        # A $600k home (loan 480,000) at 6.5%/30yr costs ~3,034/mo > 2380,
        # so the max affordable price must fall below $600k.
        assert result.max_affordable_price is not None
        assert result.max_affordable_price < 600000

    def test_dti_limit_respected(self):
        """Test that DTI limit caps affordability."""
        params = MortgageParams(
            home_price=1000000,
            down_payment=200000,
            interest_rate=0.065,
            term_years=30,
        )
        result = calculate_affordability(
            monthly_income=10000,
            max_dti_ratio=0.36,
            existing_monthly_debts=0,
            params=params,
        )

        # Max debt payment = $10,000 * 0.36 = $3,600
        # Payment for $1M home (loan 800k at 6.5%/30yr ~ 5,057) exceeds 3,600,
        # so max_affordable_price should be set below $1M
        assert result.max_affordable_price is not None
        assert result.max_affordable_price < 1000000


class TestAmortization:
    """Test amortization schedule generation."""

    def test_basic_schedule(self):
        """Test basic amortization schedule."""
        schedule = generate_amortization_schedule(300000, 0.05, 15)

        # term_years=15 -> 15 annual rows
        assert len(schedule) == 15
        # First year
        assert schedule[0].year == 1
        # Year 1 starts at full original principal
        assert schedule[0].beginning_balance == 300000
        # First year's payment includes principal, so balance drops below 300000
        assert schedule[0].ending_balance < 300000

        # Last year should have zero balance
        assert schedule[-1].ending_balance == pytest.approx(0, abs=1.0)

        # Cumulative principal should equal original loan
        assert schedule[-1].cumulative_principal == pytest.approx(300000, abs=1.0)

    def test_schedule_with_extra_payment(self):
        """Test amortization with extra payment."""
        schedule = generate_amortization_schedule(300000, 0.05, 15, extra_monthly_payment=500)

        # Extra $500/mo shortens the term below 180 months -> fewer than 15 rows
        assert len(schedule) < 15
        # Paid off early -> ending balance ~0
        assert schedule[-1].ending_balance == pytest.approx(0, abs=1.0)

        # Total interest should be less
        total_interest = schedule[-1].cumulative_interest
        # Compare with no extra payment
        normal_schedule = generate_amortization_schedule(300000, 0.05, 15)
        normal_interest = normal_schedule[-1].cumulative_interest
        assert total_interest < normal_interest

    def test_payment_split(self):
        """Test that payment = principal + interest each year."""
        schedule = generate_amortization_schedule(200000, 0.06, 30)

        for row in schedule:
            assert row.payment == pytest.approx(row.principal + row.interest, rel=0.01)


class TestScenarioComparison:
    """Test scenario comparison."""

    def test_compare_scenarios(self):
        """Test comparing multiple scenarios."""
        base_params = MortgageParams(
            home_price=500000,
            down_payment=100000,
            interest_rate=0.065,
            term_years=30,
        )
        variations = [
            {"name": "Rate 7%", "interest_rate": 0.07},
            {"name": "Rate 7.5%", "interest_rate": 0.075},
        ]

        results = compare_scenarios(
            base_params=base_params,
            variations=variations,
            monthly_income=10000,
            max_dti_ratio=0.36,
            existing_monthly_debts=0,
        )

        assert len(results) == 3  # Base + 2 variations
        assert results[0]["name"] == "Base"
        assert results[1]["name"] == "Rate 7%"
        assert results[2]["name"] == "Rate 7.5%"

        # Higher rate = higher payment
        assert results[2]["result"].monthly_principal_interest > results[1]["result"].monthly_principal_interest
        assert results[1]["result"].monthly_principal_interest > results[0]["result"].monthly_principal_interest


class TestReverseCalculation:
    """Test reverse price calculation."""

    def test_reverse_calculate_max_price(self):
        """Test binary search for max affordable price."""
        # $3600/month available, 20% down, 6.5%, 30yr, no tax/insurance
        max_price = _reverse_calculate_max_price(
            available_for_mortgage=3600,
            down_payment_pct=0.20,
            interest_rate=0.065,
            term_years=30,
            property_tax_rate=0.0,
            insurance_rate=0.0,
            hoa_fee=0.0,
            pmi_rate=0.0,
        )

        # At 6.5% for 30yr, $3600/month PI supports ~$569k loan
        # With 20% down, price = loan / 0.8 = ~$711k
        # Let's compute: monthly payment $3600 at 6.5% 30yr
        # P = 3600 * (1 - 1.0054167^-360) / 0.0054167 = ~$569k loan
        # Price = 569k / 0.8 = ~$711k
        # But binary search may converge to slightly different value
        assert max_price > 0
        # Check that the calculated price produces a payment close to $3600
        # Reverse search targets available_for_mortgage=3600; verify the
        # max_price it found actually produces ~$3600/mo at 6.5%/30yr
        from src.mortgage_analysis import calculate_monthly_payment
        loan = max_price * 0.8
        payment = calculate_monthly_payment(loan, 0.065, 30)
        assert payment == pytest.approx(3600, abs=50)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])