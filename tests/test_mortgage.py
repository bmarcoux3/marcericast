import pytest
import pandas as pd
import yaml
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def mortgage_scenario_yaml():
    """Scenario with a mortgage to test payment handling."""
    return """
version: "1.0"
meta:
  scenario_name: "Mortgage Test"
  start_year: 2026
  end_year: 2055
  tax_status: "MFJ"

macroeconomics:
  general_inflation_rate: 0.025
  growth_rates:
    equities: 0.07
    real_estate: 0.03

tax_rules:
  federal:
    standard_deduction: 32200
    brackets:
      - limit: 24800
        rate: 0.10
      - limit: 100800
        rate: 0.12
      - limit: 211400
        rate: 0.22
      - limit: .inf
        rate: 0.24

accounts:
  - id: "checking"
    name: "Checking Account"
    type: "liquid"
    balance: 100000.0
    is_cash_reserve: true
    min_target_balance: 20000.0
  - id: "brokerage"
    name: "Brokerage"
    type: "taxable_brokerage"
    balance: 200000.0
    growth_rate_ref: "equities"

waterfall_strategy:
  surplus_allocation:
    - account_id: "brokerage"
  deficit_drawdown_order:
    - account_id: "checking"
    - account_id: "brokerage"

events:
  - id: "salary"
    name: "Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2050
    base_amount: 150000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "living_expenses"
    name: "Living Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2055
    base_amount: 60000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]
  - id: "buy_home"
    name: "Purchase Home"
    type: "asset_purchase"
    trigger_year: 2030
    down_payment: 60000.0
    asset_name: "Primary Home"
    asset_initial_value: 300000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    mortgage:
      principal: 240000.0
      interest_rate: 0.06
      term_years: 30
"""


