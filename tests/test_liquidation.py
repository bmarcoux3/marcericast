import pytest
import pandas as pd
import yaml
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def liquidation_scenario_yaml():
    """Scenario with asset purchase and liquidation to test cash flow handling."""
    return """
version: "1.0"
meta:
  scenario_name: "Liquidation Test"
  start_year: 2026
  end_year: 2040
  tax_status: "MFJ"

macroeconomics:
  general_inflation_rate: 0.02
  growth_rates:
    real_estate: 0.03

tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: 50000
        rate: 0.10

accounts:
  - id: "checking"
    name: "Checking Account"
    type: "liquid"
    balance: 100000.0
    is_cash_reserve: true
    min_target_balance: 10000.0
  - id: "brokerage"
    name: "Brokerage"
    type: "taxable_brokerage"
    balance: 50000.0
    growth_rate_ref: "real_estate"

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
    end_year: 2040
    base_amount: 100000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "buy_home"
    name: "Buy Home"
    type: "asset_purchase"
    trigger_year: 2030
    down_payment: 50000.0
    asset_name: "Primary Home"
    asset_initial_value: 400000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    costs:
      maintenance: 0.01
    mortgage:
      principal: 350000.0
      interest_rate: 0.06
      term_years: 30
  - id: "sell_home"
    name: "Sell Home"
    type: "asset_liquidation"
    trigger_year: 2035
    asset_name: "Primary Home"
    tags: ["Housing"]
"""


