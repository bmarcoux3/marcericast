"""Phase 6: Hand-computed spot checks for boundary/edge cases.

Every number below is derived by hand from first principles (tax brackets,
waterfall routing, capital-gains brackets) to catch silent drift in engine math.
Each scenario is deliberately tiny so the full expected balance can be stated.
"""
import pandas as pd
import pytest
import yaml

from src.engine import SimulationRunner
from src.loader import load_scenario_from_yaml


def _run(scenario: dict) -> pd.DataFrame:
    config = load_scenario_from_yaml(scenario)
    return SimulationRunner(config).run()


def _base(scenario_name: str, **overrides):
    scenario = {
        "version": "1.0",
        "meta": {"scenario_name": scenario_name, "start_year": 2026, "end_year": 2026, "tax_status": "MFJ"},
        "macroeconomics": {"general_inflation_rate": 0.0},
        "tax_rules": {
            "federal": {"standard_deduction": 0, "brackets": [{"limit": float("inf"), "rate": 0.0}]},
        },
        "accounts": [{"id": "checking", "name": "Checking", "type": "liquid", "balance": 0.0}],
        "waterfall_strategy": {
            "surplus_allocation": [{"account_id": "checking"}],
            "deficit_drawdown_order": [{"account_id": "checking"}],
        },
        "events": [],
    }
    for key, value in overrides.items():
        if key == "events":
            scenario["events"] = value
        elif key == "accounts":
            scenario["accounts"] = value
        else:
            scenario[key] = value
    return scenario


def test_tax_is_zero_when_agi_equals_standard_deduction():
    """AGI exactly equal to the standard deduction must produce $0 tax."""
    scenario = _base(
        "Zero Tax At Deduction",
        tax_rules={
            "federal": {"standard_deduction": 30000, "brackets": [{"limit": float("inf"), "rate": 0.10}]},
        },
        events=[
            {"id": "inc", "name": "Income", "type": "cash_stream", "category": "income",
             "start_year": 2026, "end_year": 2026, "base_amount": 30000.0,
             "is_taxable_income": True, "tags": ["Investments"]},
        ],
    )
    df = _run(scenario)
    row = df.loc[2026]
    assert row["Gross Taxable Income"] == pytest.approx(30000.0)
    assert row["AGI"] == pytest.approx(30000.0)
    assert row["Tax: Taxable Income"] == pytest.approx(0.0)
    assert row["Federal Tax"] == 0.0
    assert row["Net Cash Flow"] == pytest.approx(30000.0)
    assert row["Account: Checking"] == pytest.approx(30000.0)


def test_ordinary_tax_bracket_boundary_exact_and_one_dollar_over():
    """Tax at exactly a bracket limit, and one dollar into the next bracket."""
    scenario = _base(
        "Bracket Boundary",
        tax_rules={
            "federal": {"standard_deduction": 0,
                        "brackets": [{"limit": 20000, "rate": 0.10}, {"limit": float("inf"), "rate": 0.20}]},
        },
        events=[
            {"id": "inc1", "name": "Income A", "type": "cash_stream", "category": "income",
             "start_year": 2026, "end_year": 2026, "base_amount": 20000.0,
             "is_taxable_income": True, "tags": ["Investments"]},
            {"id": "inc2", "name": "Income B", "type": "cash_stream", "category": "income",
             "start_year": 2027, "end_year": 2027, "base_amount": 20001.0,
             "is_taxable_income": True, "tags": ["Investments"]},
        ],
    )
    scenario["meta"]["end_year"] = 2027
    df = _run(scenario)
    row2026 = df.loc[2026]
    row2027 = df.loc[2027]

    # 20,000 * 10% = 2,000 exactly; NOCF = 20,000 - 2,000 = 18,000
    assert row2026["Federal Tax"] == pytest.approx(-2000.0)
    assert row2026["Account: Checking"] == pytest.approx(18000.0)

    # 20,001 -> 20,000 * 10% + 1 * 20% = 2,000.20
    assert row2027["Federal Tax"] == pytest.approx(-2000.20)
    assert row2027["Account: Checking"] == pytest.approx(18000.0 + 18000.80)


