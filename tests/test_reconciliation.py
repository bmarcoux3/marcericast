"""Invariant tests: the recorded year-by-year outputs must always reconcile.

Every row of the simulation DataFrame must satisfy, for each year:

1. Balance sheet:  Total Assets = Total Account Balances + Total Assets (asset schedule)
                   Total Liabilities = sum of all Debt columns
                   Net Worth = Total Assets - Total Liabilities
2. Tax pipeline:   AGI = max(0, Gross Taxable Income - Pre-tax Deductions)
                   Taxable Income = max(0, AGI - Standard Deduction)
3. Cash flow:      Net Cash Flow = sum of every cash-movement column
                   (event columns incl. fees, recurring costs, mortgage payments,
                   Federal Tax), i.e. inflows minus outflows.

These tests run on the real generic-family scenario plus controlled
micro-scenarios where every per-account balance can be hand-computed.
"""
import pandas as pd
import pytest
import yaml
from pathlib import Path

from src.engine import SimulationRunner
from src.loader import load_scenario_from_yaml

GENERIC_SCENARIO_PATH = Path(__file__).parent / "fixtures" / "scenarios" / "generic-family.yaml"


# Columns that represent balance-sheet or derived quantities (excluded from the
# cash-flow reconciliation because they are aggregates, not cash movements).
_AGGREGATE_PREFIXES = (
    "Account: ",
    "Total ",
    "Net Worth",
    "Gross Taxable",
    "Pre-tax",
    "AGI",
    "Net Cash Flow",
    "Tax: Standard",
    "Tax: Taxable",
    "Asset: ",
    "Debt: ",
    "Tag: ",
    "General Lifestyle Spend",
)


def _sum_columns(row, prefix):
    return sum(
        value
        for column, value in row.items()
        if isinstance(column, str)
        and column.startswith(prefix)
        and pd.notna(value)
    )


def _cash_flow_columns(columns):
    return [c for c in columns if not c.startswith(_AGGREGATE_PREFIXES)]


def _assert_balance_sheet(row):
    accounts = _sum_columns(row, "Account: ")
    assets = _sum_columns(row, "Asset: ")
    debts = _sum_columns(row, "Debt: ")
    assert accounts == pytest.approx(row["Total Account Balances"])
    assert accounts + assets == pytest.approx(row["Total Assets"])
    assert debts == pytest.approx(row["Total Liabilities"])
    assert row["Total Assets"] - row["Total Liabilities"] == pytest.approx(row["Net Worth"])


def _assert_tax_pipeline(row):
    expected_agi = max(0.0, row["Gross Taxable Income"] - row["Pre-tax Deductions"])
    assert row["AGI"] == pytest.approx(expected_agi)
    expected_taxable = max(0.0, row["AGI"] - row["Tax: Standard Deduction"])
    assert row["Tax: Taxable Income"] == pytest.approx(expected_taxable)


def _assert_cash_flow_reconciliation(row, cash_columns):
    manual = sum(row[c] for c in cash_columns if pd.notna(row[c]))
    assert manual == pytest.approx(row["Net Cash Flow"])


def test_generic_family_balance_sheet_identities_every_year():
    config = load_scenario_from_yaml(GENERIC_SCENARIO_PATH)
    df = SimulationRunner(config).run()
    for year in df.index:
        _assert_balance_sheet(df.loc[year])


def test_generic_family_tax_pipeline_identities_every_year():
    config = load_scenario_from_yaml(GENERIC_SCENARIO_PATH)
    df = SimulationRunner(config).run()
    for year in df.index:
        _assert_tax_pipeline(df.loc[year])


def test_generic_family_cash_flow_reconciles_every_year():
    config = load_scenario_from_yaml(GENERIC_SCENARIO_PATH)
    df = SimulationRunner(config).run()
    cash_columns = _cash_flow_columns(df.columns)
    for year in df.index:
        _assert_cash_flow_reconciliation(df.loc[year], cash_columns)


