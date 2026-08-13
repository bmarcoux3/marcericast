from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal


@dataclass
class AccountState:
    id: str
    name: str
    account_type: Literal["liquid", "taxable_brokerage", "traditional_401k", "roth_ira", "debt"]
    balance: float
    growth_rate_ref: Optional[str] = None
    is_cash_reserve: bool = False
    min_target_balance: float = 0.0
    max_target_balance: float = 0.0
    cost_basis: float = 0.0


@dataclass
class AssetState:
    id: str
    name: str
    value: float
    growth_rate_ref: Optional[str] = None
    cost_basis: float = 0.0  # Original purchase price for capital gains
    recurring_costs: Dict[str, float] = field(default_factory=dict)  # cost_type -> percentage of asset value


@dataclass
class DebtState:
    id: str
    name: str
    principal: float
    interest_rate: float
    term_years: int
    remaining_years: int


@dataclass
class SimulationState:
    current_year: int
    accounts: Dict[str, AccountState] = field(default_factory=dict)
    assets: Dict[str, AssetState] = field(default_factory=dict)
    debts: Dict[str, DebtState] = field(default_factory=dict)