class TestMortgagePayments:
    """Test mortgage amortization and payment handling."""

    def test_mortgage_principal_decreases_annually(self, mortgage_scenario_yaml):
        """Mortgage principal should decrease each year after purchase."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # Get mortgage principal for years after purchase
        mortgage_2030 = df.loc[2030, "Debt: Primary Home Mortgage"]
        mortgage_2031 = df.loc[2031, "Debt: Primary Home Mortgage"]
        mortgage_2032 = df.loc[2032, "Debt: Primary Home Mortgage"]
        mortgage_2035 = df.loc[2035, "Debt: Primary Home Mortgage"]

        # Principal should decrease each year
        assert mortgage_2031 < mortgage_2030, "Mortgage should decrease from 2030 to 2031"
        assert mortgage_2032 < mortgage_2031, "Mortgage should decrease from 2031 to 2032"
        assert mortgage_2035 < mortgage_2032, "Mortgage should continue decreasing"

    def test_mortgage_payment_columns_exist(self, mortgage_scenario_yaml):
        """Mortgage payment columns should be present in output."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # Check mortgage payment column exists (single column, no interest/principal split)
        assert "Mortgage Payment: Primary Home Mortgage" in df.columns
        # Interest/Principal breakdowns are no longer output (per user request)
        assert "Mortgage Interest: Primary Home Mortgage" not in df.columns
        assert "Mortgage Principal: Primary Home Mortgage" not in df.columns

    def test_mortgage_payments_are_negative_expenses(self, mortgage_scenario_yaml):
        """Mortgage payments should be negative (expenses)."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        payment_2031 = df.loc[2031, "Mortgage Payment: Primary Home Mortgage"]
        assert payment_2031 < 0, "Total mortgage payment should be negative"

    def test_mortgage_payment_splits_correctly(self, mortgage_scenario_yaml):
        """Mortgage payment should equal interest + principal (verified via debt reduction)."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # Since we no longer output interest/principal breakdown, verify via debt reduction
        # Payment = interest + principal, so debt reduction = principal portion
        debt_2030 = df.loc[2030, "Debt: Primary Home Mortgage"]
        debt_2031 = df.loc[2031, "Debt: Primary Home Mortgage"]
        payment_2031 = df.loc[2031, "Mortgage Payment: Primary Home Mortgage"]

        # Principal paid = debt reduction
        principal_paid = debt_2030 - debt_2031
        # Interest = payment - principal
        interest_paid = abs(payment_2031) - principal_paid
        # Interest should equal beginning balance * rate
        expected_interest = debt_2030 * 0.06
        assert interest_paid == pytest.approx(expected_interest, rel=0.01)

    def test_mortgage_interest_calculated_correctly(self, mortgage_scenario_yaml):
        """Interest portion should equal principal * rate (verified via debt reduction)."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # 2030: first payment year (mortgage created and payment made in same year)
        # Principal is 240000, rate 6%
        debt_2030 = df.loc[2030, "Debt: Primary Home Mortgage"]
        payment_2030 = df.loc[2030, "Mortgage Payment: Primary Home Mortgage"]
        principal_paid_2030 = 240000 - debt_2030
        interest_paid_2030 = abs(payment_2030) - principal_paid_2030
        expected_interest_2030 = 240000 * 0.06
        assert interest_paid_2030 == pytest.approx(expected_interest_2030, rel=0.01)

        # 2031: principal reduced after 2030 payment
        debt_2030_val = df.loc[2030, "Debt: Primary Home Mortgage"]
        debt_2031_val = df.loc[2031, "Debt: Primary Home Mortgage"]
        payment_2031 = df.loc[2031, "Mortgage Payment: Primary Home Mortgage"]
        principal_paid_2031 = debt_2030_val - debt_2031_val
        interest_paid_2031 = abs(payment_2031) - principal_paid_2031
        expected_interest_2031 = debt_2030_val * 0.06
        assert interest_paid_2031 == pytest.approx(expected_interest_2031, rel=0.01)

    def test_mortgage_payment_affects_net_cash_flow(self, mortgage_scenario_yaml):
        """Mortgage payments should reduce net cash flow."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # Check that net cash flow includes mortgage payment
        # Net cash flow = salary - living_expenses - mortgage_payment - tax (approx)
        net_cf_2031 = df.loc[2031, "Net Cash Flow"]
        salary_2031 = df.loc[2031, "Event: Salary"]
        living_2031 = df.loc[2031, "Event: Living Expenses"]
        mortgage_pmt_2031 = df.loc[2031, "Mortgage Payment: Primary Home Mortgage"]

        # Net CF should be less than salary - living_expenses due to mortgage
        available_before_mortgage = salary_2031 + living_2031  # living is negative
        assert net_cf_2031 < available_before_mortgage, "Net CF should include mortgage payment"

    def test_mortgage_paid_off_by_term_end(self, mortgage_scenario_yaml):
        """Mortgage should be fully paid off by end of term."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # 30-year mortgage starting 2030 should be paid off by 2060
        # Our simulation ends 2055, so check it's decreasing toward zero
        final_mortgage = df.loc[2055, "Debt: Primary Home Mortgage"]
        assert final_mortgage < 100000, "Mortgage should be significantly paid down by 2055"

    def test_no_mortgage_payment_before_purchase(self, mortgage_scenario_yaml):
        """No mortgage payments before home purchase year."""
        config = load_scenario_from_yaml(mortgage_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        for year in range(2026, 2030):
            assert pd.isna(df.loc[year, "Debt: Primary Home Mortgage"])
            assert pd.isna(df.loc[year, "Mortgage Payment: Primary Home Mortgage"])

    def test_mortgage_payment_stops_after_liquidation(self, mortgage_scenario_yaml):
        """Mortgage payments stop when asset is liquidated - mortgage paid off in sale year."""
        # Add liquidation event by parsing YAML string and modifying
        import yaml
        scenario_dict = yaml.safe_load(mortgage_scenario_yaml)
        scenario_dict['events'].append({
            "id": "sell_home",
            "name": "Sell Home",
            "type": "asset_liquidation",
            "trigger_year": 2040,
            "asset_name": "Primary Home",
            "tags": ["Housing"]
        })
        config = load_scenario_from_yaml(scenario_dict)
        runner = SimulationRunner(config)
        df = runner.run()

        # In 2040 (sale year), mortgage is paid off during liquidation
        # So it should be removed (NaN) since asset was sold
        assert pd.isna(df.loc[2040, "Debt: Primary Home Mortgage"])
        # Mortgage payment should not exist in 2040 since it was paid off
        assert pd.isna(df.loc[2040, "Mortgage Payment: Primary Home Mortgage"])
        # After 2040, no mortgage
        assert pd.isna(df.loc[2041, "Debt: Primary Home Mortgage"])
        assert pd.isna(df.loc[2041, "Mortgage Payment: Primary Home Mortgage"])