def test_deficit_exactly_equal_to_available_funds():
    """A deficit equal to the full account balance drains it to exactly $0 with no debt."""
    scenario = _base(
        "Exact Deficit",
        accounts=[{"id": "checking", "name": "Checking", "type": "liquid", "balance": 100000.0}],
        events=[
            {"id": "exp", "name": "Expense", "type": "cash_stream", "category": "expense",
             "start_year": 2026, "end_year": 2026, "base_amount": 100000.0,
             "tags": ["Food & Living"]},
        ],
    )
    df = _run(scenario)
    row = df.loc[2026]
    assert row["Net Cash Flow"] == pytest.approx(-100000.0)
    assert row["Account: Checking"] == 0.0
    assert pd.isna(row.get("Debt: Uncovered Deficit (Revolving)"))
    assert row["Net Worth"] == pytest.approx(0.0)


def test_deficit_one_dollar_over_available_funds():
    """A deficit one dollar beyond the account balance creates exactly $1 of debt."""
    scenario = _base(
        "One Dollar Over",
        accounts=[{"id": "checking", "name": "Checking", "type": "liquid", "balance": 99999.0}],
        events=[
            {"id": "exp", "name": "Expense", "type": "cash_stream", "category": "expense",
             "start_year": 2026, "end_year": 2026, "base_amount": 100000.0,
             "tags": ["Food & Living"]},
        ],
    )
    df = _run(scenario)
    row = df.loc[2026]
    assert row["Net Cash Flow"] == pytest.approx(-100000.0)
    assert row["Account: Checking"] == 0.0
    assert row["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(1.0)
    assert row["Net Worth"] == pytest.approx(-1.0)


def test_zero_net_cash_flow_leaves_accounts_untouched():
    """Income exactly equal to expenses (0% tax) must not move any balance."""
    scenario = _base(
        "Zero NOCF",
        accounts=[{"id": "checking", "name": "Checking", "type": "liquid", "balance": 5000.0}],
        events=[
            {"id": "inc", "name": "Income", "type": "cash_stream", "category": "income",
             "start_year": 2026, "end_year": 2026, "base_amount": 100000.0,
             "is_taxable_income": True, "tags": ["Investments"]},
            {"id": "exp", "name": "Expense", "type": "cash_stream", "category": "expense",
             "start_year": 2026, "end_year": 2026, "base_amount": 100000.0,
             "tags": ["Food & Living"]},
        ],
    )
    df = _run(scenario)
    row = df.loc[2026]
    assert row["Net Cash Flow"] == 0.0
    assert row["Account: Checking"] == pytest.approx(5000.0)


def test_surplus_cap_hit_exactly_does_not_overflow_to_next_account():
    """Surplus exactly equal to the first account's annual cap stops there."""
    scenario = _base(
        "Exact Cap",
        accounts=[
            {"id": "checking", "name": "Checking", "type": "liquid", "balance": 10000.0},
            {"id": "brokerage", "name": "Brokerage", "type": "taxable_brokerage", "balance": 0.0},
        ],
        waterfall_strategy={
            "surplus_allocation": [
                {"account_id": "checking", "max_annual_contribution": 50000.0},
                {"account_id": "brokerage"},
            ],
            "deficit_drawdown_order": [{"account_id": "checking"}, {"account_id": "brokerage"}],
        },
        events=[
            {"id": "inc", "name": "Income", "type": "cash_stream", "category": "income",
             "start_year": 2026, "end_year": 2026, "base_amount": 50000.0,
             "is_taxable_income": True, "tags": ["Investments"]},
        ],
    )
    df = _run(scenario)
    row = df.loc[2026]
    assert row["Net Cash Flow"] == pytest.approx(50000.0)
    # 10,000 + 50,000 (exactly the cap) = 60,000; brokerage receives nothing
    assert row["Account: Checking"] == pytest.approx(60000.0)
    assert row["Account: Brokerage"] == pytest.approx(0.0)


def test_asset_sold_at_cost_basis_pays_zero_capital_gains_tax():
    """Selling at exactly cost basis produces a $0 gain and $0 cap-gains tax,
    even with a 15% cap-gains bracket configured."""
    scenario = _base(
        "Zero Gain Sale",
        accounts=[{"id": "checking", "name": "Checking", "type": "liquid", "balance": 400000.0}],
        tax_rules={
            "federal": {"standard_deduction": 0, "brackets": [{"limit": float("inf"), "rate": 0.10}]},
            "capital_gains": {"brackets": [{"limit": float("inf"), "rate": 0.15}]},
        },
        events=[
            {"id": "buy", "name": "Buy", "type": "asset_purchase", "trigger_year": 2026,
             "down_payment": 400000.0, "asset_name": "Home", "asset_initial_value": 400000.0,
             "tags": ["Housing"]},
            {"id": "sell", "name": "Sell", "type": "asset_liquidation", "trigger_year": 2027,
             "asset_name": "Home", "sale_price": 400000.0, "tags": ["Housing"]},
        ],
    )
    scenario["meta"]["end_year"] = 2027
    df = _run(scenario)
    row2027 = df.loc[2027]
    assert row2027["Gross Taxable Income"] == pytest.approx(0.0)
    assert row2027["Federal Tax"] == 0.0
    assert row2027["Net Cash Flow"] == pytest.approx(400000.0)
    assert row2027["Account: Checking"] == pytest.approx(400000.0)


def test_cap_gains_bracket_boundary_exact_and_one_dollar_over():
    """Gain exactly at the 0% cap-gains bracket limit pays no tax; one dollar
    more is taxed only on the excess."""
    scenario = _base(
        "Cap Gains Boundary",
        accounts=[{"id": "checking", "name": "Checking", "type": "liquid", "balance": 200000.0}],
        tax_rules={
            "federal": {"standard_deduction": 0, "brackets": [{"limit": float("inf"), "rate": 0.10}]},
            "capital_gains": {"brackets": [{"limit": 10000, "rate": 0.0}, {"limit": float("inf"), "rate": 0.15}]},
        },
        events=[
            # Buy A, sell at exactly +10,000 gain (0% bracket limit)
            {"id": "buy_a", "name": "Buy A", "type": "asset_purchase", "trigger_year": 2026,
             "down_payment": 100000.0, "asset_name": "Home A", "asset_initial_value": 100000.0,
             "tags": ["Housing"]},
            {"id": "sell_a", "name": "Sell A", "type": "asset_liquidation", "trigger_year": 2027,
             "asset_name": "Home A", "sale_price": 110000.0, "tags": ["Housing"]},
            # Buy B, sell at +10,001 gain (one dollar into the 15% bracket)
            {"id": "buy_b", "name": "Buy B", "type": "asset_purchase", "trigger_year": 2027,
             "down_payment": 100000.0, "asset_name": "Home B", "asset_initial_value": 100000.0,
             "tags": ["Housing"]},
            {"id": "sell_b", "name": "Sell B", "type": "asset_liquidation", "trigger_year": 2028,
             "asset_name": "Home B", "sale_price": 110001.0, "tags": ["Housing"]},
        ],
    )
    scenario["meta"]["end_year"] = 2028
    df = _run(scenario)

    # 2026: buy A -> checking 200k - 100k = 100k
    assert df.loc[2026]["Account: Checking"] == pytest.approx(100000.0)

    # 2027: sell A (+110k) then buy B (-100k). Gain 10,000 exactly at 0% limit -> no tax.
    row2027 = df.loc[2027]
    assert row2027["Gross Taxable Income"] == pytest.approx(10000.0)
    assert row2027["Federal Tax"] == 0.0
    assert row2027["Net Cash Flow"] == pytest.approx(10000.0)
    assert row2027["Account: Checking"] == pytest.approx(110000.0)

    # 2028: sell B (+110,001). Gain 10,001 -> 10,000 at 0% + 1 at 15% = 0.15 tax.
    row2028 = df.loc[2028]
    assert row2028["Gross Taxable Income"] == pytest.approx(10001.0)
    assert row2028["Federal Tax"] == pytest.approx(-0.15)
    assert row2028["Net Cash Flow"] == pytest.approx(110001.0 - 0.15)
    assert row2028["Account: Checking"] == pytest.approx(110000.0 + 110001.0 - 0.15)