def test_generic_family_years_advance_contiguously():
    config = load_scenario_from_yaml(GENERIC_SCENARIO_PATH)
    df = SimulationRunner(config).run()
    assert list(df.index) == list(range(config.meta.start_year, config.meta.end_year + 1))


def test_zero_growth_account_balance_delta_equals_net_cash_flow():
    """With no growth, inflation, or rebalancing, each account's balance changes
    by exactly its share of the year's net cash flow."""
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Zero Growth Reconciliation"
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
    balance: 100000.0
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
    start_year: 2026
    end_year: 2028
    base_amount: 100000.0
    is_taxable_income: true
    tags: ["Investments"]
  - id: "exp"
    name: "Expense"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 40000.0
    tags: ["Food & Living"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    df = SimulationRunner(config).run()
    cash_columns = _cash_flow_columns(df.columns)
    previous = 100000.0
    for year in df.index:
        row = df.loc[year]
        _assert_cash_flow_reconciliation(row, cash_columns)
        _assert_balance_sheet(row)
        assert row["Account: Checking"] == pytest.approx(previous + row["Net Cash Flow"])
        previous = row["Account: Checking"]


def test_capped_two_account_waterfall_reconciles_per_account():
    """Hand-computed waterfall with a capped cash-reserve account.

    checking: initial 20k, cash reserve, min 10k, max 50k, annual contribution cap 50k
    brokerage: no caps
    Income 100k/yr, 0% tax, no expenses -> NOCF 100k/yr.

    Year 1: checking + min(100k, 50k) = 50k -> 70k; brokerage + 50k -> 50k.
            rebalance moves checking above its 50k cap (20k) to brokerage
            -> checking 50k, brokerage 70k.
    Year 2: same again -> checking 50k, brokerage 170k.
    Year 3: same again -> checking 50k, brokerage 270k.
    """
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Capped Waterfall Reconciliation"
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
    balance: 20000.0
    min_target_balance: 10000.0
    max_target_balance: 50000.0
  - id: "brokerage"
    name: "Brokerage"
    type: "taxable_brokerage"
    balance: 0.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
      max_annual_contribution: 50000.0
    - account_id: "brokerage"
  deficit_drawdown_order:
    - account_id: "checking"
    - account_id: "brokerage"
events:
  - id: "inc"
    name: "Income"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2028
    base_amount: 100000.0
    is_taxable_income: true
    tags: ["Investments"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    df = SimulationRunner(config).run()
    cash_columns = _cash_flow_columns(df.columns)
    expected = {2026: (50000.0, 70000.0), 2027: (50000.0, 170000.0), 2028: (50000.0, 270000.0)}
    for year, (checking, brokerage) in expected.items():
        row = df.loc[year]
        _assert_cash_flow_reconciliation(row, cash_columns)
        _assert_balance_sheet(row)
        assert row["Net Cash Flow"] == pytest.approx(100000.0)
        assert row["Account: Checking"] == pytest.approx(checking)
        assert row["Account: Brokerage"] == pytest.approx(brokerage)


def test_uncovered_deficit_reconciles_on_balance_sheet():
    """When a deficit is left uncovered, the shortfall appears as a liability so
    Net Worth still equals Total Assets - Total Liabilities."""
    raw_yaml = """
version: "1.0"
meta:
  scenario_name: "Deficit Reconciliation"
  start_year: 2026
  end_year: 2026
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
    balance: 20000.0
waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
events:
  - id: "exp"
    name: "Expense"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2026
    base_amount: 100000.0
    tags: ["Food & Living"]
"""
    config = load_scenario_from_yaml(yaml.safe_load(raw_yaml))
    df = SimulationRunner(config).run()
    row = df.loc[2026]
    _assert_balance_sheet(row)
    assert row["Account: Checking"] == 0.0
    assert row["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(80000.0)
    assert row["Net Worth"] == pytest.approx(-80000.0)
