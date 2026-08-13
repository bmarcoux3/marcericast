from typing import List, Dict, Optional, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Tag taxonomy
# ---------------------------------------------------------------------------

# Flat tag vocabulary applied to events. An event may carry multiple tags;
# totals per tag represent "spend associated with X" and should NOT be summed
# across tags to avoid double-counting.
Tag = Literal[
    "Children",
    "Food & Living",
    "Healthcare",
    "Housing",
    "Insurance",
    "Investments",
    "Legal",
    "Life Events",
    "Pets",
    "Taxes",
    "Technology",
    "Transportation",
    "Travel & Discretionary",
    "Utilities",
]


class TaxBracket(BaseModel):
    limit: float
    rate: float

    model_config = ConfigDict(extra="forbid")


class FederalTaxRules(BaseModel):
    standard_deduction: float = 0.0
    brackets: List[TaxBracket] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CapitalGainsTaxRules(BaseModel):
    brackets: List[TaxBracket] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TaxRulesConfig(BaseModel):
    inflate_brackets: bool = True
    reference_year: Optional[int] = 2026
    inflation_ref: str = "general_inflation_rate"
    federal: FederalTaxRules = Field(default_factory=FederalTaxRules)
    capital_gains: CapitalGainsTaxRules = Field(default_factory=CapitalGainsTaxRules)

    model_config = ConfigDict(extra="forbid")


class MacroeconomicsConfig(BaseModel):
    general_inflation_rate: float = 0.0
    growth_rates: Dict[str, float] = Field(default_factory=dict)
    # Age-based derisking: maps age to growth rate key for portfolio
    # e.g., {"equities": {"start_age": 60, "end_age": 80, "transition_to": "bonds"}}
    derisking_schedule: Dict[str, Dict[str, Union[int, str]]] = Field(
        default_factory=dict,
        description="Maps growth_rate_ref to derisking rules: {start_age, end_age, transition_to}"
    )

    @model_validator(mode="after")
    def validate_derisking_schedule(self) -> "MacroeconomicsConfig":
        for rate_ref, schedule in self.derisking_schedule.items():
            start_age = schedule.get("start_age")
            end_age = schedule.get("end_age")
            if isinstance(start_age, int) and isinstance(end_age, int) and end_age <= start_age:
                raise ValueError(
                    f"derisking_schedule for '{rate_ref}' must have end_age > start_age "
                    f"(got start_age={start_age}, end_age={end_age})"
                )
        return self

    model_config = ConfigDict(extra="forbid")


class MetaConfig(BaseModel):
    scenario_name: str
    start_year: int
    end_year: int
    time_step: Literal["annual", "monthly"] = "annual"
    tax_status: Literal["Single", "MFJ", "MFS", "HeadOfHousehold"] = "MFJ"
    # Birth year for age calculation (used for derisking)
    birth_year: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def check_years(self) -> "MetaConfig":
        if self.end_year < self.start_year:
            raise ValueError(f"end_year ({self.end_year}) cannot be earlier than start_year ({self.start_year})")
        return self


class AccountConfig(BaseModel):
    id: str
    name: str
    type: Literal["liquid", "taxable_brokerage", "traditional_401k", "roth_ira", "debt"]
    balance: float = 0.0
    growth_rate_ref: Optional[str] = None
    is_cash_reserve: bool = False
    min_target_balance: float = 0.0
    max_target_balance: float = 0.0
    cost_basis: float = 0.0

    model_config = ConfigDict(extra="forbid")


class SurplusAllocationItem(BaseModel):
    account_id: str
    max_annual_contribution: float = float("inf")

    model_config = ConfigDict(extra="forbid")


class DeficitDrawdownItem(BaseModel):
    account_id: str

    model_config = ConfigDict(extra="forbid")


