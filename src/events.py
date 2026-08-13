from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union
from src.domain_models import SimulationState, AssetState, DebtState
from src.schema import (
    BaseEventConfig,
    CashStreamEventConfig,
    AssetPurchaseEventConfig,
    AccountLiquidationEventConfig,
    AssetLiquidationEventConfig,
    MacroeconomicsConfig,
    EventConfigUnion,
)
from src.inflation import calculate_inflated_amount


@dataclass
class EventImpact:
    gross_taxable_income: float = 0.0
    non_taxable_income: float = 0.0
    cash_inflow: float = 0.0  # Actual cash received (excludes capital gains)
    pre_tax_deductions: float = 0.0
    post_tax_expenses: float = 0.0
    # Capital gains from asset liquidation. Kept separate from gross_taxable_income
    # so the engine can apply capital-gains bracket rates instead of ordinary rates.
    # gross_taxable_income still includes the gain for reporting (AGI/Gross Taxable
    # Income columns), but the tax engine splits it out.
    capital_gains: float = 0.0
    future_events: List[Dict] = field(default_factory=list)
    # Fee breakdowns for detailed column output in simulation results
    purchase_fees: Dict[str, float] = field(default_factory=dict)  # fee_type -> amount
    sale_fees: Dict[str, float] = field(default_factory=dict)      # fee_type -> amount

    @property
    def total_inflow(self) -> float:
        return self.gross_taxable_income + self.non_taxable_income

    @property
    def total_outflow(self) -> float:
        return self.pre_tax_deductions + self.post_tax_expenses

    @property
    def net_cash_flow(self) -> float:
        # Use actual cash inflow, not taxable income (which includes capital gains)
        return self.cash_inflow - self.total_outflow


class BaseEvent(ABC):
    def __init__(self, config: BaseEventConfig):
        self.config = config

    @abstractmethod
    def evaluate(self, state: SimulationState, macro: MacroeconomicsConfig) -> EventImpact:
        pass


class CashStreamEvent(BaseEvent):
    def __init__(self, config: CashStreamEventConfig):
        super().__init__(config)
        self.config: CashStreamEventConfig = config

    def evaluate(self, state: SimulationState, macro: MacroeconomicsConfig) -> EventImpact:
        impact = EventImpact()
        current_year = state.current_year

        if current_year < self.config.start_year or current_year > self.config.end_year:
            return impact

        if current_year in self.config.gap_years:
            return impact

        # Determine inflation rate
        inflation_rate = 0.0
        if self.config.inflation_ref:
            if self.config.inflation_ref == "general_inflation_rate":
                inflation_rate = macro.general_inflation_rate
            else:
                inflation_rate = macro.growth_rates.get(self.config.inflation_ref, 0.0)

        # Resolve step adjustments (multiplier applied based on most recent step year <= current_year)
        multiplier = 1.0
        past_steps = [mult for y, mult in sorted(self.config.step_adjustments.items()) if y <= current_year]
        if past_steps:
            multiplier = past_steps[-1]

        amount = calculate_inflated_amount(
            base_amount=self.config.base_amount,
            current_year=current_year,
            reference_year=self.config.reference_year,
            inflation_rate=inflation_rate,
            multiplier=multiplier,
        )

        if self.config.category == "income":
            if self.config.is_taxable_income:
                impact.gross_taxable_income += amount
            else:
                impact.non_taxable_income += amount
            impact.cash_inflow += amount
        elif self.config.category == "expense":
            if self.config.is_pre_tax_deduction:
                impact.pre_tax_deductions += amount
            else:
                impact.post_tax_expenses += amount

        # Target account payroll transfers (e.g. 401k pre-tax contributions).
        # Only expense cash streams may credit a target account directly: for an
        # income event the amount already reaches accounts via the waterfall
        # (Net Cash Flow -> surplus allocation), so crediting the target here too
        # would create money from nothing.
        if (
            self.config.category == "expense"
            and self.config.target_account_id
            and self.config.target_account_id in state.accounts
        ):
            state.accounts[self.config.target_account_id].balance += amount

        return impact


class AssetPurchaseEvent(BaseEvent):
    def __init__(self, config: AssetPurchaseEventConfig):
        super().__init__(config)
        self.config: AssetPurchaseEventConfig = config

    def evaluate(self, state: SimulationState, macro: MacroeconomicsConfig) -> EventImpact:
        impact = EventImpact()
        if state.current_year != self.config.trigger_year:
            return impact

        # Down payment handling (existing)
        impact.post_tax_expenses += self.config.down_payment

        # Purchase fees (one-time) - track breakdown for detailed columns
        purchase_price = self.config.asset_initial_value
        for fee_type, percentage in self.config.purchase_fees.items():
            fee_amount = purchase_price * percentage
            impact.purchase_fees[fee_type] = fee_amount
            impact.post_tax_expenses += fee_amount

        # Create new asset in simulation state
        asset_id = self._generate_asset_id(state.assets)
        state.assets[asset_id] = AssetState(
            id=asset_id,
            name=self.config.asset_name,
            value=self.config.asset_initial_value,
            growth_rate_ref=self.config.growth_rate_ref,
            cost_basis=self.config.asset_initial_value,
            recurring_costs=dict(self.config.costs) if self.config.costs else {},
        )

        # Process mortgage if present
        if self.config.mortgage:
            self._create_mortgage(state.debts)

        return impact

    def _generate_asset_id(self, existing_assets: Dict) -> str:
        """Generate a unique asset ID based on asset name."""
        asset_id = self.config.asset_name.lower().replace(" ", "_")
        if not asset_id or asset_id in existing_assets:
            asset_id = f"{asset_id}_{self.config.trigger_year}"
        return asset_id

    def _create_mortgage(self, debts: Dict) -> None:
        """Create mortgage debt liability if present in config."""
        if not self.config.mortgage:
            return
        asset_id = self._generate_asset_id({})
        debt_id = f"{asset_id}_mortgage"
        debts[debt_id] = DebtState(
            id=debt_id,
            name=f"{self.config.asset_name} Mortgage",
            principal=self.config.mortgage.principal,
            interest_rate=self.config.mortgage.interest_rate,
            term_years=self.config.mortgage.term_years,
            remaining_years=self.config.mortgage.term_years,
        )


