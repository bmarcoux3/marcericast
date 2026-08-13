from typing import Dict, List
from src.domain_models import SimulationState, AccountState
from src.schema import WaterfallStrategyConfig, SurplusAllocationItem, DeficitDrawdownItem


class WaterfallResolver:
    """
    Handles cash flow surplus allocation and deficit liquidation routing across accounts
    strictly according to WaterfallStrategyConfig.
    """

    def __init__(self, strategy: WaterfallStrategyConfig):
        self.strategy = strategy

    def resolve_surplus(self, surplus_amount: float, accounts: Dict[str, AccountState]) -> float:
        """
        Allocates surplus cash flow across accounts in order of surplus_allocation items.
        Returns any remaining unallocated surplus (e.g. if contribution limits are reached).
        Negative surplus is treated as zero.
        """
        remaining_surplus = max(0.0, surplus_amount)

        for item in self.strategy.surplus_allocation:
            if remaining_surplus <= 0:
                break

            account = accounts.get(item.account_id)
            if not account:
                continue

            allocation = min(remaining_surplus, item.max_annual_contribution)
            account.balance += allocation
            remaining_surplus -= allocation

        return remaining_surplus

    def resolve_deficit(self, deficit_amount: float, accounts: Dict[str, AccountState]) -> float:
        """
        Liquidates cash from accounts to cover a deficit in order of deficit_drawdown_order.
        Cash reserve accounts respect min_target_balance.
        Returns any remaining uncovered deficit.
        Negative deficit is treated as zero.
        """
        remaining_deficit = max(0.0, deficit_amount)

        for item in self.strategy.deficit_drawdown_order:
            if remaining_deficit <= 0:
                break

            account = accounts.get(item.account_id)
            if not account:
                continue

            # Calculate available funds for drawdown
            if account.is_cash_reserve:
                available_funds = max(0.0, account.balance - account.min_target_balance)
            else:
                available_funds = max(0.0, account.balance)

            drawdown = min(remaining_deficit, available_funds)
            account.balance -= drawdown
            remaining_deficit -= drawdown

        return remaining_deficit

    def rebalance_excess(self, accounts: Dict[str, AccountState]) -> None:
        """
        Rebalances accounts that exceed their max_target_balance by moving excess
        to the next account in the surplus_allocation order.
        This is called after growth compounding and surplus resolution.
        """
        # Get ordered list of surplus allocation account IDs
        surplus_account_ids = [item.account_id for item in self.strategy.surplus_allocation]

        for i, account_id in enumerate(surplus_account_ids):
            account = accounts.get(account_id)
            if not account or account.max_target_balance <= 0:
                continue

            if account.balance > account.max_target_balance:
                excess = account.balance - account.max_target_balance
                account.balance = account.max_target_balance

                # Find the next account in the surplus allocation chain to receive the excess
                for next_account_id in surplus_account_ids[i + 1:]:
                    next_account = accounts.get(next_account_id)
                    if next_account:
                        next_account.balance += excess
                        break
