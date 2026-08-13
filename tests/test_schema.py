"""Tests for Pydantic schema validation."""
import pytest
import yaml
from pydantic import ValidationError
from src.loader import load_scenario_from_yaml
from src.schema import (
    ScenarioConfig,
    CashStreamEventConfig,
    AssetPurchaseEventConfig,
    Tag,
    MetaConfig,
    TaxBracket,
    FederalTaxRules,
    CapitalGainsTaxRules,
    TaxRulesConfig,
    MacroeconomicsConfig,
    AccountConfig,
    WaterfallStrategyConfig,
    SurplusAllocationItem,
    DeficitDrawdownItem,
    MortgageConfig,
    AssetLiquidationEventConfig,
    AccountLiquidationEventConfig,
)


class TestMetaConfig:
    """Tests for MetaConfig validation."""

    def test_valid_meta(self):
        """Valid meta config should pass."""
        meta = MetaConfig(
            scenario_name="Test",
            start_year=2026,
            end_year=2030,
        )
        assert meta.scenario_name == "Test"
        assert meta.start_year == 2026
        assert meta.end_year == 2030
        assert meta.tax_status == "MFJ"  # default

    def test_invalid_years_raises(self):
        """End year before start year should raise."""
        with pytest.raises(ValidationError) as excinfo:
            MetaConfig(
                scenario_name="Invalid",
                start_year=2030,
                end_year=2026,
            )
        assert "end_year" in str(excinfo.value).lower() or "2026" in str(excinfo.value)

    def test_tax_status_validation(self):
        """Invalid tax status should raise."""
        with pytest.raises(ValidationError):
            MetaConfig(
                scenario_name="Test",
                start_year=2026,
                end_year=2030,
                tax_status="InvalidStatus",
            )

    def test_extra_fields_forbidden(self):
        """Extra fields should be forbidden."""
        with pytest.raises(ValidationError):
            MetaConfig(
                scenario_name="Test",
                start_year=2026,
                end_year=2030,
                unknown_field="not_allowed",
            )


class TestTaxConfig:
    """Tests for tax configuration validation."""

    def test_tax_bracket_validation(self):
        """Tax bracket validation."""
        bracket = TaxBracket(limit=50000, rate=0.10)
        assert bracket.limit == 50000
        assert bracket.rate == 0.10

    def test_federal_tax_rules(self):
        """Federal tax rules with brackets."""
        federal = FederalTaxRules(
            standard_deduction=30000,
            brackets=[
                TaxBracket(limit=20000, rate=0.10),
                TaxBracket(limit=100000, rate=0.20),
                TaxBracket(limit=float("inf"), rate=0.30),
            ],
        )
        assert federal.standard_deduction == 30000
        assert len(federal.brackets) == 3

    def test_capital_gains_tax_rules(self):
        """Capital gains tax rules."""
        cg = CapitalGainsTaxRules(
            brackets=[
                TaxBracket(limit=40000, rate=0.0),
                TaxBracket(limit=float("inf"), rate=0.15),
            ],
        )
        assert len(cg.brackets) == 2

    def test_tax_rules_config_defaults(self):
        """TaxRulesConfig with defaults."""
        config = TaxRulesConfig()
        assert config.inflate_brackets is True
        assert config.reference_year == 2026
        assert config.inflation_ref == "general_inflation_rate"
        assert isinstance(config.federal, FederalTaxRules)
        assert isinstance(config.capital_gains, CapitalGainsTaxRules)

    def test_tax_rules_config_custom(self):
        """TaxRulesConfig with custom values."""
        config = TaxRulesConfig(
            inflate_brackets=False,
            reference_year=2025,
            inflation_ref="custom_rate",
            federal=FederalTaxRules(
                standard_deduction=25000,
                brackets=[TaxBracket(limit=float("inf"), rate=0.15)],
            ),
        )
        assert config.inflate_brackets is False
        assert config.reference_year == 2025
        assert config.inflation_ref == "custom_rate"


