import pytest
import pandas as pd
import yaml
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def sample_scenario_yaml():
    return """
    version: "1.0"
    meta:
      scenario_name: "30-Year Deterministic Plan"
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
        balance: 50000.0
        is_cash_reserve: true
        min_target_balance: 20000.0
      - id: "brokerage"
        name: "Brokerage"
        type: "taxable_brokerage"
        balance: 100000.0
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


def test_simulation_runner_dataframe_structure(sample_scenario_yaml):
    config = load_scenario_from_yaml(yaml.safe_load(sample_scenario_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 30  # 2026 to 2055 inclusive
    assert "Gross Taxable Income" in df.columns
    assert "Federal Tax" in df.columns
    assert "Net Cash Flow" in df.columns
    assert "Total Assets" in df.columns
    assert "Total Liabilities" in df.columns
    assert "Net Worth" in df.columns


def test_simulation_runner_determinism(sample_scenario_yaml):
    config = load_scenario_from_yaml(yaml.safe_load(sample_scenario_yaml))
    runner1 = SimulationRunner(config)
    df1 = runner1.run()

    runner2 = SimulationRunner(config)
    df2 = runner2.run()

    # Verify 100% deterministic identical outputs
    pd.testing.assert_frame_equal(df1, df2)


def test_net_worth_growth_and_home_purchase(sample_scenario_yaml):
    config = load_scenario_from_yaml(yaml.safe_load(sample_scenario_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # In 2026 (year 1), initial net worth should reflect accounts ($150,000) + growth + NOCF
    first_year = df.loc[2026]
    assert first_year["Total Assets"] > 150000.0

    # In 2030 (year 5), home purchase triggers asset & liability additions
    y2030 = df.loc[2030]
    assert y2030["Total Liabilities"] > 0  # Mortgage added
    # Home is booked under "Asset: Primary Home" (asset_id derived from asset_name)
    assert "Asset: Primary Home" in df.columns
    # Total Assets = accounts + 300,000 home value, so it clears 300k on the asset alone
    assert y2030["Total Assets"] > 300000.0


# Tag validation tests
def test_event_single_tag_valid():
    """An event with exactly one tag should load successfully."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Tag Test"
      start_year: 2026
      end_year: 2030
    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        tags: ["Investments"]
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    """
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    event = config.events[0]
    assert event.tags == ["Investments"]


def test_event_multiple_tags_valid():
    """An event may carry multiple tags for cross-dimensional analysis."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Multi-Tag Test"
      start_year: 2026
      end_year: 2030
    events:
      - id: "maternity"
        name: "Maternity Hospital Delivery"
        type: "cash_stream"
        category: "expense"
        start_year: 2027
        end_year: 2027
        base_amount: 4000.0
        tags: ["Healthcare", "Life Events", "Children"]
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    """
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    event = config.events[0]
    assert set(event.tags) == {"Healthcare", "Life Events", "Children"}


def test_event_tags_required():
    """An event with no tags should raise a ValidationError."""
    from pydantic import ValidationError
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "No Tag Test"
      start_year: 2026
      end_year: 2030
    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        tags: []
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    """

def test_event_empty_tags_allowed():
    """Event with empty tags is now allowed (backward compatibility)."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Empty Tag Test"
      start_year: 2026
      end_year: 2030
    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        tags: []
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    """
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    assert config.events[0].tags == []


def test_event_invalid_tag_value():
    """An event with an unrecognized tag value should raise a ValidationError."""
    from pydantic import ValidationError
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Bad Tag Test"
      start_year: 2026
      end_year: 2030
    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2030
        base_amount: 100000.0
        tags: ["NotARealTag"]
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    """
    with pytest.raises(ValidationError):
        load_scenario_from_yaml(yaml.safe_load(raw_yaml))


def test_invalid_years_validation():
    """end_year earlier than start_year should raise a ValidationError."""
    from pydantic import ValidationError
    invalid_meta = """
    version: "1.0"
    meta:
      scenario_name: "Invalid Years"
      start_year: 2050
      end_year: 2026
    macroeconomics:
      general_inflation_rate: 0.02
    tax_rules:
      federal:
        standard_deduction: 30000
        brackets:
          - limit: .inf
            rate: 0.10
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    events: []
    """
    with pytest.raises(ValidationError) as excinfo:
        load_scenario_from_yaml(yaml.safe_load(invalid_meta))
    assert "end_year (2026) cannot be earlier than start_year (2050)" in str(excinfo.value)


def test_unknown_extra_fields_forbidden():
    """Extra fields not in schema should raise ValidationError."""
    from pydantic import ValidationError
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Extra Field"
      start_year: 2026
      end_year: 2030
      unknown_field: "not_allowed"
    macroeconomics:
      general_inflation_rate: 0.02
    tax_rules:
      federal:
        standard_deduction: 30000
        brackets:
          - limit: .inf
            rate: 0.10
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 10000.0
    waterfall_strategy:
      surplus_allocation:
        - account_id: "checking"
      deficit_drawdown_order:
        - account_id: "checking"
    events: []
    """
    with pytest.raises(ValidationError):
        load_scenario_from_yaml(yaml.safe_load(raw_yaml))


