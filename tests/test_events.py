import pytest
import pandas as pd
from src.domain_models import SimulationState, AccountState, AssetState, DebtState
from src.schema import (
    CashStreamEventConfig,
    AssetPurchaseEventConfig,
    MortgageConfig,
    AccountLiquidationEventConfig,
    AssetLiquidationEventConfig,
    MacroeconomicsConfig,
)
from src.events import (
    EventImpact,
    CashStreamEvent,
    AssetPurchaseEvent,
    AccountLiquidationEvent,
    AssetLiquidationEvent,
    EventRegistry,
)
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner


@pytest.fixture
def macro_config():
    return MacroeconomicsConfig(
        general_inflation_rate=0.03,
        growth_rates={"real_estate": 0.04},
    )


@pytest.fixture
def sim_state():
    return SimulationState(
        current_year=2030,
        accounts={
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=150000.0),
            "college_fund": AccountState(id="college_fund", name="529 Fund", account_type="liquid", balance=50000.0),
        },
    )


# 1. CashStreamEvent Tests
def test_cash_stream_event_income_and_expense(macro_config, sim_state):
    income_config = CashStreamEventConfig(
        id="salary",
        name="Salary",
        type="cash_stream",
        category="income",
        start_year=2026,
        end_year=2040,
        base_amount=100000.0,
        reference_year=2026,
        inflation_ref="general_inflation_rate",
        is_taxable_income=True,
        tags=["Investments"],
    )
    event = CashStreamEvent(income_config)

    impact = event.evaluate(sim_state, macro_config)
    # Year 2030 (4 years from 2026 @ 3% inflation) = 100,000 * (1.03^4) = 112,550.881
    assert impact.gross_taxable_income == pytest.approx(112550.881)
    assert impact.total_inflow == pytest.approx(112550.881)
    # Income event has no outflow
    assert impact.total_outflow == 0.0


def test_cash_stream_event_gap_years(macro_config, sim_state):
    income_config = CashStreamEventConfig(
        id="salary",
        name="Salary",
        type="cash_stream",
        category="income",
        start_year=2026,
        end_year=2040,
        base_amount=100000.0,
        gap_years=[2030],
        tags=["Investments"],
    )
    event = CashStreamEvent(income_config)

    impact = event.evaluate(sim_state, macro_config)
    # 2030 is a gap year -> income suspended, inflow = 0
    assert impact.total_inflow == 0.0


# 2. AssetPurchaseEvent & Mortgage Tests
def test_asset_purchase_event_triggers_downpayment_asset_and_debt(macro_config, sim_state):
    purchase_config = AssetPurchaseEventConfig(
        id="buy_home",
        name="Buy Primary Home",
        type="asset_purchase",
        trigger_year=2030,
        down_payment=100000.0,
        asset_name="Primary Home",
        asset_initial_value=500000.0,
        growth_rate_ref="real_estate",
        tags=["Housing"],
        mortgage=MortgageConfig(
            principal=400000.0,
            interest_rate=0.06,
            term_years=30,
        ),
    )
    event = AssetPurchaseEvent(purchase_config)

    # Before evaluation
    assert "primary_home" not in sim_state.assets
    assert "primary_home_mortgage" not in sim_state.debts

    impact = event.evaluate(sim_state, macro_config)

    # Check cash outflow for downpayment (down_payment=100000 outflow)
    assert impact.post_tax_expenses == 100000.0
    assert impact.total_outflow == 100000.0

    # Check asset creation
    assert "primary_home" in sim_state.assets
    # Asset created at asset_initial_value=500000
    assert sim_state.assets["primary_home"].value == 500000.0
    assert sim_state.assets["primary_home"].growth_rate_ref == "real_estate"

    # Check debt creation
    assert "primary_home_mortgage" in sim_state.debts
    # Debt created at mortgage.principal=400000
    assert sim_state.debts["primary_home_mortgage"].principal == 400000.0