class TestMacroeconomicsConfig:
    """Tests for MacroeconomicsConfig validation."""

    def test_defaults(self):
        """Default values."""
        macro = MacroeconomicsConfig()
        assert macro.general_inflation_rate == 0.0
        assert macro.growth_rates == {}

    def test_custom_rates(self):
        """Custom growth rates."""
        macro = MacroeconomicsConfig(
            general_inflation_rate=0.03,
            growth_rates={"equities": 0.07, "real_estate": 0.04},
        )
        assert macro.general_inflation_rate == 0.03
        assert macro.growth_rates == {"equities": 0.07, "real_estate": 0.04}

    def test_derisking_schedule_valid(self):
        """Valid derisking schedule (end_age > start_age) is accepted."""
        macro = MacroeconomicsConfig(
            growth_rates={"equities": 0.10, "bonds": 0.03},
            derisking_schedule={
                "equities": {"start_age": 50, "end_age": 70, "transition_to": "bonds"}
            },
        )
        assert macro.derisking_schedule["equities"]["start_age"] == 50

    def test_derisking_schedule_end_age_less_than_start_age(self):
        """end_age <= start_age should raise a validation error."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MacroeconomicsConfig(
                growth_rates={"equities": 0.10, "bonds": 0.03},
                derisking_schedule={
                    "equities": {"start_age": 70, "end_age": 50, "transition_to": "bonds"}
                },
            )


class TestAccountConfig:
    """Tests for AccountConfig validation."""

    def test_valid_account(self):
        """Valid account config."""
        acc = AccountConfig(
            id="checking",
            name="Checking Account",
            type="liquid",
            balance=10000.0,
        )
        assert acc.id == "checking"
        assert acc.type == "liquid"
        assert acc.balance == 10000.0

    def test_all_account_types(self):
        """All valid account types."""
        for acc_type in ["liquid", "taxable_brokerage", "traditional_401k", "roth_ira", "debt"]:
            acc = AccountConfig(
                id="test",
                name="Test",
                type=acc_type,
                balance=0.0,
            )
            assert acc.type == acc_type

    def test_invalid_account_type(self):
        """Invalid account type should raise."""
        with pytest.raises(ValidationError):
            AccountConfig(
                id="test",
                name="Test",
                type="invalid_type",
                balance=0.0,
            )

    def test_cash_reserve_config(self):
        """Cash reserve account configuration."""
        acc = AccountConfig(
            id="checking",
            name="Checking",
            type="liquid",
            balance=15000.0,
            is_cash_reserve=True,
            min_target_balance=10000.0,
        )
        assert acc.is_cash_reserve is True
        assert acc.min_target_balance == 10000.0


class TestWaterfallStrategy:
    """Tests for WaterfallStrategyConfig validation."""

    def test_surplus_allocation_item(self):
        """Surplus allocation item."""
        item = SurplusAllocationItem(account_id="401k", max_annual_contribution=20000.0)
        assert item.account_id == "401k"
        assert item.max_annual_contribution == 20000.0

    def test_surplus_allocation_default_cap(self):
        """Default max contribution is infinity."""
        item = SurplusAllocationItem(account_id="brokerage")
        assert item.max_annual_contribution == float("inf")

    def test_deficit_drawdown_item(self):
        """Deficit drawdown item."""
        item = DeficitDrawdownItem(account_id="checking")
        assert item.account_id == "checking"

    def test_waterfall_strategy_defaults(self):
        """Default empty waterfall strategy."""
        strategy = WaterfallStrategyConfig()
        assert strategy.surplus_allocation == []
        assert strategy.deficit_drawdown_order == []

    def test_waterfall_strategy_full(self):
        """Full waterfall strategy."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="401k", max_annual_contribution=20000.0),
                SurplusAllocationItem(account_id="brokerage"),
            ],
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
                DeficitDrawdownItem(account_id="brokerage"),
            ],
        )
        assert len(strategy.surplus_allocation) == 2
        assert len(strategy.deficit_drawdown_order) == 2