class WaterfallStrategyConfig(BaseModel):
    surplus_allocation: List[SurplusAllocationItem] = Field(default_factory=list)
    deficit_drawdown_order: List[DeficitDrawdownItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


# Polymorphic Event Models
class BaseEventConfig(BaseModel):
    id: str
    name: str
    type: str
    # Tags are optional for backward compatibility. Multiple tags are allowed; tag totals
    # represent filtered views and should not be summed to avoid double-counting.
    tags: List[Tag] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CashStreamEventConfig(BaseEventConfig):
    type: Literal["cash_stream"] = "cash_stream"
    category: Literal["income", "expense"]
    start_year: int
    end_year: int
    base_amount: float
    reference_year: Optional[int] = None
    inflation_ref: Optional[str] = None
    gap_years: List[int] = Field(default_factory=list)
    is_taxable_income: bool = False
    is_earned_income: bool = False
    is_pre_tax_deduction: bool = False
    target_account_id: Optional[str] = None
    step_adjustments: Dict[int, float] = Field(default_factory=dict)


class MortgageConfig(BaseModel):
    principal: float
    interest_rate: float
    term_years: int

    model_config = ConfigDict(extra="forbid")


class AssetPurchaseEventConfig(BaseEventConfig):
    type: Literal["asset_purchase"] = "asset_purchase"
    trigger_year: int
    down_payment: float
    asset_name: str
    asset_initial_value: float
    growth_rate_ref: Optional[str] = None
    mortgage: Optional[MortgageConfig] = None
    costs: Dict[str, float] = Field(
        default_factory=dict,
        description="Percentage-based annual costs (e.g., maintenance: 0.01 for 1%)"
    )
    purchase_fees: Dict[str, float] = Field(
        default_factory=dict,
        description="One-time purchase fees as percentage of purchase price (e.g., closing_costs: 0.03 for 3%)"
    )

    @model_validator(mode="after")
    def validate_costs(self) -> "AssetPurchaseEventConfig":
        for cost_type, percentage in self.costs.items():
            if not (0 <= percentage <= 1):
                raise ValueError(
                    f"Cost percentage for '{cost_type}' must be between 0 and 1, got {percentage}"
                )
        for fee_type, percentage in self.purchase_fees.items():
            if not (0 <= percentage <= 1):
                raise ValueError(
                    f"Purchase fee percentage for '{fee_type}' must be between 0 and 1, got {percentage}"
                )
        return self

    @model_validator(mode="after")
    def validate_funding(self) -> "AssetPurchaseEventConfig":
        """Ensure the purchase is fully funded by down payment plus mortgage."""
        mortgage_principal = self.mortgage.principal if self.mortgage else 0.0
        total_funding = self.down_payment + mortgage_principal
        if abs(total_funding - self.asset_initial_value) > 0.01:
            raise ValueError(
                f"Asset purchase '{self.name}' is not fully funded: "
                f"down_payment ({self.down_payment}) + mortgage principal ({mortgage_principal}) "
                f"= {total_funding}, but asset_initial_value is {self.asset_initial_value}. "
                f"Set down_payment to the full purchase price (buy outright) or add a mortgage "
                f"for the difference."
            )
        return self


class AccountLiquidationEventConfig(BaseEventConfig):
    type: Literal["account_liquidation"] = "account_liquidation"
    trigger_year: int
    source_account_id: str
    target_account_id: str
    amount: float


class AssetLiquidationEventConfig(BaseEventConfig):
    type: Literal["asset_liquidation"] = "asset_liquidation"
    trigger_year: int
    asset_name: str
    sale_price: Optional[float] = None  # If None, use current asset value
    mortgage_payoff: bool = True  # Whether to pay off associated mortgage
    primary_residence_exclusion: float = 0.0  # IRS Sec. 121 gain exclusion (0 = none; 500,000 for MFJ primary residence)
    sale_fees: Dict[str, float] = Field(
        default_factory=dict,
        description="One-time sale fees as percentage of sale price (e.g., agent_commission: 0.06 for 6%)"
    )

    @model_validator(mode="after")
    def validate_sale_fees(self) -> "AssetLiquidationEventConfig":
        for fee_type, percentage in self.sale_fees.items():
            if not (0 <= percentage <= 1):
                raise ValueError(
                    f"Sale fee percentage for '{fee_type}' must be between 0 and 1, got {percentage}"
                )
        return self


EventConfigUnion = Union[
    CashStreamEventConfig,
    AssetPurchaseEventConfig,
    AccountLiquidationEventConfig,
    AssetLiquidationEventConfig,
]


class ScenarioConfig(BaseModel):
    version: str = "1.0"
    meta: MetaConfig
    macroeconomics: MacroeconomicsConfig = Field(default_factory=MacroeconomicsConfig)
    tax_rules: TaxRulesConfig = Field(default_factory=TaxRulesConfig)
    accounts: List[AccountConfig] = Field(default_factory=list)
    waterfall_strategy: WaterfallStrategyConfig = Field(default_factory=WaterfallStrategyConfig)
    events: List[EventConfigUnion] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