def test_asset_purchase_event_non_trigger_year(macro_config, sim_state):
    purchase_config = AssetPurchaseEventConfig(
        id="buy_home",
        name="Buy Primary Home",
        type="asset_purchase",
        trigger_year=2035,  # sim_state is 2030
        down_payment=500000.0,
        asset_name="Primary Home",
        asset_initial_value=500000.0,
        tags=["Housing"],
    )
    event = AssetPurchaseEvent(purchase_config)

    impact = event.evaluate(sim_state, macro_config)
    # trigger_year=2035 != current 2030 -> event not evaluated, no outflow
    assert impact.total_outflow == 0.0
    assert "primary_home" not in sim_state.assets


# 3. AssetPurchase with Costs Tests
def test_asset_purchase_event_with_costs(macro_config, sim_state):
    """Verify asset_purchase events store recurring costs on the asset."""
    purchase_config = AssetPurchaseEventConfig(
        id="buy_home_test",
        name="Test House with Costs",
        type="asset_purchase",
        trigger_year=2030,
        down_payment=300000.0,
        asset_name="Test Home",
        asset_initial_value=300000.0,
        growth_rate_ref="real_estate",
        costs={
            "maintenance": 0.01,
            "property_tax": 0.015,
            "insurance": 0.005,
        },
        tags=["Housing"],
    )

    event = AssetPurchaseEvent(purchase_config)
    impact = event.evaluate(sim_state, macro_config)

    # Check that down payment is recorded as expense
    assert impact.post_tax_expenses == 300000.0

    # Check asset was created with recurring costs
    assert "test_home" in sim_state.assets
    asset = sim_state.assets["test_home"]
    assert asset.value == 300000.0
    assert asset.growth_rate_ref == "real_estate"
    assert asset.cost_basis == 300000.0
    assert asset.recurring_costs == {
        "maintenance": 0.01,
        "property_tax": 0.015,
        "insurance": 0.005,
    }


def test_asset_purchase_event_purchase_fees(macro_config, sim_state):
    """Verify asset_purchase events apply one-time purchase fees."""
    purchase_config = AssetPurchaseEventConfig(
        id="buy_home_fees",
        name="Test House with Purchase Fees",
        type="asset_purchase",
        trigger_year=2030,
        down_payment=300000.0,
        asset_name="Test Home",
        asset_initial_value=300000.0,
        growth_rate_ref="real_estate",
        purchase_fees={
            "closing_costs": 0.03,
            "title_insurance": 0.005,
        },
        tags=["Housing"],
    )

    event = AssetPurchaseEvent(purchase_config)
    impact = event.evaluate(sim_state, macro_config)

    # Check that down payment + fees are recorded as expense
    expected_fees = 300000.0 * 0.035  # 3% + 0.5% = 3.5% of $300k = $10,500
    assert impact.post_tax_expenses == pytest.approx(300000.0 + expected_fees)


def test_asset_purchase_event_costs_empty_by_default(macro_config, sim_state):
    """If no costs are defined, future_events should be empty."""
    purchase_config = AssetPurchaseEventConfig(
        id="buy_home_no_costs",
        name="House Without Costs",
        type="asset_purchase",
        trigger_year=2030,
        down_payment=300000.0,
        asset_name="No Cost Home",
        asset_initial_value=300000.0,
        tags=["Housing"],
    )

    event = AssetPurchaseEvent(purchase_config)
    impact = event.evaluate(sim_state, macro_config)

    assert len(impact.future_events) == 0


def test_asset_purchase_event_cost_percentage_validation():
    """Percentages outside [0, 1] should raise a validation error."""
    with pytest.raises(ValueError):
        AssetPurchaseEventConfig(
            id="bad_costs",
            name="Invalid Cost Asset",
            type="asset_purchase",
            trigger_year=2030,
            down_payment=300000.0,
            asset_name="Bad Home",
            asset_initial_value=300000.0,
            costs={"maintenance": 1.5},  # 150% -> invalid
            tags=["Housing"],
        )