def test_deficit_drawdown_reduces_account_balances():
    """Test that negative net cash flow actually draws down from accounts per waterfall strategy."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Deficit Test"
      start_year: 2026
      end_year: 2030
      tax_status: "MFJ"
    macroeconomics:
      general_inflation_rate: 0.0
      growth_rates:
        equities: 0.10
        cash_equivalents: 0.0
    tax_rules:
      federal:
        standard_deduction: 32200.0
        brackets:
          - limit: .inf
            rate: 0.0
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 100000.0
        growth_rate_ref: "cash_equivalents"
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
        end_year: 2028
        base_amount: 50000.0
        reference_year: 2026
        is_taxable_income: true
        tags: ["Investments"]
      - id: "high_expenses"
        name: "High Expenses"
        type: "cash_stream"
        category: "expense"
        start_year: 2029
        end_year: 2030
        base_amount: 150000.0
        reference_year: 2026
        tags: ["Food & Living"]
    """
    import yaml
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # In 2029-2030, net cash flow should be negative (salary stops, expenses continue)
    # Checking balance should be drawn down from 100k -> 20k min, then brokerage
    y2029 = df.loc[2029]
    y2030 = df.loc[2030]

    # Net cash flow = -150,000 expenses (no income, no tax) in both years
    assert y2029["Net Cash Flow"] == pytest.approx(-150000.0)
    assert y2030["Net Cash Flow"] == pytest.approx(-150000.0)

    # Checking drawn down to min_target_balance (20000)
    assert y2029["Account: Checking"] == pytest.approx(20000.0)
    assert y2030["Account: Checking"] == pytest.approx(20000.0)

    # 2029: brokerage grows first: 431,700 * 1.10 = 474,870
    # Deficit 150,000: checking provides 80,000 (100k - 20k min),
    #   brokerage provides the rest (70,000)
    # Brokerage = 474,870 - 70,000 = 404,870
    assert y2029["Account: Brokerage"] == pytest.approx(404870.0)

    # 2030: brokerage grows first: 404,870 * 1.10 = 445,357
    # Checking is at its min, so the full 150,000 deficit comes from brokerage
    # Brokerage = 445,357 - 150,000 = 295,357
    assert y2030["Account: Brokerage"] == pytest.approx(295357.0)


