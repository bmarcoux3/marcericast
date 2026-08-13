import pytest
import pandas as pd
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def granular_scenario_yaml():
    return """
    version: "1.0"
    meta:
      scenario_name: "Granular Output Test"
      start_year: 2026
      end_year: 2030
      tax_status: "MFJ"

    macroeconomics:
      general_inflation_rate: 0.02

    tax_rules:
      inflate_brackets: true
      federal:
        standard_deduction: 30000
        brackets:
          - limit: 50000
            rate: 0.10

    accounts:
      - id: "checking"
        name: "Checking Account"
        type: "liquid"
        balance: 10000.0

    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"

    events:
      - id: "salary"
        name: "Software Engineer Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        is_taxable_income: true
        tags: ["Investments"]
      - id: "rent"
        name: "Apartment Rent"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2030
        base_amount: 24000.0
        tags: ["Housing"]
      """


def test_granular_columns_presence_and_order(granular_scenario_yaml):
    config = load_scenario_from_yaml(granular_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    cols = list(df.columns)

    # Core Summary Metrics at start
    assert cols[0] == "Gross Taxable Income"
    assert cols[1] == "Pre-tax Deductions"
    assert cols[2] == "AGI"
    assert cols[3] == "Net Cash Flow"

    # Accounts, Assets, Debts section
    assert "Account: Checking Account" in cols

    # Granular Tax Details section
    assert "Tax: Standard Deduction" in cols
    assert "Tax: Taxable Income" in cols

    # Federal Tax now negative expense (right side with other expenses)
    assert "Federal Tax" in cols
    row_2026 = df.loc[2026]
    assert row_2026["Federal Tax"] == -5000.0  # Negative for expense

    # Life Events section placed at the rightmost end
    event_cols = [c for c in cols if c.startswith("Event: ")]
    assert len(event_cols) == 2
    assert "Event: Software Engineer Salary" in event_cols
    assert "Event: Apartment Rent" in event_cols

    # Assert rightmost position - events and expenses are on the right
    assert all(cols.index(ec) > cols.index("Tax: Taxable Income") for ec in event_cols)


def test_granular_values_math_consistency(granular_scenario_yaml):
    config = load_scenario_from_yaml(granular_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    row_2026 = df.loc[2026]
    # Check Salary event impact
    assert row_2026["Event: Software Engineer Salary"] == 100000.0
    assert row_2026["Event: Apartment Rent"] == -24000.0

    # Check granular tax section
    assert row_2026["Tax: Standard Deduction"] == 30000.0
    assert row_2026["Tax: Taxable Income"] == 70000.0  # $100k AGI - $30k deduction
    # Federal tax is now negative for expense tracking
    assert row_2026["Federal Tax"] == -5000.0  # Negative for expense


@pytest.fixture
def tag_aggregate_scenario_yaml():
    return """
    version: "1.0"
    meta:
      scenario_name: "Tag Aggregate Test"
      start_year: 2026
      end_year: 2028
      tax_status: "MFJ"

    macroeconomics:
      general_inflation_rate: 0.02

    tax_rules:
      inflate_brackets: true
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

    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"

    events:
      # Income
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2028
        base_amount: 100000.0
        is_taxable_income: true
        tags: ["Investments"]

      # Housing expense
      - id: "rent"
        name: "Rent"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2028
        base_amount: 24000.0
        tags: ["Housing"]

      # Food expense
      - id: "groceries"
        name: "Groceries"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2028
        base_amount: 12000.0
        tags: ["Food & Living"]

      # Healthcare expense
      - id: "healthcare"
        name: "Healthcare"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2028
        base_amount: 5000.0
        tags: ["Healthcare"]

      # Travel expense (discretionary)
      - id: "travel"
        name: "Travel"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2028
        base_amount: 10000.0
        tags: ["Travel & Discretionary"]

      # Investment contribution (pre-tax)
      - id: "401k"
        name: "401k Contribution"
        type: "cash_stream"
        category: "expense"
        start_year: 2026
        end_year: 2028
        base_amount: 10000.0
        is_pre_tax_deduction: true
        tags: ["Investments"]
    """


def test_tag_aggregate_columns_exist(tag_aggregate_scenario_yaml):
    """Test that Tag: columns are present for all defined tags."""
    config = load_scenario_from_yaml(tag_aggregate_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    cols = list(df.columns)
    tag_cols = [c for c in cols if c.startswith("Tag: ")]

    # Should have columns for all tags used in scenario
    assert "Tag: Investments" in tag_cols
    assert "Tag: Housing" in tag_cols
    assert "Tag: Food & Living" in tag_cols
    assert "Tag: Healthcare" in tag_cols
    assert "Tag: Travel & Discretionary" in tag_cols

    # Also check tags not used in scenario still exist (but are 0)
    assert "Tag: Children" in tag_cols
    assert "Tag: Insurance" in tag_cols
    assert "Tag: Taxes" in tag_cols
    assert "Tag: Transportation" in tag_cols
    assert "Tag: Utilities" in tag_cols
    assert "Tag: Legal" in tag_cols
    assert "Tag: Life Events" in tag_cols
    assert "Tag: Pets" in tag_cols
    assert "Tag: Technology" in tag_cols


def test_tag_aggregate_values(tag_aggregate_scenario_yaml):
    """Test that tag aggregate values are calculated correctly."""
    config = load_scenario_from_yaml(tag_aggregate_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    row = df.loc[2026]

    # Investments: Salary (100k) - 401k (10k) = 90k positive
    # Note: 401k is pre-tax deduction, so it's an expense
    # Salary is income tagged Investments, 401k is expense tagged Investments
    assert row["Tag: Investments"] == 100000.0 - 10000.0  # 90000

    # Housing: Rent expense
    assert row["Tag: Housing"] == -24000.0

    # Food & Living: Groceries expense
    assert row["Tag: Food & Living"] == -12000.0

    # Healthcare: Healthcare expense
    assert row["Tag: Healthcare"] == -5000.0

    # Travel & Discretionary: Travel expense
    assert row["Tag: Travel & Discretionary"] == -10000.0

    # Unused tags should be 0
    assert row["Tag: Children"] == 0.0
    assert row["Tag: Insurance"] == 0.0
    assert row["Tag: Transportation"] == 0.0


def test_general_lifestyle_spend(tag_aggregate_scenario_yaml):
    """Test General Lifestyle Spend = all expenses except Investments and Taxes."""
    config = load_scenario_from_yaml(tag_aggregate_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    row = df.loc[2026]

    # Lifestyle spend should include: Rent (24000) + Groceries (12000) + Healthcare (5000) + Travel (10000) = 51000
    # NOT including: 401k (Investments) and Federal Tax (Taxes)
    # Federal tax: AGI = 100000 - 10000 (401k) = 90000, deduction = 30000,
    #   taxable = 60000, single bracket capped at inflated 50000 limit:
    #   tax = min(60000, 50000) * 10% = 5000
    expected_lifestyle = -51000.0  # Negative for expense
    assert row["General Lifestyle Spend"] == expected_lifestyle


def test_general_lifestyle_spend_excludes_federal_tax(tag_aggregate_scenario_yaml):
    """Verify General Lifestyle Spend does not include federal tax."""
    config = load_scenario_from_yaml(tag_aggregate_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    row = df.loc[2026]

    # Federal tax: AGI = 100000 - 10000 (401k) = 90000
    #   Taxable = 90000 - 30000 (std deduction) = 60000
    #   Single bracket capped at inflated 50000 limit (2026 is reference year):
    #   tax = min(60000, 50000) * 10% = 5000
    federal_tax = -row["Federal Tax"]
    assert federal_tax == 5000.0

    # Lifestyle spend = all expenses except Investments (401k) and Taxes
    # = Rent 24000 + Groceries 12000 + Healthcare 5000 + Travel 10000 = 51000
    assert row["General Lifestyle Spend"] == -51000.0

    # Federal tax is tracked separately in Taxes tag
    assert row["Tag: Taxes"] == -federal_tax

    # Investments tag includes both salary income and 401k expense
    # Salary: +100000, 401k: -10000 = 90000
    assert row["Tag: Investments"] == 90000.0


def test_tag_aggregate_with_asset_purchase():
    """Test that asset purchase down payments are included in tag aggregates."""
    scenario_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Asset Purchase Tag Test"
      start_year: 2026
      end_year: 2030
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
        balance: 200000.0

    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"

    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        is_taxable_income: true
        tags: ["Investments"]

      - id: "buy_home"
        name: "Buy Home"
        type: "asset_purchase"
        trigger_year: 2027
        down_payment: 300000.0
        asset_name: "Home"
        asset_initial_value: 300000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
    """
    config = load_scenario_from_yaml(scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # 2026 - no home purchase yet
    row_2026 = df.loc[2026]
    assert row_2026["Tag: Housing"] == 0.0

    # 2027 - home purchase year
    row_2027 = df.loc[2027]
    # Housing tag should include down payment (-300000)
    assert row_2027["Tag: Housing"] == -300000.0

    # Lifestyle spend should include the down payment (it's Housing, not Investments)
    assert row_2027["General Lifestyle Spend"] == -300000.0


def test_tag_aggregate_with_recurring_asset_costs():
    """Test that recurring asset costs (tax, insurance, maintenance) are tracked in tags."""
    scenario_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Asset Costs Tag Test"
      start_year: 2026
      end_year: 2028
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
        balance: 200000.0

    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"

    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2028
        base_amount: 100000.0
        is_taxable_income: true
        tags: ["Investments"]

      - id: "buy_home"
        name: "Buy Home"
        type: "asset_purchase"
        trigger_year: 2026
        down_payment: 300000.0
        asset_name: "Home"
        asset_initial_value: 300000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
        costs:
          tax: 0.01       # 1% property tax
          insurance: 0.005  # 0.5% insurance
          maintenance: 0.01 # 1% maintenance
          HOA: 0.002      # 0.2% HOA
    """
    config = load_scenario_from_yaml(scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # 2026 - purchase year, only down payment, no recurring costs yet
    row_2026 = df.loc[2026]
    assert row_2026["Tag: Housing"] == -300000.0  # Only down payment
    assert row_2026["Tag: Insurance"] == 0.0
    assert row_2026["General Lifestyle Spend"] == -300000.0

    # 2027 - first full year with recurring costs
    row_2027 = df.loc[2027]
    # Asset value grew by 3%: 300000 * 1.03 = 309000
    # tax: 309000 * 0.01 = 3090
    # insurance: 309000 * 0.005 = 1545
    # maintenance: 309000 * 0.01 = 3090
    # HOA: 309000 * 0.002 = 618
    # Total recurring = 8343

    # Housing tag: tax (3090) + maintenance (3090) + HOA (618) = 6798
    assert row_2027["Tag: Housing"] == -6798.0

    # Insurance tag: insurance (1545)
    assert row_2027["Tag: Insurance"] == -1545.0

    # Lifestyle spend should include ALL recurring costs (none are Investments or Taxes)
    assert row_2027["General Lifestyle Spend"] == -8343.0