def test_asset_purchase_event_fee_percentage_validation():
    """Purchase fee percentages outside [0, 1] should raise a validation error."""
    with pytest.raises(ValueError):
        AssetPurchaseEventConfig(
            id="bad_fees",
            name="Invalid Fee Asset",
            type="asset_purchase",
            trigger_year=2030,
            down_payment=300000.0,
            asset_name="Bad Home",
            asset_initial_value=300000.0,
            purchase_fees={"closing_costs": 1.5},  # 150% -> invalid
            tags=["Housing"],
        )


# 4. AccountLiquidationEvent Tests
def test_account_liquidation_event(macro_config, sim_state):
    liq_config = AccountLiquidationEventConfig(
        id="tuition",
        name="College Tuition Liquidation",
        type="account_liquidation",
        trigger_year=2030,
        source_account_id="college_fund",
        target_account_id="checking",
        amount=25000.0,
        tags=["Children"],
    )
    event = AccountLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state, macro_config)
    # 50000 - 25000 = 25000 remains in college_fund
    assert sim_state.accounts["college_fund"].balance == 25000.0
    # 150000 + 25000 = 175000 in checking after transfer
    assert sim_state.accounts["checking"].balance == 175000.0


# 5. Event Registry Polymorphic Creation
def test_event_registry_instantiation():
    raw_configs = [
        CashStreamEventConfig(
            id="s1", name="Salary", type="cash_stream", category="income", start_year=2026, end_year=2030, base_amount=50000.0, tags=["Investments"]
        ),
        AssetPurchaseEventConfig(
            id="a1", name="Car", type="asset_purchase", trigger_year=2028, down_payment=20000.0, asset_name="Car", asset_initial_value=20000.0, tags=["Transportation"]
        ),
    ]
    events = EventRegistry.from_configs(raw_configs)
    assert len(events) == 2
    assert isinstance(events[0], CashStreamEvent)
    assert isinstance(events[1], AssetPurchaseEvent)


# 6. AssetLiquidationEvent Tests
@pytest.fixture
def sim_state_with_asset():
    return SimulationState(
        current_year=2035,
        accounts={
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=100000.0),
        },
        assets={
            "primary_home": AssetState(
                id="primary_home",
                name="Primary Home",
                value=500000.0,
                growth_rate_ref="real_estate",
                cost_basis=300000.0,
            ),
        },
        debts={},
    )


def test_asset_liquidation_event_basic(macro_config, sim_state_with_asset):
    """Test basic asset liquidation without mortgage."""
    liq_config = AssetLiquidationEventConfig(
        id="sell_home",
        name="Sell Primary Home",
        type="asset_liquidation",
        trigger_year=2035,
        asset_name="Primary Home",
        tags=["Housing"],
    )
    event = AssetLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state_with_asset, macro_config)

    # Sale price = asset value = 500,000
    # Capital gain = 500,000 - 300,000 = 200,000
    assert impact.gross_taxable_income == 200000.0
    assert impact.cash_inflow == 500000.0
    assert "primary_home" not in sim_state_with_asset.assets


def test_asset_liquidation_event_with_mortgage(macro_config, sim_state_with_asset):
    """Test asset liquidation with mortgage payoff."""
    sim_state_with_asset.debts["primary_home_mortgage"] = DebtState(
        id="primary_home_mortgage",
        name="Primary Home Mortgage",
        principal=200000.0,
        interest_rate=0.06,
        term_years=30,
        remaining_years=25,
    )

    liq_config = AssetLiquidationEventConfig(
        id="sell_home",
        name="Sell Primary Home",
        type="asset_liquidation",
        trigger_year=2035,
        asset_name="Primary Home",
        tags=["Housing"],
    )
    event = AssetLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state_with_asset, macro_config)

    # Sale price = 500,000
    # Net proceeds after mortgage = 500,000 - 200,000 = 300,000
    assert impact.gross_taxable_income == 200000.0
    assert impact.cash_inflow == 300000.0
    assert "primary_home" not in sim_state_with_asset.assets
    assert "primary_home_mortgage" not in sim_state_with_asset.debts