def test_deficit_drawdown_full_chain_including_retirement():
    """Test that deficit drawdown cascades through all accounts including retirement."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Full Chain Deficit Test"
      start_year: 2026
      end_year: 2030
      tax_status: "MFJ"
    macroeconomics:
      general_inflation_rate: 0.0
      growth_rates:
        equities: 0.10
        cash_equivalents: 0.0
    tax_rules:
      federal:
        standard_deduction: 32200.0
        brackets:
          - limit: .inf
            rate: 0.0
    accounts:
      - id: "checking"
        name: "Checking"
        type: "liquid"
        balance: 50000.0
        growth_rate_ref: "cash_equivalents"
        is_cash_reserve: true
        min_target_balance: 10000.0
      - id: "brokerage"
        name: "Brokerage"
        type: "taxable_brokerage"
        balance: 100000.0
        growth_rate_ref: "equities"
      - id: "retirement"
        name: "Retirement"
        type: "traditional_401k"
        balance: 200000.0
        growth_rate_ref: "equities"
    waterfall_strategy:
      surplus_allocation:
        - account_id: "brokerage"
        - account_id: "retirement"
      deficit_drawdown_order:
        - account_id: "checking"
        - account_id: "brokerage"
        - account_id: "retirement"
    events:
      - id: "salary"
        name: "Salary"
        type: "cash_stream"
        category: "income"
        start_year: 2026
        end_year: 2028
        base_amount: 50000.0
        reference_year: 2026
        is_taxable_income: true
        tags: ["Investments"]
      - id: "high_expenses"
        name: "High Expenses"
        type: "cash_stream"
        category: "expense"
        start_year: 2029
        end_year: 2030
        base_amount: 500000.0
        reference_year: 2026
        tags: ["Food & Living"]
    """
    import yaml
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    y2029 = df.loc[2029]
    y2030 = df.loc[2030]

    # Net cash flow should be negative
    assert y2029["Net Cash Flow"] < 0
    assert y2030["Net Cash Flow"] < 0

    # 2029: Checking drawn to min (10000), brokerage exhausted, retirement drawn
    # Checking: 50,000 -> 10,000 (40,000 drawn)
    # Brokerage grows first: 298,600 * 1.10 = 328,460 (fully drawn)
    # Retirement grows first: 266,200 * 1.10 = 292,820
    # Remaining deficit = 500,000 - 40,000 - 328,460 = 131,540
    # Retirement = 292,820 - 131,540 = 161,280 (no uncovered deficit in 2029)
    assert y2029["Account: Checking"] == pytest.approx(10000.0), f"Checking should be at min, got {y2029['Account: Checking']}"
    assert y2029["Account: Brokerage"] == 0.0, f"Brokerage should be zero, got {y2029['Account: Brokerage']}"
    assert y2029["Account: Retirement"] == pytest.approx(161280.0), f"Retirement should be drawn down, got {y2029['Account: Retirement']}"

    # 2030: Checking at min, brokerage zero, retirement exhausted
    # Retirement grows first: 161,280 * 1.10 = 177,408 (fully drawn)
    # Uncovered deficit = 500,000 - 177,408 = 322,592 -> booked as revolving debt
    assert y2030["Account: Checking"] == pytest.approx(10000.0)
    assert y2030["Account: Brokerage"] == 0.0
    assert y2030["Account: Retirement"] == 0.0, f"Retirement should be zero, got {y2030['Account: Retirement']}"
    assert y2030["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(322592.0)


def test_age_based_derisking():
    """Test that growth rates transition from equities to bonds based on age."""
    raw_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Derisking Test"
      start_year: 2026
      end_year: 2060
      birth_year: 1980  # Age 46 in 2026, 80 in 2060
    macroeconomics:
      general_inflation_rate: 0.0
      growth_rates:
        equities: 0.10
        bonds: 0.03
      derisking_schedule:
        equities:
          start_age: 50
          end_age: 70
          transition_to: "bonds"
    accounts:
      - id: "portfolio"
        name: "Portfolio"
        type: "taxable_brokerage"
        balance: 100000.0
        growth_rate_ref: "equities"
    waterfall_strategy:
      surplus_allocation:
        - account_id: "portfolio"
      deficit_drawdown_order:
        - account_id: "portfolio"
    events: []
    """
    import yaml
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # Check growth rate transitions
    # Age 46-50 (2026-2030): full equities rate (10%)
    # Age 50-70 (2030-2050): transitioning
    # Age 70+ (2050+): full bonds rate (3%)

    # Portfolio at age 46 (2026) should grow at 10%
    balance_2026 = df.loc[2026, "Account: Portfolio"]
    balance_2027 = df.loc[2027, "Account: Portfolio"]
    growth_2026 = (balance_2027 / balance_2026) - 1
    assert abs(growth_2026 - 0.10) < 0.001

    # Portfolio at age 80 (2060) should grow at 3%
    balance_2059 = df.loc[2059, "Account: Portfolio"]
    balance_2060 = df.loc[2060, "Account: Portfolio"]
    growth_2060 = (balance_2060 / balance_2059) - 1
    assert abs(growth_2060 - 0.03) < 0.001

    # Mid-transition (age 60, year 2040) should be between
    balance_2039 = df.loc[2039, "Account: Portfolio"]
    balance_2040 = df.loc[2040, "Account: Portfolio"]
    growth_2040 = (balance_2040 / balance_2039) - 1
    assert 0.03 < growth_2040 < 0.10


def test_uncovered_deficit_tracked_as_debt():
    """Test that when all accounts are exhausted, remaining deficit becomes debt and net worth goes negative."""
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Uncovered Deficit Test"
  start_year: 2026
  end_year: 2030
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.0
  growth_rates:
    equities: 0.0
    cash_equivalents: 0.0
tax_rules:
  federal:
    standard_deduction: 32200.0
    brackets:
      - limit: .inf
        rate: 0.0
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 50000.0
    growth_rate_ref: "cash_equivalents"
    is_cash_reserve: true
    min_target_balance: 0.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "high_expenses"
    name: "High Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2030
    base_amount: 200000.0  # Much more than the 50k checking balance
    reference_year: 2026
    tags: ["Food & Living"]
"""
    import yaml
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # In 2026: checking has 50k, expenses 200k, deficit 150k -> checking goes to 0, 150k uncovered
    y2026 = df.loc[2026]
    assert y2026["Account: Checking"] == 0.0
    assert "Debt: Uncovered Deficit (Revolving)" in df.columns
    assert y2026["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(150000.0, rel=0.01)
    assert y2026["Net Worth"] == pytest.approx(-150000.0, rel=0.01)
    assert y2026["Net Cash Flow"] == pytest.approx(-200000.0, rel=0.01)

    # In 2027: checking still 0, expenses 200k, deficit 200k -> debt increases by 200k (plus interest on existing debt)
    y2027 = df.loc[2027]
    # Debt = 150k * 1.18 + 200k = 377k
    assert y2027["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(377000.0, rel=0.01)
    assert y2027["Net Worth"] == pytest.approx(-377000.0, rel=0.01)


def test_large_house_purchase_eventual_deficit():
    """Test that a large house purchase with mortgage eventually leads to uncovered deficit when income stops.

    Scenario: $300M down payment on $550M house, $250M mortgage, $200k salary until 2050.
    The checking account is drained by the down payment, then mortgage payments eventually
    exceed income, leading to uncovered deficit debt.
    """
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Large House Purchase Test"
  start_year: 2026
  end_year: 2060
  tax_status: "MFJ"
  birth_year: 1980
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
    balance: 350000000.0
    is_cash_reserve: true
    min_target_balance: 10000000.0
  - id: "brokerage"
    name: "Brokerage"
    type: "taxable_brokerage"
    balance: 50000000.0
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
    base_amount: 200000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "living_expenses"
    name: "Living Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2060
    base_amount: 80000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]
  - id: "buy_home"
    name: "Purchase 550M Home"
    type: "asset_purchase"
    trigger_year: 2030
    down_payment: 300000000.0
    asset_name: "Primary Home"
    asset_initial_value: 550000000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    mortgage:
      principal: 250000000.0
      interest_rate: 0.06
      term_years: 30
"""
    import yaml
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # 2026: Before house purchase, positive net worth
    y2026 = df.loc[2026]
    assert y2026["Net Worth"] > 0

    # 2030: House purchased, down payment drains checking, mortgage added
    y2030 = df.loc[2030]
    assert y2030["Asset: Primary Home"] == pytest.approx(550000000.0, rel=0.01)
    assert y2030["Debt: Primary Home Mortgage"] > 0
    # Checking has 350M - 300M down payment = 50M initially, then some drawn for mortgage
    assert y2030["Account: Checking Account"] < 50000000.0
    assert y2030["Account: Checking Account"] > 10000000.0  # Not at min yet

    # 2040: Mortgage payments continue, checking and brokerage drained
    y2040 = df.loc[2040]
    assert y2040["Account: Checking Account"] <= 10000000.0  # At min target
    assert y2040["Account: Brokerage"] == 0.0
    # Uncovered deficit should start appearing
    assert "Debt: Uncovered Deficit (Revolving)" in df.columns
    assert y2040["Debt: Uncovered Deficit (Revolving)"] > 0

    # 2050: Salary ends, deficit accelerates
    y2050 = df.loc[2050]
    assert y2050["Debt: Uncovered Deficit (Revolving)"] > y2040["Debt: Uncovered Deficit (Revolving)"]

    # 2060: Net worth should be negative (debt exceeds assets)
    y2060 = df.loc[2060]
    assert y2060["Net Worth"] < 0
    assert y2060["Debt: Uncovered Deficit (Revolving)"] > 0
    # Mortgage should be paid off by 2060 (30 year term from 2030)
    assert y2060.get("Debt: Primary Home Mortgage", 0) == pytest.approx(0.0, abs=1.0)


def test_revolving_deficit_paid_down_by_surplus():
    """Surplus cash flow should repay revolving deficit debt before investing.

    Sequence (0% tax, no inflation):
    - 2026: 50k checking, 200k expense -> 150k uncovered deficit booked as debt.
    - 2027: 100k income -> interest accrues (150k * 1.18 = 177k), paydown min(100k, 177k)
            = 100k -> debt 77k, no surplus reaches checking.
    - 2028: 100k income -> interest accrues (77k * 1.18 = 90,860), paydown 90,860
            fully repays and removes the debt, remaining 9,140 goes to checking.
    """
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Revolving Debt Paydown Test"
  start_year: 2026
  end_year: 2028
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.0
tax_rules:
  federal:
    standard_deduction: 0
    brackets:
      - limit: .inf
        rate: 0.0
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 50000.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "inc"
    name: "Income"
    type: "cash_stream"
    category: "income"
    start_year: 2027
    end_year: 2028
    base_amount: 100000.0
    is_taxable_income: true
    tags: ["Investments"]
  - id: "exp"
    name: "Expense"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2026
    base_amount: 200000.0
    tags: ["Food & Living"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    # 2026: deficit creates 150k revolving debt
    y2026 = df.loc[2026]
    assert y2026["Net Cash Flow"] == pytest.approx(-200000.0)
    assert y2026["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(150000.0)
    assert y2026["Account: Checking"] == 0.0

    # 2027: 100k income, debt accrues interest to 177k, paydown 100k -> 77k, no surplus to checking
    y2027 = df.loc[2027]
    assert y2027["Net Cash Flow"] == pytest.approx(100000.0)
    assert y2027["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(77000.0)
    assert y2027["Account: Checking"] == 0.0

    # 2028: 100k income, debt accrues to 90,860, paydown fully repays, 9,140 surplus to checking
    y2028 = df.loc[2028]
    assert y2028["Net Cash Flow"] == pytest.approx(100000.0)
    assert pd.isna(y2028.get("Debt: Uncovered Deficit (Revolving)"))
    assert y2028["Account: Checking"] == pytest.approx(9140.0)


def test_non_taxable_income_counted_once_in_net_cash_flow():
    """Non-taxable income must be counted exactly once in Net Cash Flow.

    Regression: total_inflows added non_taxable_income on top of total_cash_inflow,
    even though cash_inflow already includes non-taxable amounts, doubling the surplus.
    """
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Non-Taxable Income Test"
  start_year: 2026
  end_year: 2026
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.0
tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: .inf
        rate: 0.0
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 10000.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "gift"
    name: "Gift"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2026
    base_amount: 10000.0
    is_taxable_income: false
    tags: ["Life Events"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    y2026 = df.loc[2026]
    # 10000 non-taxable income, 0 expenses, 0 tax -> NOCF = 10000 (not 20000)
    assert y2026["Gross Taxable Income"] == 0.0
    assert y2026["Net Cash Flow"] == pytest.approx(10000.0)
    # 10000 starting balance + 10000 surplus = 20000 (not 30000)
    assert y2026["Account: Checking"] == pytest.approx(20000.0)


def test_income_event_target_account_does_not_double_allocate():
    """target_account_id on an income event must not deposit twice.

    Regression: the amount was credited to the target account AND flowed through
    Net Cash Flow into surplus allocation, creating money from nothing.
    """
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Income Target Account Test"
  start_year: 2026
  end_year: 2026
  tax_status: "MFJ"
macroeconomics:
  general_inflation_rate: 0.0
tax_rules:
  federal:
    standard_deduction: 30000
    brackets:
      - limit: .inf
        rate: 0.0
accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 10000.0
  - id: "retirement"
    name: "Retirement"
    type: "traditional_401k"
    balance: 0.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "sal"
    name: "Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2026
    base_amount: 10000.0
    is_taxable_income: true
    target_account_id: "retirement"
    tags: ["Investments"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    runner = SimulationRunner(config)
    df = runner.run()

    y2026 = df.loc[2026]
    # Income flows through NOCF only; target account is untouched for income events
    assert y2026["Net Cash Flow"] == pytest.approx(10000.0)
    assert y2026["Account: Retirement"] == 0.0
    # 10000 starting + 10000 surplus = 20000
    assert y2026["Account: Checking"] == pytest.approx(20000.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])