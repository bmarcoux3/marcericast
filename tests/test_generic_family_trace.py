"""Phase 7: generic-family full-scenario trace for 2026 and 2061.

Every figure below is derived by hand from the generic-family.yaml inputs
(salaries, standard deduction, ordinary + capital-gains brackets, 3%
real-estate growth, 6.5% amortization) and pinned exactly so any engine
drift breaks the trace.
"""
import pytest
from pathlib import Path

from src.engine import SimulationRunner
from src.loader import load_scenario_from_yaml

GENERIC_SCENARIO_PATH = Path(__file__).parent / "fixtures" / "scenarios" / "generic-family.yaml"


@pytest.fixture(scope="module")
def generic_df():
    config = load_scenario_from_yaml(GENERIC_SCENARIO_PATH)
    return SimulationRunner(config).run()


# ---------------------------------------------------------------- 2026
def test_trace_2026_income_and_tax(generic_df):
    """2026 AGI pipeline: salaries 120k + 80k, pre-tax 20k, std ded 32.2k."""
    row = generic_df.loc[2026]
    assert row["Gross Taxable Income"] == pytest.approx(200000.0)      # 120,000 + 80,000
    assert row["Pre-tax Deductions"] == pytest.approx(20000.0)         # retirement pre-tax
    assert row["AGI"] == pytest.approx(180000.0)                       # 200,000 - 20,000
    assert row["Tax: Standard Deduction"] == pytest.approx(32200.0)
    assert row["Tax: Taxable Income"] == pytest.approx(147800.0)       # 180,000 - 32,200
    # Progressive 2026 federal tax on 147,800:
    #   24,800 @ 10% + 76,000 @ 12% + 47,000 @ 22%
    # = 2,480 + 9,120 + 10,340 = 21,940
    assert row["Federal Tax"] == pytest.approx(-21940.0)


def test_trace_2026_home_purchase(generic_df):
    """2026 Family Home purchase: 500k home, 150k down, 350k mortgage @ 6.5%."""
    row = generic_df.loc[2026]
    assert row["Asset: Family Home"] == pytest.approx(500000.0)
    # Purchase fees: 3% closing + 0.5% title insurance of 500,000
    assert row["Event: Family Home Purchase - closing_costs"] == pytest.approx(-15000.0)
    assert row["Event: Family Home Purchase - title_insurance"] == pytest.approx(-2500.0)
    # Down payment is the main event outflow
    assert row["Event: Family Home Purchase"] == pytest.approx(-150000.0)
    # First-year mortgage payment and remaining balance (350,000 @ 6.5%, 30 yr)
    assert row["Mortgage Payment: Family Home Mortgage"] == pytest.approx(-26802.104786068714)
    assert row["Debt: Family Home Mortgage"] == pytest.approx(345947.8952139313)


def test_trace_2026_cash_reserve_floor(generic_df):
    """Checking is a cash reserve with a 20k floor and is never drained below it."""
    row = generic_df.loc[2026]
    assert row["Account: Primary Checking"] == pytest.approx(20000.0)
    # The deep 2026 deficit (down payment + fees + lifestyle spend) is absorbed
    # by the brokerage account after the checking floor is hit.
    assert row["Account: Primary Taxable Brokerage"] == pytest.approx(1757.895213931275)
    assert row["Account: Pre-Tax Retirement (401k)"] == pytest.approx(73500.0)   # 50,000*1.07 + 20,000
    assert row["Account: Roth IRA"] == pytest.approx(15700.0)                    # 10,000*1.07 + 5,000
    assert row["Account: College 529"] == pytest.approx(12000.0)                 # 0 + 12,000


def test_trace_2026_net_worth(generic_df):
    """Net worth decomposition on the 2026 row."""
    row = generic_df.loc[2026]
    assert row["Net Cash Flow"] == pytest.approx(-136242.10478606872)
    assert row["Total Assets"] == pytest.approx(622957.8952139313)
    assert row["Total Liabilities"] == pytest.approx(345947.8952139313)
    # 622,957.90 - 345,947.90 = 277,010.00
    assert row["Net Worth"] == pytest.approx(277010.0)


# ---------------------------------------------------------------- 2061
def test_trace_2061_downsize_liquidation(generic_df):
    """2061 sale of Family Home: 500k grown 35 years at 3% = 1,406,931.23.

    Mortgage paid off in 2056 (30-yr term), so gross proceeds equal the sale
    price. The 406,931.23 gain after the $500k primary-residence exclusion is
    taxable capital-gains income.
    """
    row = generic_df.loc[2061]
    sale_price = 500000.0 * 1.03 ** 35
    assert sale_price == pytest.approx(1406931.2271857627)
    assert row["Event: Sell Family Home (Downsize)"] == pytest.approx(sale_price)
    assert row["Event: Sell Family Home (Downsize) - agent_commission"] == pytest.approx(-84415.87363114576)
    assert row["Event: Sell Family Home (Downsize) - closing_costs"] == pytest.approx(-28138.624543715254)
    assert row["Asset: Family Home"] != row["Asset: Family Home"]  # NaN -> asset removed
    assert row["Debt: Family Home Mortgage"] == pytest.approx(0.0)  # fully amortized


def test_trace_2061_capital_gain_and_tax(generic_df):
    """2061 tax: no salary (retired). The home gain 406,931.23 (after 500k
    exclusion) is the only income and is taxed at capital-gains rates."""
    row = generic_df.loc[2061]
    gain = 1406931.2271857627 - 500000.0 - 500000.0
    assert gain == pytest.approx(406931.2271857627)
    assert row["Gross Taxable Income"] == pytest.approx(gain)
    assert row["Pre-tax Deductions"] == pytest.approx(0.0)
    assert row["AGI"] == pytest.approx(gain)
    assert row["Federal Tax"] == pytest.approx(-27559.69191543497)


def test_trace_2061_retirement_home_purchase(generic_df):
    """2061 retirement home: 400k bought outright (no mortgage), fees 3.5%."""
    row = generic_df.loc[2061]
    assert row["Event: Retirement Home Purchase"] == pytest.approx(-400000.0)
    assert row["Event: Retirement Home Purchase - closing_costs"] == pytest.approx(-12000.0)  # 3%
    assert row["Event: Retirement Home Purchase - title_insurance"] == pytest.approx(-2000.0)  # 0.5%
    assert row["Asset: Retirement Home"] == pytest.approx(400000.0)
    assert row["Total Liabilities"] == pytest.approx(0.0)


def test_trace_years_2061_end_state(generic_df):
    """2061 balances as pinned from the trace."""
    row = generic_df.loc[2061]
    assert row["Net Cash Flow"] == pytest.approx(580233.0660516449)
    assert row["Net Worth"] == pytest.approx(11333491.53087334)
