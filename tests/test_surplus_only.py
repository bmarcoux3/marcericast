"""Tests for surplus-gated ("waterfall") contribution streams.

When a contribution event is flagged ``surplus_only`` it no longer fires
unconditionally: it only contributes in years with true excess cash flow
(post-tax, post-consumption surplus), capped at its annual amount and funded in
``surplus_priority`` order. In deficit years the contribution is zero and is
never funded by liquidating savings. Non-gated streams keep the legacy
always-contribute (self-funded) behavior.
"""
import pytest
import pandas as pd
from src.domain_models import SimulationState, AccountState
from src.schema import CashStreamEventConfig, MacroeconomicsConfig
from src.events import CashStreamEvent
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner
from api import get_tunable_parameters


@pytest.fixture
def macro_config():
    return MacroeconomicsConfig(general_inflation_rate=0.03)


def test_gated_event_proposes_but_does_not_credit(macro_config):
    """A surplus_only stream proposes its amount but credits nothing and banks
    no pre-tax deduction until the engine funds it."""
    sim_state = SimulationState(
        current_year=2030,
        accounts={
            "retirement_pretax": AccountState(
                id="retirement_pretax", name="Pre-Tax", account_type="traditional_401k", balance=1000.0
            ),
        },
    )
    config = CashStreamEventConfig(
        id="pretax_401k",
        name="Pre-Tax 401k",
        type="cash_stream",
        category="expense",
        start_year=2020,
        end_year=2040,
        base_amount=20000.0,
        reference_year=2026,
        inflation_ref="general_inflation_rate",
        target_account_id="retirement_pretax",
        is_pre_tax_deduction=True,
        surplus_only=True,
        tags=["Investments"],
    )
    impact = CashStreamEvent(config).evaluate(sim_state, macro_config)

    # 20000 * 1.03^4 = 22510.18 proposed
    assert impact.surplus_contribution == pytest.approx(22510.18, abs=0.01)
    assert impact.contribution_transfers == 0.0
    assert impact.pre_tax_contribution == 0.0
    assert impact.post_tax_expenses == 0.0
    # Account untouched until the engine funds the contribution
    assert sim_state.accounts["retirement_pretax"].balance == 1000.0


def test_gated_event_respects_gap_years(macro_config):
    sim_state = SimulationState(
        current_year=2030,
        accounts={"retirement_pretax": AccountState(
            id="retirement_pretax", name="Pre-Tax", account_type="traditional_401k", balance=0.0
        )},
    )
    config = CashStreamEventConfig(
        id="pretax_401k",
        name="Pre-Tax 401k",
        type="cash_stream",
        category="expense",
        start_year=2020,
        end_year=2040,
        base_amount=20000.0,
        gap_years=[2030],
        target_account_id="retirement_pretax",
        is_pre_tax_deduction=True,
        surplus_only=True,
        tags=["Investments"],
    )
    impact = CashStreamEvent(config).evaluate(sim_state, macro_config)
    assert impact.surplus_contribution == 0.0


SURPLUS_SCENARIO = """
version: "1.0"
meta:
  scenario_name: "Surplus-Gated Priority Test"
  start_year: 2026
  end_year: 2028
  tax_status: "MFJ"

macroeconomics:
  general_inflation_rate: 0.0
  growth_rates:
    equities: 0.0

tax_rules:
  federal:
    standard_deduction: 0
    brackets:
      - limit: 1000000000
        rate: 0.1

accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 0.0
  - id: "retirement_pretax"
    name: "Retirement Pre-Tax"
    type: "traditional_401k"
    balance: 0.0
  - id: "retirement_roth"
    name: "Roth IRA"
    type: "roth_ira"
    balance: 0.0
  - id: "college_529"
    name: "College 529"
    type: "taxable_brokerage"
    balance: 0.0

waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
    - account_id: "retirement_pretax"
    - account_id: "retirement_roth"
    - account_id: "college_529"

events:
  - id: "salary"
    name: "Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2028
    base_amount: 100000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "pretax_401k"
    name: "Pre-Tax 401k"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 24500.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    target_account_id: "retirement_pretax"
    is_pre_tax_deduction: true
    surplus_only: true
    surplus_priority: 10
    tags: ["Investments"]
  - id: "mbr"
    name: "Mega Backdoor Roth"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 30000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    target_account_id: "retirement_roth"
    surplus_only: true
    surplus_priority: 20
    tags: ["Investments"]
  - id: "college"
    name: "College 529"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 10000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    target_account_id: "college_529"
    surplus_only: true
    surplus_priority: 30
    tags: ["Investments", "Children"]
"""