def test_asset_liquidation_event_mortgage_kept_when_flag_false(macro_config, sim_state_with_asset):
    """mortgage_payoff=False keeps the mortgage as an ongoing liability."""
    sim_state_with_asset.debts["primary_home_mortgage"] = DebtState(
        id="primary_home_mortgage",
        name="Primary Home Mortgage",
        principal=200000.0,
        interest_rate=0.06,
        term_years=30,
        remaining_years=25,
    )

    liq_config = AssetLiquidationEventConfig(
        id="sell_home",
        name="Sell Primary Home",
        type="asset_liquidation",
        trigger_year=2035,
        asset_name="Primary Home",
        mortgage_payoff=False,
        tags=["Housing"],
    )
    event = AssetLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state_with_asset, macro_config)

    # Sale price = 500,000, buyer keeps the full amount (mortgage not paid off)
    # Capital gain = 500,000 - 300,000 = 200,000 (unaffected by payoff choice)
    assert impact.gross_taxable_income == 200000.0
    assert impact.cash_inflow == 500000.0
    assert "primary_home" not in sim_state_with_asset.assets
    assert "primary_home_mortgage" in sim_state_with_asset.debts


def test_asset_liquidation_event_sale_fees(macro_config, sim_state_with_asset):
    """Test asset liquidation with sale fees (e.g., agent commission)."""
    liq_config = AssetLiquidationEventConfig(
        id="sell_home",
        name="Sell Primary Home",
        type="asset_liquidation",
        trigger_year=2035,
        asset_name="Primary Home",
        sale_fees={
            "agent_commission": 0.06,  # 6% agent fee
            "closing_costs": 0.02,     # 2% closing costs
        },
        tags=["Housing"],
    )
    event = AssetLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state_with_asset, macro_config)

    # Sale price = 500,000
    # Fees = 500,000 * 0.08 = 40,000
    # Gross proceeds (cash_inflow) = 500,000 (no mortgage)
    # Post-tax expenses = 40,000 (fees)
    # Net cash flow = 500,000 - 40,000 = 460,000
    # Capital gain = 500,000 - 300,000 = 200,000 (not affected by fees)
    assert impact.gross_taxable_income == 200000.0
    assert impact.post_tax_expenses == 40000.0
    assert impact.cash_inflow == 500000.0
    assert impact.net_cash_flow == 460000.0


def test_asset_liquidation_event_custom_sale_price(macro_config, sim_state_with_asset):
    """Test asset liquidation with custom sale price."""
    liq_config = AssetLiquidationEventConfig(
        id="sell_home",
        name="Sell Primary Home",
        type="asset_liquidation",
        trigger_year=2035,
        asset_name="Primary Home",
        sale_price=600000.0,  # Sell above market value
        tags=["Housing"],
    )
    event = AssetLiquidationEvent(liq_config)

    impact = event.evaluate(sim_state_with_asset, macro_config)

    # Sale price = 600,000
    # Capital gain = 600,000 - 300,000 = 300,000
    assert impact.gross_taxable_income == 300000.0
    assert impact.cash_inflow == 600000.0


def test_asset_liquidation_event_fee_percentage_validation():
    """Sale fee percentages outside [0, 1] should raise a validation error."""
    with pytest.raises(ValueError):
        AssetLiquidationEventConfig(
            id="bad_fees",
            name="Invalid Fee Asset",
            type="asset_liquidation",
            trigger_year=2035,
            asset_name="Bad Home",
            sale_fees={"agent_commission": 1.5},  # 150% -> invalid
            tags=["Housing"],
        )


