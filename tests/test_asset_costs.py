import pytest
import pandas as pd
import yaml
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def asset_cost_scenario_yaml():
    """Scenario with asset purchase that has recurring costs."""
    return """
version: "1.0"
meta:
  scenario_name: "Asset Cost Test"
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
    balance: 500000.0
    is_cash_reserve: true
    min_target_balance: 10000.0

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
    down_payment: 500000.0
    asset_name: "Primary Home"
    asset_initial_value: 500000.0
    growth_rate_ref: "real_estate"
    tags: ["Housing"]
    costs:
      maintenance: 0.01      # 1% = $5,000/year (of initial value)
      property_tax: 0.015    # 1.5% = $7,500/year (of initial value)
      insurance: 0.005       # 0.5% = $2,500/year (of initial value)
"""


def test_asset_costs_recur_annually_after_purchase(asset_cost_scenario_yaml):
    """Asset costs should recur annually from year after purchase until end of simulation.

    Costs are calculated as percentage of current asset value (which grows at growth_rate).
    """
    config = load_scenario_from_yaml(asset_cost_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # Purchase happens in 2030, costs start in 2031
    # Check 2030 (purchase year) - only down payment, no recurring costs yet
    row_2030 = df.loc[2030]
    assert "Event: Buy Home" in df.columns
    assert row_2030["Event: Buy Home"] == -500000.0  # Down payment is negative

    # Check 2031 - first year of recurring costs
    row_2031 = df.loc[2031]
    # Should have columns for each cost type
    assert "Primary Home_maintenance" in df.columns
    assert "Primary Home_property_tax" in df.columns
    assert "Primary Home_insurance" in df.columns

    # Costs should be negative (expenses)
    assert row_2031["Primary Home_maintenance"] < 0
    assert row_2031["Primary Home_property_tax"] < 0
    assert row_2031["Primary Home_insurance"] < 0

    # Verify amounts: percentage * asset_value (asset already grows at growth_rate)
    # Asset value in 2031 = 500000 * (1.03)^1 = 515000
    # Maintenance: 1% * 515000 = 5150
    asset_value_2031 = 500000 * 1.03  # 515000
    expected_maintenance = -0.01 * asset_value_2031
    expected_tax = -0.015 * asset_value_2031
    expected_insurance = -0.005 * asset_value_2031

    assert row_2031["Primary Home_maintenance"] == pytest.approx(expected_maintenance)
    assert row_2031["Primary Home_property_tax"] == pytest.approx(expected_tax)
    assert row_2031["Primary Home_insurance"] == pytest.approx(expected_insurance)


def test_asset_costs_recur_every_year(asset_cost_scenario_yaml):
    """Asset costs should recur every year after purchase, growing with asset value."""
    config = load_scenario_from_yaml(asset_cost_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # Check multiple years after purchase
    for year in [2031, 2032, 2033, 2035, 2040]:
        row = df.loc[year]
        # Costs should exist and be negative
        assert row["Primary Home_maintenance"] < 0, f"Year {year} missing maintenance"
        assert row["Primary Home_property_tax"] < 0, f"Year {year} missing property_tax"
        assert row["Primary Home_insurance"] < 0, f"Year {year} missing insurance"

        # Amounts should grow with asset value (3%)
        years_since_purchase = year - 2030
        asset_value = 500000 * (1.03 ** years_since_purchase)
        expected_maintenance = -0.01 * asset_value
        assert row["Primary Home_maintenance"] == pytest.approx(expected_maintenance), f"Year {year}"


def test_asset_costs_are_negative_expenses(asset_cost_scenario_yaml):
    """Asset costs should be negative (expenses), not positive."""
    config = load_scenario_from_yaml(asset_cost_scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    row_2031 = df.loc[2031]
    # All costs should be negative (expenses reduce cash flow)
    assert row_2031["Primary Home_maintenance"] < 0
    assert row_2031["Primary Home_property_tax"] < 0
    assert row_2031["Primary Home_insurance"] < 0

    # Total cost should be sum of individual costs
    total_cost = row_2031["Primary Home_maintenance"] + row_2031["Primary Home_property_tax"] + row_2031["Primary Home_insurance"]
    assert total_cost < 0


def test_asset_costs_stop_after_liquidation(asset_cost_scenario_yaml):
    """Asset costs should stop after the asset is liquidated."""
    # Modify scenario to include asset liquidation in 2035
    scenario_dict = yaml.safe_load(asset_cost_scenario_yaml)
    scenario_dict['events'].append({
        "id": "sell_home",
        "name": "Sell Home",
        "type": "asset_liquidation",
        "trigger_year": 2035,
        "asset_name": "Primary Home",
        "tags": ["Housing"]
    })
    config = load_scenario_from_yaml(scenario_dict)
    runner = SimulationRunner(config)
    df = runner.run()

    # Costs should exist from 2031 to 2035 (year of sale)
    for year in range(2031, 2036):
        row = df.loc[year]
        assert row["Primary Home_maintenance"] < 0, f"Year {year} should have maintenance cost"
        assert row["Primary Home_property_tax"] < 0, f"Year {year} should have property tax"
        assert row["Primary Home_insurance"] < 0, f"Year {year} should have insurance"

    # Costs should NOT exist after 2035 (asset no longer exists)
    for year in range(2036, 2041):
        row = df.loc[year]
        # Costs are NaN (column exists but no value for this year) - treat as 0
        assert pd.isna(row["Primary Home_maintenance"]) or row["Primary Home_maintenance"] == 0, f"Year {year} should NOT have maintenance cost"
        assert pd.isna(row["Primary Home_property_tax"]) or row["Primary Home_property_tax"] == 0, f"Year {year} should NOT have property tax"
        assert pd.isna(row["Primary Home_insurance"]) or row["Primary Home_insurance"] == 0, f"Year {year} should NOT have insurance"

    # Asset should be removed after liquidation
    for year in range(2036, 2041):
        row = df.loc[year]
        asset_val = row.get("Asset: Primary Home", 0)
        assert pd.isna(asset_val) or asset_val == 0, f"Year {year} should not have Primary Home asset"