class AccountLiquidationEvent(BaseEvent):
    def __init__(self, config: AccountLiquidationEventConfig):
        super().__init__(config)
        self.config: AccountLiquidationEventConfig = config

    def evaluate(self, state: SimulationState, macro: MacroeconomicsConfig) -> EventImpact:
        impact = EventImpact()
        if state.current_year != self.config.trigger_year:
            return impact

        source = state.accounts.get(self.config.source_account_id)
        target = state.accounts.get(self.config.target_account_id)

        if source and target:
            actual_amount = min(self.config.amount, source.balance)
            source.balance -= actual_amount
            target.balance += actual_amount

        return impact


class AssetLiquidationEvent(BaseEvent):
    def __init__(self, config: AssetLiquidationEventConfig):
        super().__init__(config)
        self.config: AssetLiquidationEventConfig = config

    def evaluate(self, state: SimulationState, macro: MacroeconomicsConfig) -> EventImpact:
        impact = EventImpact()
        if state.current_year != self.config.trigger_year:
            return impact

        # Find the asset by name (asset_id is generated from name)
        asset_id = self.config.asset_name.lower().replace(" ", "_")
        if asset_id not in state.assets:
            # Try with year suffix if multiple assets with same name
            for aid, asset in state.assets.items():
                if asset.name == self.config.asset_name:
                    asset_id = aid
                    break

        if asset_id not in state.assets:
            return impact

        asset = state.assets[asset_id]

        # Determine sale price
        sale_price = self.config.sale_price if self.config.sale_price is not None else asset.value

        # Sale fees (one-time) - track breakdown for detailed columns
        total_fees = 0.0
        for fee_type, percentage in self.config.sale_fees.items():
            fee_amount = sale_price * percentage
            impact.sale_fees[fee_type] = fee_amount
            total_fees += fee_amount
            impact.post_tax_expenses += fee_amount

        # Calculate capital gain/loss
        cost_basis = asset.cost_basis
        capital_gain = sale_price - cost_basis

        # Apply IRS Sec. 121 primary-residence exclusion (e.g., 500k MFJ) to the gain
        taxable_gain = max(0.0, capital_gain - self.config.primary_residence_exclusion)

        if taxable_gain > 0:
            impact.gross_taxable_income += taxable_gain
            impact.capital_gains += taxable_gain
        # For simplicity, we're not handling capital losses here

        # Calculate gross proceeds (before fees)
        mortgage_id = f"{asset_id}_mortgage"
        mortgage_balance = 0.0
        if mortgage_id in state.debts:
            mortgage = state.debts[mortgage_id]
            mortgage_balance = mortgage.principal

        # If mortgage_payoff is False, the buyer keeps the full sale price and
        # the outstanding mortgage remains on the books as an ongoing liability.
        if self.config.mortgage_payoff:
            gross_proceeds = sale_price - mortgage_balance
        else:
            gross_proceeds = sale_price

        # Net proceeds go to cash inflow for system net cash flow
        # Fees are handled via post_tax_expenses (added above in the fee loop)
        # This allows waterfall to distribute per strategy via net_operating_cash_flow
        impact.cash_inflow += gross_proceeds

        # Pay off mortgage directly from proceeds (reduces debt) unless flag is False
        if mortgage_balance > 0 and self.config.mortgage_payoff:
            del state.debts[mortgage_id]

        # Remove the asset - this stops recurring costs
        del state.assets[asset_id]

        return impact


class EventRegistry:
    @staticmethod
    def from_config(config: EventConfigUnion) -> BaseEvent:
        if isinstance(config, CashStreamEventConfig):
            return CashStreamEvent(config)
        elif isinstance(config, AssetPurchaseEventConfig):
            return AssetPurchaseEvent(config)
        elif isinstance(config, AccountLiquidationEventConfig):
            return AccountLiquidationEvent(config)
        elif isinstance(config, AssetLiquidationEventConfig):
            return AssetLiquidationEvent(config)
        else:
            raise TypeError(f"Unsupported event config type: {type(config)}")

    @staticmethod
    def from_configs(configs: List[EventConfigUnion]) -> List[BaseEvent]:
        return [EventRegistry.from_config(c) for c in configs]