# 7. Fee Breakdown Columns Tests (Integration with Engine)
def test_asset_purchase_fee_breakdown_columns():
    """Purchase fee breakdown columns should appear in DataFrame output."""
    scenario_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Purchase Fee Breakdown Test"
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
        down_payment: 500000.0
        asset_name: "Primary Home"
        asset_initial_value: 500000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
        purchase_fees:
          closing_costs: 0.03
          title_insurance: 0.005
    """
    config = load_scenario_from_yaml(scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # Check fee breakdown columns exist
    assert "Event: Buy Home - closing_costs" in df.columns
    assert "Event: Buy Home - title_insurance" in df.columns

    # Check values in purchase year (2030)
    row_2030 = df.loc[2030]
    # 500000 * 0.03 = 15000
    assert row_2030["Event: Buy Home - closing_costs"] == -15000.0  # 3% of 500000
    # 500000 * 0.005 = 2500
    assert row_2030["Event: Buy Home - title_insurance"] == -2500.0  # 0.5% of 500000

    # Fees should only appear in trigger year
    for year in range(2026, 2036):
        row = df.loc[year]
        if year == 2030:
            assert row["Event: Buy Home - closing_costs"] == -15000.0
            assert row["Event: Buy Home - title_insurance"] == -2500.0
        else:
            assert pd.isna(row["Event: Buy Home - closing_costs"]) or row["Event: Buy Home - closing_costs"] == 0
            assert pd.isna(row["Event: Buy Home - title_insurance"]) or row["Event: Buy Home - title_insurance"] == 0

    # Total event net cash flow should include fees + down payment
    # With new granular output: main column = down payment only, fees in breakdown columns
    assert row_2030["Event: Buy Home"] == -500000.0  # down payment only
    # Sum of main + fee breakdowns = total cost
    total_buy_cost = row_2030["Event: Buy Home"] + row_2030["Event: Buy Home - closing_costs"] + row_2030["Event: Buy Home - title_insurance"]
    assert total_buy_cost == -517500.0  # -500000 - 15000 - 2500


def test_asset_liquidation_fee_breakdown_columns():
    """Sale fee breakdown columns should appear in DataFrame output."""
    scenario_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Sale Fee Breakdown Test"
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
        down_payment: 500000.0
        asset_name: "Primary Home"
        asset_initial_value: 500000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
      - id: "sell_home"
        name: "Sell Home"
        type: "asset_liquidation"
        trigger_year: 2033
        asset_name: "Primary Home"
        tags: ["Housing"]
        sale_fees:
          agent_commission: 0.06
          closing_costs: 0.02
    """
    config = load_scenario_from_yaml(scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # Check fee breakdown columns exist
    assert "Event: Sell Home - agent_commission" in df.columns
    assert "Event: Sell Home - closing_costs" in df.columns

    # Check values in sale year (2033)
    row_2033 = df.loc[2033]
    # Sale price = 500000 * 1.03^3 = 546363.5 (asset grows at 3% from 2030)
    # agent_commission = 6% of sale_price
    # closing_costs = 2% of sale_price
    sale_price_2033 = 500000 * (1.03 ** 3)
    expected_commission = -sale_price_2033 * 0.06
    expected_closing = -sale_price_2033 * 0.02

    assert row_2033["Event: Sell Home - agent_commission"] == pytest.approx(expected_commission)
    assert row_2033["Event: Sell Home - closing_costs"] == pytest.approx(expected_closing)

    # Fees should only appear in trigger year
    for year in range(2026, 2036):
        row = df.loc[year]
        if year == 2033:
            assert row["Event: Sell Home - agent_commission"] == pytest.approx(expected_commission)
            assert row["Event: Sell Home - closing_costs"] == pytest.approx(expected_closing)
        else:
            assert pd.isna(row["Event: Sell Home - agent_commission"]) or row["Event: Sell Home - agent_commission"] == 0
            assert pd.isna(row["Event: Sell Home - closing_costs"]) or row["Event: Sell Home - closing_costs"] == 0


def test_multiple_properties_fee_breakdown_columns():
    """Multiple properties with different fees should all have breakdown columns."""
    scenario_yaml = """
    version: "1.0"
    meta:
      scenario_name: "Multiple Properties Fee Test"
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
        balance: 1000000.0
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
      - id: "buy_home1"
        name: "Buy First Home"
        type: "asset_purchase"
        trigger_year: 2028
        down_payment: 500000.0
        asset_name: "First Home"
        asset_initial_value: 500000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
        purchase_fees:
          closing_costs: 0.03
          title_insurance: 0.005
      - id: "buy_home2"
        name: "Buy Second Home"
        type: "asset_purchase"
        trigger_year: 2032
        down_payment: 750000.0
        asset_name: "Second Home"
        asset_initial_value: 750000.0
        growth_rate_ref: "real_estate"
        tags: ["Housing"]
        purchase_fees:
          closing_costs: 0.025
          inspection_fee: 0.002
      - id: "sell_home1"
        name: "Sell First Home"
        type: "asset_liquidation"
        trigger_year: 2035
        asset_name: "First Home"
        tags: ["Housing"]
        sale_fees:
          agent_commission: 0.06
          closing_costs: 0.02
      - id: "sell_home2"
        name: "Sell Second Home"
        type: "asset_liquidation"
        trigger_year: 2038
        asset_name: "Second Home"
        tags: ["Housing"]
        sale_fees:
          agent_commission: 0.05
          title_insurance: 0.005
    """
    config = load_scenario_from_yaml(scenario_yaml)
    runner = SimulationRunner(config)
    df = runner.run()

    # Check all fee breakdown columns exist
    assert "Event: Buy First Home - closing_costs" in df.columns
    assert "Event: Buy First Home - title_insurance" in df.columns
    assert "Event: Buy Second Home - closing_costs" in df.columns
    assert "Event: Buy Second Home - inspection_fee" in df.columns
    assert "Event: Sell First Home - agent_commission" in df.columns
    assert "Event: Sell First Home - closing_costs" in df.columns
    assert "Event: Sell Second Home - agent_commission" in df.columns
    assert "Event: Sell Second Home - title_insurance" in df.columns

    # Check first purchase year (2028)
    row_2028 = df.loc[2028]
    # 500000 * 0.03 = 15000
    assert row_2028["Event: Buy First Home - closing_costs"] == -15000.0
    # 500000 * 0.005 = 2500
    assert row_2028["Event: Buy First Home - title_insurance"] == -2500.0
    assert pd.isna(row_2028.get("Event: Buy Second Home - closing_costs", float('nan'))) or row_2028.get("Event: Buy Second Home - closing_costs", 0) == 0

    # Check second purchase year (2032)
    row_2032 = df.loc[2032]
    # 750000 * 0.025 = 18750
    assert row_2032["Event: Buy Second Home - closing_costs"] == -18750.0  # 2.5% of 750000
    # 750000 * 0.002 = 1500
    assert row_2032["Event: Buy Second Home - inspection_fee"] == -1500.0  # 0.2% of 750000

    # Check first sale year (2035)
    row_2035 = df.loc[2035]
    # First Home grows at 3%/yr for 7 years (2028 -> 2035), then fees 6% + 2%
    sale_price_1_2035 = 500000 * (1.03 ** (2035 - 2028))
    assert row_2035["Event: Sell First Home - agent_commission"] == pytest.approx(-sale_price_1_2035 * 0.06)
    assert row_2035["Event: Sell First Home - closing_costs"] == pytest.approx(-sale_price_1_2035 * 0.02)

    # Check second sale year (2038)
    row_2038 = df.loc[2038]
    # Second Home grows at 3%/yr for 6 years (2032 -> 2038), then fees 5% + 0.5%
    sale_price_2_2038 = 750000 * (1.03 ** (2038 - 2032))
    assert row_2038["Event: Sell Second Home - agent_commission"] == pytest.approx(-sale_price_2_2038 * 0.05)
    assert row_2038["Event: Sell Second Home - title_insurance"] == pytest.approx(-sale_price_2_2038 * 0.005)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])