class TestAssetLiquidationCashFlow:
    """Test that asset liquidation properly handles cash flow through waterfall."""

    def test_liquidation_calculates_net_proceeds(self, liquidation_scenario_yaml):
        """Net proceeds = sale_price - mortgage_principal."""
        config = load_scenario_from_yaml(liquidation_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # In 2034 (before sale):
        # Asset value = 400000 * 1.03^4 = 450,203.52
        # Mortgage principal after 4 payments = 325,043.92
        row_2034 = df.loc[2034]
        expected_asset_2034 = 450203.52
        expected_mortgage_2034 = 325043.92
        assert row_2034["Asset: Primary Home"] == pytest.approx(expected_asset_2034, rel=0.01)
        assert row_2034["Debt: Primary Home Mortgage"] == pytest.approx(expected_mortgage_2034, rel=0.01)

        # In 2035 (sale year):
        # Asset grows first: 450,203.52 * 1.03 = 463,709.63
        # Net proceeds = 463,709.63 - 325,043.92 = 138,665.71
        # Mortgage and asset should be removed
        row_2035 = df.loc[2035]
        assert pd.isna(row_2035.get("Debt: Primary Home Mortgage", pd.NA)), "Mortgage should be paid off"
        assert pd.isna(row_2035.get("Asset: Primary Home", pd.NA)), "Asset should be removed"

    def test_liquidation_net_proceeds_enter_cash_flow(self, liquidation_scenario_yaml):
        """Net proceeds should be reflected in net cash flow via waterfall."""
        config = load_scenario_from_yaml(liquidation_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        sale_year = 2035
        row = df.loc[sale_year]

        # Cash inflows: salary (119,509.26) + net proceeds (138,665.71) = 258,174.97
        # Outflows: maintenance (4,637.10) - only maintenance cost in fixture
        # Tax: 5,975.46
        #   Gross taxable = salary 119,509.26 + capital gain 63,709.63 = 183,218.89
        #   Taxable = 183,218.89 - 30,000 std deduction = 153,218.89
        #   Bracket limit inflated to 2035: 50,000 * 1.02^9 = 59,754.65
        #   Single bracket, so tax = min(153,218.89, 59,754.65) * 10% = 5,975.46
        # Net CF = 258,174.97 - 4,637.10 - 5,975.46 = 247,562.41
        expected_net_cf = 247562.41
        net_cf = row["Net Cash Flow"]
        assert net_cf == pytest.approx(expected_net_cf, rel=0.01)

    def test_liquidation_capital_gain_taxable(self, liquidation_scenario_yaml):
        """Capital gain from liquidation should be taxable income."""
        config = load_scenario_from_yaml(liquidation_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        sale_year = 2035
        row = df.loc[sale_year]

        # Capital gain = sale_price - cost_basis = 463,709.63 - 400,000 = 63,709.63
        # Gross taxable income = salary + capital_gain
        # Salary = 100000 * 1.02^9 = 119,509.26
        # Expected gross = 119,509.26 + 63,709.63 = 183,218.89
        assert row["Gross Taxable Income"] == pytest.approx(183218.89, rel=0.01)

    def test_liquidation_primary_residence_exclusion(self, liquidation_scenario_yaml):
        """Primary-residence gain exclusion should reduce taxable capital gains."""
        import yaml
        scenario_dict = yaml.safe_load(liquidation_scenario_yaml)
        for ev in scenario_dict['events']:
            if ev.get('id') == 'sell_home':
                ev['primary_residence_exclusion'] = 500000.0  # Fully covers the 63,709.63 gain
        config = load_scenario_from_yaml(scenario_dict)
        runner = SimulationRunner(config)
        df = runner.run()

        row = df.loc[2035]
        # Gain fully excluded -> gross taxable income is salary only (119,509.26)
        assert row["Gross Taxable Income"] == pytest.approx(119509.26, rel=0.01)

    def test_liquidation_primary_residence_exclusion_partial(self, liquidation_scenario_yaml):
        """Partial exclusion should only shield gains up to the exclusion amount."""
        import yaml
        scenario_dict = yaml.safe_load(liquidation_scenario_yaml)
        for ev in scenario_dict['events']:
            if ev.get('id') == 'sell_home':
                ev['primary_residence_exclusion'] = 25000.0
        config = load_scenario_from_yaml(scenario_dict)
        runner = SimulationRunner(config)
        df = runner.run()

        row = df.loc[2035]
        # Taxable gain = 63,709.63 - 25,000 = 38,709.63; gross = 119,509.26 + 38,709.63
        assert row["Gross Taxable Income"] == pytest.approx(158218.89, rel=0.01)

    def test_liquidation_respects_waterfall(self, liquidation_scenario_yaml):
        """Net proceeds should flow through waterfall to surplus allocation accounts."""
        config = load_scenario_from_yaml(liquidation_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        sale_year = 2035
        row = df.loc[sale_year]

        # Brokerage 2034 = cumulative surplus 2026-2034 (each year's surplus
        #   = salary 100000*1.02^n - maintenance - mortgage payment - tax, all
        #   routed to brokerage via surplus_allocation, growing 3%/yr).
        row_2034 = df.loc[2034]
        assert row_2034["Account: Brokerage"] == pytest.approx(897924.89, rel=0.01)

        brokerage_balance = row["Account: Brokerage"]
        # 2035: brokerage grows first (step 1), then waterfall adds the sale-year NOCF:
        #   897,924.89 * 1.03 = 924,862.64
        #   + NOCF 247,562.41 (= salary 119,509.26 + sale proceeds 138,665.71
        #      - maintenance 4,637.10 - tax 5,975.46)
        #   = 1,172,425.05
        assert brokerage_balance == pytest.approx(897924.89 * 1.03 + 247562.41, rel=0.01)

    def test_liquidation_with_custom_sale_price(self, liquidation_scenario_yaml):
        """Custom sale price should override asset value."""
        import yaml
        scenario_dict = yaml.safe_load(liquidation_scenario_yaml)
        # Remove the original sell_home event so the custom sale price is actually used
        scenario_dict['events'] = [
            ev for ev in scenario_dict['events'] if ev.get('id') != 'sell_home'
        ]
        scenario_dict['events'].append({
            "id": "sell_home_custom",
            "name": "Sell Home Custom",
            "type": "asset_liquidation",
            "trigger_year": 2035,
            "asset_name": "Primary Home",
            "sale_price": 500000.0,  # Custom price
            "tags": ["Housing"]
        })
        config = load_scenario_from_yaml(scenario_dict)
        runner = SimulationRunner(config)
        df = runner.run()

        sale_year = 2035
        row = df.loc[sale_year]

        # Custom sale_price=500000 is used directly (no growth applied to it).
        # Capital gain = 500,000 - 400,000 (cost basis) = 100,000
        # Salary (inflated 9 yrs @2%) = 100000 * 1.02^9 = 119,509.26
        # Gross taxable income = 119,509.26 + 100,000 = 219,509.26
        assert row["Gross Taxable Income"] == pytest.approx(219509.26, rel=0.01)

        # Sell event = sale_price - mortgage balance (325,043.92 = end-2034 balance,
        #   sale runs before the 2035 mortgage payment).
        # = 500,000 - 325,043.92 = 174,956.08
        assert row["Event: Sell Home Custom"] == pytest.approx(174956.08, rel=0.01)

        # Net CF = salary 119,509.26 + proceeds 174,956.08 - maintenance 4,637.10
        #        - tax 5,975.46 = 283,852.78
        # (tax is unchanged: taxable = 219,509.26 - 30,000 = 189,509.26, still
        #  capped by the inflated single bracket 59,754.65 * 10% = 5,975.46)
        assert row["Net Cash Flow"] == pytest.approx(283852.78, rel=0.01)

    def test_liquidation_mortgage_paid_off(self, liquidation_scenario_yaml):
        """Outstanding mortgage should be paid off from sale proceeds."""
        config = load_scenario_from_yaml(liquidation_scenario_yaml)
        runner = SimulationRunner(config)
        df = runner.run()

        # Before sale
        row_2034 = df.loc[2034]
        mortgage_2034 = row_2034.get("Debt: Primary Home Mortgage", 0)
        assert mortgage_2034 == pytest.approx(325043.92, rel=0.01)

        # Sale year - mortgage paid off
        row_2035 = df.loc[2035]
        assert pd.isna(row_2035.get("Debt: Primary Home Mortgage", pd.NA)), "Mortgage should be removed"

        # After sale - no mortgage
        row_2036 = df.loc[2036]
        assert pd.isna(row_2036.get("Debt: Primary Home Mortgage", pd.NA)), "Mortgage should stay removed"

    def test_liquidation_no_mortgage(self):
        """Liquidation without mortgage should transfer full value."""
        scenario = """
version: "1.0"
meta:
  scenario_name: "No Mortgage Liquidation"
  start_year: 2026
  end_year: 2035
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.02
  growth_rates:
    real_estate: 0.05
tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: 50000
        rate: 0.10
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 150000.0
    is_cash_reserve: true
    min_target_balance: 5000.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "buy_asset"
    name: "Buy Asset"
    type: "asset_purchase"
    trigger_year: 2028
    down_payment: 100000.0
    asset_name: "Investment Property"
    asset_initial_value: 100000.0
    growth_rate_ref: "real_estate"
    tags: ["Investments"]
  - id: "sell_asset"
    name: "Sell Asset"
    type: "asset_liquidation"
    trigger_year: 2033
    asset_name: "Investment Property"
    tags: ["Investments"]
"""
        config = load_scenario_from_yaml(scenario)
        runner = SimulationRunner(config)
        df = runner.run()

        # Sale price = 127,628.16 (asset value after growth in 2033)
        # Capital gain = 127,628.16 - 100,000 = 27,628.16
        # Taxable income = 27,628.16 - 34,460.57 (inflated std ded) = 0 (under deduction)
        # Tax = 0
        # Net proceeds = 127,628.16 (no mortgage)
        # Net CF = net proceeds = 127,628.16
        row = df.loc[2033]
        expected_net_cf = 127628.16
        assert row["Net Cash Flow"] == pytest.approx(expected_net_cf, rel=0.01)

        # Event: Sell Asset should show net proceeds
        assert row["Event: Sell Asset"] == pytest.approx(127628.16, rel=0.01)

        # Asset should be removed after sale
        assert pd.isna(row.get("Asset: Investment Property", pd.NA))

    def test_liquidation_mortgage_exceeds_value(self):
        """If mortgage exceeds asset value, net proceeds should be negative."""
        scenario = """
version: "1.0"
meta:
  scenario_name: "Underwater Liquidation"
  start_year: 2026
  end_year: 2035
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.02
  growth_rates:
    real_estate: -0.05  # Faster depreciation
tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: 50000
        rate: 0.10
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 200000.0
    is_cash_reserve: true
    min_target_balance: 10000.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "buy_home"
    name: "Buy Home"
    type: "asset_purchase"
    trigger_year: 2028
    down_payment: 10000.0
    asset_name: "Underwater Home"
    asset_initial_value: 200000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    mortgage:
      principal: 190000.0
      interest_rate: 0.06
      term_years: 30
  - id: "sell_home"
    name: "Sell Home"
    type: "asset_liquidation"
    trigger_year: 2030  # Sell sooner before much principal paid down
    asset_name: "Underwater Home"
    tags: ["Housing"]
"""
        config = load_scenario_from_yaml(scenario)
        runner = SimulationRunner(config)
        df = runner.run()

        row = df.loc[2030]
        # 2030 (sale year): asset grows first: 190,000 * 0.95 = 180,500
        # Mortgage balance (after 2 payments, end-2029) = 185,049.22
        #   (payment = 190000 @6%/30yr = 13,803.29/yr; balance after yr2
        #    190000 - 2403.29 principal - 2547.49 principal = 185,049.22)
        # Net proceeds = 180,500 - 185,049.22 = -4,549.22
        # Negative proceeds flow into NOCF -> covered by checking via deficit drawdown
        net_cf = row["Net Cash Flow"]
        assert net_cf == pytest.approx(-4549.22, rel=0.01)

    def test_cash_flow_manual_check_asset_buy_sell(self):
        """Verify manual cash flow check matches Net Cash Flow for asset buy/sell years.

        The correct manual check is:
        Sum of ALL event columns (main + fee breakdowns)
        + recurring asset costs
        + mortgage payments
        + federal tax
        = Net Cash Flow
        """
        scenario = """
version: "1.0"
meta:
  scenario_name: "Cash Flow Verification"
  start_year: 2026
  end_year: 2035
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.02
  growth_rates:
    real_estate: 0.03
tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: 50000
        rate: 0.10
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 100000.0
    is_cash_reserve: true
    min_target_balance: 10000.0
  - id: "brokerage"
    name: "Brokerage"
    type: "taxable_brokerage"
    balance: 50000.0
    growth_rate_ref: "real_estate"
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
    end_year: 2035
    base_amount: 100000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "buy_home"
    name: "Buy Home"
    type: "asset_purchase"
    trigger_year: 2030
    down_payment: 50000.0
    asset_name: "Test Home"
    asset_initial_value: 400000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    costs:
      maintenance: 0.01
    mortgage:
      principal: 350000.0
      interest_rate: 0.06
      term_years: 30
    purchase_fees:
      closing_costs: 0.03
  - id: "sell_home"
    name: "Sell Home"
    type: "asset_liquidation"
    trigger_year: 2035
    asset_name: "Test Home"
    sale_fees:
      agent_commission: 0.06
      closing_costs: 0.02
    tags: ["Housing"]
"""
        config = load_scenario_from_yaml(scenario)
        runner = SimulationRunner(config)
        df = runner.run()

        # Test purchase year (2030)
        row_2030 = df.loc[2030]

        # ALL event columns (including fee breakdowns)
        event_cols = [c for c in df.columns if c.startswith('Event:')]
        total_events = sum(row_2030[c] for c in event_cols if pd.notna(row_2030[c]))

        # Recurring asset costs
        recurring_cols = [c for c in df.columns if 'Test Home_' in c]
        total_recurring = sum(row_2030[c] for c in recurring_cols if pd.notna(row_2030[c]))

        # Mortgage payments
        mortgage_cols = [c for c in df.columns if 'Mortgage Payment' in c]
        total_mortgage = sum(row_2030[c] for c in mortgage_cols if pd.notna(row_2030[c]))

        # Federal tax
        fed_tax = row_2030.get('Federal Tax', 0)

        # Manual check
        manual_check = total_events + total_recurring + total_mortgage + fed_tax
        net_cf = row_2030.get('Net Cash Flow', 0)

        assert abs(manual_check - net_cf) < 0.01, f"Purchase year: manual_check={manual_check}, net_cf={net_cf}"

        # Test liquidation year (2035)
        row_2035 = df.loc[2035]

        total_events = sum(row_2035[c] for c in event_cols if pd.notna(row_2035[c]))
        total_recurring = sum(row_2035[c] for c in recurring_cols if pd.notna(row_2035[c]))
        total_mortgage = sum(row_2035[c] for c in mortgage_cols if pd.notna(row_2035[c]))
        fed_tax = row_2035.get('Federal Tax', 0)

        manual_check = total_events + total_recurring + total_mortgage + fed_tax
        net_cf = row_2035.get('Net Cash Flow', 0)

        assert abs(manual_check - net_cf) < 0.01, f"Liquidation year: manual_check={manual_check}, net_cf={net_cf}"

        # Also verify fee breakdown columns exist and are negative
        fee_cols = [c for c in df.columns if c.startswith('Event:') and ' - ' in c]
        for year in [2030, 2035]:
            row = df.loc[year]
            fee_sum = sum(row[c] for c in fee_cols if pd.notna(row[c]))
            assert fee_sum <= 0, f"Year {year}: fee breakdowns should be negative (expenses)"


def test_capital_gain_taxed_at_cap_gains_brackets():
    """Capital gains are taxed at capital-gains bracket rates, separate from ordinary income.

    Regression: gains were previously folded into AGI and taxed at ordinary rates
    (the cap-gains bracket machinery was dead code). With configured capital_gains
    brackets, a $100k gain on $100k salary should produce:
    - ordinary tax = (100k salary - 30k std deduction) * 10% = 7,000
    - cap-gains tax = 10k * 0% + 90k * 15% = 13,500
    - total = 20,500 (vs. 17,000 if the gain were taxed at the ordinary 10% flat rate)
    """
    scenario = {
        'version': '1.0',
        'meta': {'scenario_name': 'Cap Gains Test', 'start_year': 2026, 'end_year': 2027, 'tax_status': 'MFJ'},
        'macroeconomics': {'general_inflation_rate': 0.0},
        'tax_rules': {
            'federal': {'standard_deduction': 30000, 'brackets': [{'limit': float('inf'), 'rate': 0.10}]},
            'capital_gains': {'brackets': [{'limit': 10000, 'rate': 0.0}, {'limit': float('inf'), 'rate': 0.15}]},
        },
        'accounts': [{'id': 'checking', 'name': 'Checking', 'type': 'liquid', 'balance': 500000.0}],
        'waterfall_strategy': {
            'surplus_allocation': [{'account_id': 'checking'}],
            'deficit_drawdown_order': [{'account_id': 'checking'}],
        },
        'events': [
            {'id': 'sal', 'name': 'Salary', 'type': 'cash_stream', 'category': 'income',
             'start_year': 2026, 'end_year': 2027, 'base_amount': 100000.0,
             'is_taxable_income': True, 'tags': ['Investments']},
            {'id': 'buy', 'name': 'Buy', 'type': 'asset_purchase', 'trigger_year': 2026,
             'down_payment': 400000.0, 'asset_name': 'Home', 'asset_initial_value': 400000.0,
             'tags': ['Housing']},
            {'id': 'sell', 'name': 'Sell', 'type': 'asset_liquidation', 'trigger_year': 2027,
             'asset_name': 'Home', 'sale_price': 500000.0, 'tags': ['Housing']},
        ],
    }
    config = load_scenario_from_yaml(scenario)
    runner = SimulationRunner(config)
    df = runner.run()

    row_2027 = df.loc[2027]
    # Gross Taxable Income still includes the gain: 100k salary + 100k gain = 200k
    assert row_2027["Gross Taxable Income"] == pytest.approx(200000.0)
    # Total federal tax = 7,000 ordinary + 13,500 cap-gains = 20,500
    assert row_2027["Federal Tax"] == pytest.approx(-20500.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])