def test_surplus_scenario_funds_streams_in_priority_order():
    """$100k salary, 10% flat tax, no consumption: surplus fully funds all three
    streams. Pre-tax contribution reduces AGI (tax 7,550 not 10,000); remaining
    surplus spills to checking. Repeats identically each year."""
    config = load_scenario_from_yaml(SURPLUS_SCENARIO)
    df = SimulationRunner(config).run()

    for offset, year in enumerate((2026, 2027, 2028)):
        row = df.loc[year]
        assert row["Retirement Contribution Transfers"] == pytest.approx(-54500.0)  # pre-tax + MBR
        assert row["Investment Contribution Transfers"] == pytest.approx(-64500.0)  # all three
        assert row["Federal Tax"] == pytest.approx(-7550.0)
        assert row["Net Cash Flow"] == pytest.approx(92450.0)
        # Balances accumulate year over year
        assert row["Account: Retirement Pre-Tax"] == pytest.approx(24500.0 * (offset + 1))
        assert row["Account: Roth IRA"] == pytest.approx(30000.0 * (offset + 1))
        assert row["Account: College 529"] == pytest.approx(10000.0 * (offset + 1))
        assert row["Account: Checking"] == pytest.approx((92450.0 - 64500.0) * (offset + 1))
        # Per-stream columns confirm what was actually funded that year
        assert row["Contribution: Pre-Tax 401k"] == pytest.approx(-24500.0)
        assert row["Contribution: Mega Backdoor Roth"] == pytest.approx(-30000.0)
        assert row["Contribution: College 529"] == pytest.approx(-10000.0)


DEFICIT_SCENARIO = """
version: "1.0"
meta:
  scenario_name: "Surplus-Gated Deficit Test"
  start_year: 2026
  end_year: 2028
  tax_status: "MFJ"

macroeconomics:
  general_inflation_rate: 0.0
  growth_rates:
    equities: 0.0

tax_rules:
  federal:
    standard_deduction: 0
    brackets:
      - limit: 1000000000
        rate: 0.1

accounts:
  - id: "checking"
    name: "Checking"
    type: "liquid"
    balance: 0.0
  - id: "retirement_pretax"
    name: "Retirement Pre-Tax"
    type: "traditional_401k"
    balance: 0.0

waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
  deficit_drawdown_order:
    - account_id: "checking"
    - account_id: "retirement_pretax"

events:
  - id: "salary"
    name: "Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2028
    base_amount: 50000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Investments"]
  - id: "living"
    name: "Living Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 55000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]
  - id: "pretax_401k"
    name: "Pre-Tax 401k"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: 24500.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    target_account_id: "retirement_pretax"
    is_pre_tax_deduction: true
    surplus_only: true
    surplus_priority: 10
    tags: ["Investments"]
"""


def test_deficit_year_skips_gated_contributions_entirely():
    """Income 50k, consumption 55k -> structural deficit every year. Gated
    streams contribute nothing (no self-funding via drawdown) and the retirement
    account stays at zero; the deficit becomes uncovered debt instead."""
    config = load_scenario_from_yaml(DEFICIT_SCENARIO)
    df = SimulationRunner(config).run()

    for year in (2026, 2027, 2028):
        row = df.loc[year]
        assert row["Retirement Contribution Transfers"] == 0.0
        assert row["Investment Contribution Transfers"] == 0.0
        assert row["Deficit Drawdowns"] == 0.0
        assert row["Account: Retirement Pre-Tax"] == 0.0
        assert row["Net Cash Flow"] == pytest.approx(-10000.0)

    # Year 1 shortfall of 10,000 rolls into revolving deficit debt
    assert df.loc[2026]["Debt: Uncovered Deficit (Revolving)"] == pytest.approx(10000.0)


LEGACY_SCENARIO = DEFICIT_SCENARIO.replace(
    "    surplus_only: true\n    surplus_priority: 10\n",
    "",
)


def test_legacy_non_gated_contributions_unchanged():
    """Without surplus_only, the exact same deficit scenario keeps the legacy
    behavior: the contribution fires every year and is self-funded by drawing it
    back out of the account (savings funded by liquidating savings)."""
    config = load_scenario_from_yaml(LEGACY_SCENARIO)
    df = SimulationRunner(config).run()

    # Contribution still made even in a deficit year (legacy semantics preserved)
    assert df.loc[2026]["Retirement Contribution Transfers"] == pytest.approx(-24500.0)
    assert df.loc[2027]["Retirement Contribution Transfers"] == pytest.approx(-24500.0)
    # 24,500 credited then drawn back -> account nets to zero
    assert df.loc[2026]["Account: Retirement Pre-Tax"] == 0.0
    # 24,500 consumed by contribution + 7,550 operating shortfall + 1,400
    # 18% interest rollover from year 1 -> uncovered deficit debt grows
    assert df.loc[2026]["Net Cash Flow"] == pytest.approx(-7550.0)


def test_api_exposes_surplus_only_flag_only_when_opted_in():
    parameters = {p.path: p for p in get_tunable_parameters(load_scenario_from_yaml(SURPLUS_SCENARIO), {})}
    assert "events.pretax_401k.surplus_only" in parameters
    assert parameters["events.pretax_401k.surplus_only"].parameter_type == "bool"
    assert parameters["events.pretax_401k.surplus_only"].control == "toggle"
    assert "events.pretax_401k.surplus_priority" in parameters

    legacy_parameters = {p.path for p in get_tunable_parameters(load_scenario_from_yaml(LEGACY_SCENARIO), {})}
    assert "events.pretax_401k.surplus_only" not in legacy_parameters


def test_schema_defaults_keep_legacy_behavior():
    config = CashStreamEventConfig(
        id="x", name="X", type="cash_stream", category="expense",
        start_year=2026, end_year=2030, base_amount=1000.0, target_account_id="checking",
    )
    assert config.surplus_only is False
    assert config.surplus_priority == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])