class TestEventConfigs:
    """Tests for event configuration validation."""

    def test_cash_stream_event_income(self):
        """Cash stream income event."""
        event = CashStreamEventConfig(
            id="salary",
            name="Salary",
            category="income",
            start_year=2026,
            end_year=2030,
            base_amount=100000.0,
            tags=["Investments"],
        )
        assert event.id == "salary"
        assert event.category == "income"
        assert event.tags == ["Investments"]

    def test_cash_stream_event_expense(self):
        """Cash stream expense event."""
        event = CashStreamEventConfig(
            id="rent",
            name="Rent",
            category="expense",
            start_year=2026,
            end_year=2030,
            base_amount=24000.0,
            tags=["Housing"],
        )
        assert event.category == "expense"

    def test_cash_stream_event_optional_fields(self):
        """Cash stream with all optional fields."""
        event = CashStreamEventConfig(
            id="salary",
            name="Salary",
            category="income",
            start_year=2026,
            end_year=2030,
            base_amount=100000.0,
            reference_year=2026,
            inflation_ref="general_inflation_rate",
            gap_years=[2028],
            is_taxable_income=True,
            is_earned_income=True,
            is_pre_tax_deduction=False,
            target_account_id="401k",
            step_adjustments={2028: 1.1},
            tags=["Investments"],
        )
        assert event.reference_year == 2026
        assert event.gap_years == [2028]
        assert event.is_taxable_income is True
        assert event.step_adjustments == {2028: 1.1}

    def test_invalid_category(self):
        """Invalid category should raise."""
        with pytest.raises(ValidationError):
            CashStreamEventConfig(
                id="test",
                name="Test",
                category="invalid",
                start_year=2026,
                end_year=2030,
                base_amount=1000.0,
                tags=["Investments"],
            )

    def test_asset_purchase_event(self):
        """Asset purchase event."""
        event = AssetPurchaseEventConfig(
            id="buy_home",
            name="Buy Home",
            trigger_year=2030,
            down_payment=300000.0,
            asset_name="Primary Home",
            asset_initial_value=300000.0,
            growth_rate_ref="real_estate",
            tags=["Housing"],
        )
        assert event.trigger_year == 2030
        assert event.down_payment == 300000.0
        assert event.asset_initial_value == 300000.0

    def test_asset_purchase_with_mortgage(self):
        """Asset purchase with mortgage."""
        event = AssetPurchaseEventConfig(
            id="buy_home",
            name="Buy Home",
            trigger_year=2030,
            down_payment=50000.0,
            asset_name="Primary Home",
            asset_initial_value=300000.0,
            mortgage=MortgageConfig(
                principal=250000.0,
                interest_rate=0.06,
                term_years=30,
            ),
            tags=["Housing"],
        )
        assert event.mortgage is not None
        assert event.mortgage.principal == 250000.0
        assert event.mortgage.interest_rate == 0.06
        assert event.mortgage.term_years == 30

    def test_asset_purchase_with_costs(self):
        """Asset purchase with recurring costs."""
        event = AssetPurchaseEventConfig(
            id="buy_home",
            name="Buy Home",
            trigger_year=2030,
            down_payment=300000.0,
            asset_name="Primary Home",
            asset_initial_value=300000.0,
            costs={
                "maintenance": 0.01,
                "property_tax": 0.015,
                "insurance": 0.005,
            },
            tags=["Housing"],
        )
        assert event.costs == {
            "maintenance": 0.01,
            "property_tax": 0.015,
            "insurance": 0.005,
        }

    def test_asset_purchase_invalid_cost_percentage(self):
        """Cost percentage outside [0,1] should raise."""
        with pytest.raises(ValidationError) as excinfo:
            AssetPurchaseEventConfig(
                id="bad_costs",
                name="Bad Costs",
                trigger_year=2030,
                down_payment=300000.0,
                asset_name="Bad Home",
                asset_initial_value=300000.0,
                costs={"maintenance": 1.5},  # 150% - invalid
                tags=["Housing"],
            )
        assert "between 0 and 1" in str(excinfo.value).lower() or "1.5" in str(excinfo.value)

    def test_asset_purchase_negative_cost(self):
        """Negative cost percentage should raise."""
        with pytest.raises(ValidationError):
            AssetPurchaseEventConfig(
                id="bad_costs",
                name="Bad Costs",
                trigger_year=2030,
                down_payment=300000.0,
                asset_name="Bad Home",
                asset_initial_value=300000.0,
                costs={"maintenance": -0.01},
                tags=["Housing"],
            )

    def test_asset_purchase_full_cash_passes(self):
        """Full cash purchase (down_payment == asset value, no mortgage) should pass."""
        event = AssetPurchaseEventConfig(
            id="buy_cash",
            name="Buy Cash Home",
            trigger_year=2030,
            down_payment=300000.0,
            asset_name="Cash Home",
            asset_initial_value=300000.0,
            tags=["Housing"],
        )
        assert event.down_payment == 300000.0
        assert event.mortgage is None

    def test_asset_purchase_mortgage_funding_matches_passes(self):
        """Down payment + mortgage principal equal to asset value should pass."""
        event = AssetPurchaseEventConfig(
            id="buy_home",
            name="Buy Home",
            trigger_year=2030,
            down_payment=100000.0,
            asset_name="Primary Home",
            asset_initial_value=400000.0,
            mortgage=MortgageConfig(
                principal=300000.0,
                interest_rate=0.06,
                term_years=30,
            ),
            tags=["Housing"],
        )
        assert event.mortgage.principal == 300000.0

    def test_asset_purchase_underfunded_no_mortgage_raises(self):
        """Down payment below asset value with no mortgage should raise."""
        with pytest.raises(ValidationError) as excinfo:
            AssetPurchaseEventConfig(
                id="buy_gap",
                name="Buy With Gap",
                trigger_year=2061,
                down_payment=300000.0,
                asset_name="Retirement Home",
                asset_initial_value=400000.0,
                tags=["Housing"],
            )
        assert "not fully funded" in str(excinfo.value)

    def test_asset_purchase_mortgage_underfunded_raises(self):
        """Down payment + mortgage below asset value should raise."""
        with pytest.raises(ValidationError) as excinfo:
            AssetPurchaseEventConfig(
                id="buy_gap",
                name="Buy With Gap",
                trigger_year=2030,
                down_payment=50000.0,
                asset_name="Home",
                asset_initial_value=400000.0,
                mortgage=MortgageConfig(
                    principal=300000.0,
                    interest_rate=0.06,
                    term_years=30,
                ),
                tags=["Housing"],
            )
        assert "not fully funded" in str(excinfo.value)

    def test_asset_purchase_mortgage_overfunded_raises(self):
        """Down payment + mortgage above asset value should raise."""
        with pytest.raises(ValidationError) as excinfo:
            AssetPurchaseEventConfig(
                id="buy_over",
                name="Buy Overfunded",
                trigger_year=2030,
                down_payment=300000.0,
                asset_name="Home",
                asset_initial_value=550000.0,
                mortgage=MortgageConfig(
                    principal=365000.0,
                    interest_rate=0.065,
                    term_years=30,
                ),
                tags=["Housing"],
            )
        assert "not fully funded" in str(excinfo.value)

    def test_account_liquidation_event(self):
        """Account liquidation event."""
        event = AccountLiquidationEventConfig(
            id="tuition",
            name="College Tuition",
            trigger_year=2030,
            source_account_id="college_fund",
            target_account_id="checking",
            amount=25000.0,
            tags=["Children"],
        )
        assert event.source_account_id == "college_fund"
        assert event.target_account_id == "checking"
        assert event.amount == 25000.0

    def test_asset_liquidation_event(self):
        """Asset liquidation event."""
        event = AssetLiquidationEventConfig(
            id="sell_home",
            name="Sell Home",
            trigger_year=2035,
            asset_name="Primary Home",
            sale_price=500000.0,
            mortgage_payoff=True,
            tags=["Housing"],
        )
        assert event.sale_price == 500000.0
        assert event.mortgage_payoff is True

    def test_asset_liquidation_without_sale_price(self):
        """Asset liquidation without custom sale price."""
        event = AssetLiquidationEventConfig(
            id="sell_home",
            name="Sell Home",
            trigger_year=2035,
            asset_name="Primary Home",
            tags=["Housing"],
        )
        assert event.sale_price is None
        assert event.mortgage_payoff is True  # default

    def test_event_tags_required(self):
        """Event with empty tags is now allowed (backward compatibility)."""
        event = CashStreamEventConfig(
            id="test",
            name="Test",
            category="income",
            start_year=2026,
            end_year=2030,
            base_amount=1000.0,
            tags=[],
        )
        assert event.tags == []

    def test_event_invalid_tag(self):
        """Event with invalid tag should raise."""
        with pytest.raises(ValidationError):
            CashStreamEventConfig(
                id="test",
                name="Test",
                category="income",
                start_year=2026,
                end_year=2030,
                base_amount=1000.0,
                tags=["NotARealTag"],
            )

    def test_event_multiple_tags(self):
        """Event with multiple valid tags."""
        event = CashStreamEventConfig(
            id="maternity",
            name="Maternity",
            category="expense",
            start_year=2027,
            end_year=2027,
            base_amount=4000.0,
            tags=["Healthcare", "Life Events", "Children"],
        )
        assert set(event.tags) == {"Healthcare", "Life Events", "Children"}


class TestScenarioConfig:
    """Tests for full ScenarioConfig validation."""

    def test_minimal_valid_scenario(self):
        """Minimal valid scenario."""
        scenario = ScenarioConfig(
            meta=MetaConfig(
                scenario_name="Minimal",
                start_year=2026,
                end_year=2030,
            ),
            accounts=[
                AccountConfig(id="checking", name="Checking", type="liquid", balance=10000.0)
            ],
            waterfall_strategy=WaterfallStrategyConfig(
                surplus_allocation=[SurplusAllocationItem(account_id="checking")],
                deficit_drawdown_order=[DeficitDrawdownItem(account_id="checking")],
            ),
            events=[],
        )
        assert scenario.meta.scenario_name == "Minimal"
        assert len(scenario.accounts) == 1

    def test_full_scenario_from_yaml(self):
        """Full scenario loaded from YAML."""
        yaml_str = """
        version: "1.0"
        meta:
          scenario_name: "Full Test"
          start_year: 2026
          end_year: 2030
          tax_status: "MFJ"
        macroeconomics:
          general_inflation_rate: 0.025
          growth_rates:
            equities: 0.07
        tax_rules:
          federal:
            standard_deduction: 32200
            brackets:
              - limit: 24800
                rate: 0.10
              - limit: .inf
                rate: 0.12
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
          - id: "salary"
            name: "Salary"
            type: "cash_stream"
            category: "income"
            start_year: 2026
            end_year: 2030
            base_amount: 100000.0
            tags: ["Investments"]
        """
        config = load_scenario_from_yaml(yaml.safe_load(yaml_str))
        assert config.meta.scenario_name == "Full Test"
        assert config.macroeconomics.general_inflation_rate == 0.025
        assert len(config.events) == 1

    def test_extra_fields_forbidden(self):
        """Extra fields in scenario should be forbidden."""
        with pytest.raises(ValidationError):
            ScenarioConfig(
                meta=MetaConfig(
                    scenario_name="Test",
                    start_year=2026,
                    end_year=2030,
                ),
                accounts=[],
                waterfall_strategy=WaterfallStrategyConfig(),
                events=[],
                unknown_field="not_allowed",
            )


class TestTagValidation:
    """Tests for Tag literal validation."""

    def test_all_valid_tags(self):
        """All defined tags should be valid."""
        valid_tags = [
            "Children", "Food & Living", "Healthcare", "Housing", "Insurance",
            "Investments", "Legal", "Life Events", "Pets", "Taxes",
            "Technology", "Transportation", "Travel & Discretionary", "Utilities",
        ]
        for tag in valid_tags:
            # This just validates the literal type works
            t: Tag = tag  # type: ignore
            assert t == tag


if __name__ == "__main__":
    pytest.main([__file__, "-v"])