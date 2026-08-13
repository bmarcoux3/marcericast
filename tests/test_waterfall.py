"""Tests for waterfall allocation logic."""
import pytest
from src.domain_models import AccountState
from src.schema import WaterfallStrategyConfig, SurplusAllocationItem, DeficitDrawdownItem
from src.waterfall import WaterfallResolver


class TestSurplusAllocation:
    """Tests for surplus allocation."""

    def test_simple_surplus_allocation(self):
        """Simple surplus allocation to single account."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        unallocated = resolver.resolve_surplus(10000.0, accounts)

        # Full 10000 surplus allocated -> nothing left
        assert unallocated == 0.0
        # 50000 + 10000 = 60000
        assert accounts["brokerage"].balance == 60000.0

    def test_surplus_allocation_with_cap(self):
        """Surplus allocation with contribution cap."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="401k", max_annual_contribution=20000.0),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "401k": AccountState(id="401k", name="401k", account_type="traditional_401k", balance=100000.0),
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        # Surplus of $35,000 -> $20,000 to 401k, $15,000 to brokerage
        unallocated = resolver.resolve_surplus(35000.0, accounts)

        # 35000 - 20000 - 15000 = 0 left
        assert unallocated == 0.0
        # 100000 + 20000 = 120000
        assert accounts["401k"].balance == 120000.0
        # 50000 + 15000 = 65000
        assert accounts["brokerage"].balance == 65000.0

    def test_surplus_exceeds_all_caps(self):
        """Surplus exceeding all caps returns unallocated."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="401k", max_annual_contribution=20000.0),
                SurplusAllocationItem(account_id="ira", max_annual_contribution=6000.0),
            ]
        )
        accounts = {
            "401k": AccountState(id="401k", name="401k", account_type="traditional_401k", balance=100000.0),
            "ira": AccountState(id="ira", name="IRA", account_type="roth_ira", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        # Surplus of $30,000 -> $20,000 to 401k, $6,000 to IRA, $4,000 unallocated
        unallocated = resolver.resolve_surplus(30000.0, accounts)

        # 30000 - 20000 (401k cap) - 6000 (IRA cap) = 4000 unallocated
        assert unallocated == 4000.0
        # 100000 + 20000 = 120000
        assert accounts["401k"].balance == 120000.0
        # 50000 + 6000 = 56000
        assert accounts["ira"].balance == 56000.0

    def test_surplus_skips_missing_accounts(self):
        """Missing accounts should be skipped."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="missing", max_annual_contribution=10000.0),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        unallocated = resolver.resolve_surplus(5000.0, accounts)

        # 5000 surplus fully routed to brokerage (missing account skipped)
        assert unallocated == 0.0
        # 50000 + 5000 = 55000
        assert accounts["brokerage"].balance == 55000.0

    def test_zero_surplus(self):
        """Zero surplus should not change accounts."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        unallocated = resolver.resolve_surplus(0.0, accounts)

        # Zero surplus -> nothing to allocate
        assert unallocated == 0.0
        # Unchanged: 50000 + 0 = 50000
        assert accounts["brokerage"].balance == 50000.0

    def test_negative_surplus(self):
        """Negative surplus should be treated as zero."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        unallocated = resolver.resolve_surplus(-1000.0, accounts)

        # Negative surplus treated as zero -> nothing allocated
        assert unallocated == 0.0
        # Unchanged: 50000
        assert accounts["brokerage"].balance == 50000.0


class TestDeficitDrawdown:
    """Tests for deficit drawdown."""

    def test_simple_deficit_drawdown(self):
        """Simple deficit drawdown from single account."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
            ]
        )
        accounts = {
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=15000.0),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(5000.0, accounts)

        # 5000 deficit fully covered by checking
        assert uncovered == 0.0
        # 15000 - 5000 = 10000
        assert accounts["checking"].balance == 10000.0

    def test_deficit_drawdown_respects_cash_reserve(self):
        """Cash reserve accounts should respect min_target_balance."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
                DeficitDrawdownItem(account_id="brokerage"),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=15000.0,
                is_cash_reserve=True,
                min_target_balance=10000.0,
            ),
            "brokerage": AccountState(
                id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0
            ),
        }
        resolver = WaterfallResolver(strategy)

        # Deficit of $20,000 -> Checking has $5,000 available ($15,000 - $10,000 min)
        # Remaining $15,000 drawn from Brokerage
        uncovered = resolver.resolve_deficit(20000.0, accounts)

        # 20000 - 5000 (checking drawable) - 15000 (brokerage) = 0 uncovered
        assert uncovered == 0.0
        # 15000 - 5000 drawable = 10000 (min target preserved)
        assert accounts["checking"].balance == 10000.0  # Min target preserved
        # 50000 - 15000 = 35000
        assert accounts["brokerage"].balance == 35000.0

    def test_deficit_drawdown_exceeds_all_accounts(self):
        """Deficit exceeding all available funds returns uncovered amount."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
                DeficitDrawdownItem(account_id="brokerage"),
            ]
        )
        accounts = {
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=5000.0),
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=10000.0),
        }
        resolver = WaterfallResolver(strategy)

        # Deficit of $20,000 but only $15,000 available
        uncovered = resolver.resolve_deficit(20000.0, accounts)

        # 20000 deficit - 5000 (checking) - 10000 (brokerage) = 5000 uncovered
        assert uncovered == 5000.0
        # 5000 fully drained
        assert accounts["checking"].balance == 0.0
        # 10000 fully drained
        assert accounts["brokerage"].balance == 0.0

    def test_deficit_skips_missing_accounts(self):
        """Missing accounts in drawdown order should be skipped."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="missing"),
                DeficitDrawdownItem(account_id="brokerage"),
            ]
        )
        accounts = {
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(10000.0, accounts)

        # 10000 deficit fully covered from brokerage (missing account skipped)
        assert uncovered == 0.0
        # 50000 - 10000 = 40000
        assert accounts["brokerage"].balance == 40000.0

    def test_zero_deficit(self):
        """Zero deficit should not change accounts."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
            ]
        )
        accounts = {
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=15000.0),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(0.0, accounts)

        # Zero deficit -> nothing drawn
        assert uncovered == 0.0
        # Unchanged: 15000
        assert accounts["checking"].balance == 15000.0

    def test_negative_deficit(self):
        """Negative deficit should be treated as zero."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
            ]
        )
        accounts = {
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=15000.0),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(-1000.0, accounts)

        # Negative deficit treated as zero -> nothing drawn
        assert uncovered == 0.0
        # Unchanged: 15000
        assert accounts["checking"].balance == 15000.0

    def test_cash_reserve_exact_balance(self):
        """Cash reserve at exact min target should not be drawn from."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
                DeficitDrawdownItem(account_id="brokerage"),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=10000.0,
                is_cash_reserve=True,
                min_target_balance=10000.0,
            ),
            "brokerage": AccountState(
                id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0
            ),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(5000.0, accounts)

        # 5000 deficit fully covered from brokerage
        assert uncovered == 0.0
        # 10000 - 0 drawable (at min target) = 10000
        assert accounts["checking"].balance == 10000.0  # Unchanged
        # 50000 - 5000 = 45000
        assert accounts["brokerage"].balance == 45000.0

    def test_cash_reserve_below_min_target(self):
        """Cash reserve already below min target should not be drawn further."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
                DeficitDrawdownItem(account_id="brokerage"),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=5000.0,  # Already below min
                is_cash_reserve=True,
                min_target_balance=10000.0,
            ),
            "brokerage": AccountState(
                id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0
            ),
        }
        resolver = WaterfallResolver(strategy)

        uncovered = resolver.resolve_deficit(5000.0, accounts)

        # 5000 deficit fully covered from brokerage
        assert uncovered == 0.0
        # 5000 - 0 drawable (below min target) = 5000
        assert accounts["checking"].balance == 5000.0  # Unchanged (available = 0)
        # 50000 - 5000 = 45000
        assert accounts["brokerage"].balance == 45000.0


class TestWaterfallIntegration:
    """Integration tests for combined surplus/deficit scenarios."""

    def test_surplus_then_deficit_same_year(self):
        """Running surplus then deficit in sequence."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ],
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="checking"),
            ]
        )
        accounts = {
            "checking": AccountState(id="checking", name="Checking", account_type="liquid", balance=10000.0),
            "brokerage": AccountState(id="brokerage", name="Brokerage", account_type="taxable_brokerage", balance=50000.0),
        }
        resolver = WaterfallResolver(strategy)

        # 5000 surplus fully allocated to brokerage
        unallocated = resolver.resolve_surplus(5000.0, accounts)
        assert unallocated == 0.0
        # 50000 + 5000 = 55000
        assert accounts["brokerage"].balance == 55000.0

        # Then deficit (new resolver or same - stateless)
        uncovered = resolver.resolve_deficit(3000.0, accounts)
        # 3000 deficit fully covered from checking
        assert uncovered == 0.0
        # 10000 - 3000 = 7000
        assert accounts["checking"].balance == 7000.0
        # Brokerage untouched by drawdown: 55000
        assert accounts["brokerage"].balance == 55000.0

    def test_order_matters_in_surplus(self):
        """Order of surplus allocation matters when caps exist."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="limited", max_annual_contribution=1000.0),
                SurplusAllocationItem(account_id="unlimited", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "limited": AccountState(id="limited", name="Limited", account_type="traditional_401k", balance=0.0),
            "unlimited": AccountState(id="unlimited", name="Unlimited", account_type="taxable_brokerage", balance=0.0),
        }
        resolver = WaterfallResolver(strategy)

        # $5000 surplus -> $1000 to limited, $4000 to unlimited
        resolver.resolve_surplus(5000.0, accounts)

        # 0 + 1000 = 1000 (capped at max_annual_contribution 1000)
        assert accounts["limited"].balance == 1000.0
        # 0 + 4000 = 4000 (remaining surplus)
        assert accounts["unlimited"].balance == 4000.0

    def test_order_matters_in_deficit(self):
        """Order of deficit drawdown matters."""
        strategy = WaterfallStrategyConfig(
            deficit_drawdown_order=[
                DeficitDrawdownItem(account_id="first"),
                DeficitDrawdownItem(account_id="second"),
            ]
        )
        accounts = {
            "first": AccountState(id="first", name="First", account_type="liquid", balance=1000.0),
            "second": AccountState(id="second", name="Second", account_type="liquid", balance=10000.0),
        }
        resolver = WaterfallResolver(strategy)

        # $5000 deficit -> $1000 from first, $4000 from second
        resolver.resolve_deficit(5000.0, accounts)

        # 1000 fully drained
        assert accounts["first"].balance == 0.0
        # 10000 - 4000 = 6000
        assert accounts["second"].balance == 6000.0


class TestRebalanceExcess:
    """Tests for rebalance_excess functionality."""

    def test_rebalance_excess_moves_to_next_account(self):
        """Excess from first account should move to second account."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=75000.0,
                max_target_balance=50000.0,
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=100000.0,
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # 75000 - 25000 excess (above 50000 max) = 50000
        assert accounts["checking"].balance == 50000.0
        assert accounts["brokerage"].balance == 125000.0  # 100000 + 25000 excess

    def test_rebalance_excess_no_change_when_under_max(self):
        """Accounts under max_target_balance should not be rebalanced."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=30000.0,
                max_target_balance=50000.0,
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=100000.0,
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # 30000 < max 50000 -> no excess, unchanged
        assert accounts["checking"].balance == 30000.0
        # Brokerage unchanged
        assert accounts["brokerage"].balance == 100000.0

    def test_rebalance_excess_zero_max_means_no_limit(self):
        """max_target_balance of 0 should mean no limit."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=75000.0,
                max_target_balance=0.0,  # No limit
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=100000.0,
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # max_target_balance 0 = no limit -> nothing moved, unchanged
        assert accounts["checking"].balance == 75000.0
        # Brokerage unchanged
        assert accounts["brokerage"].balance == 100000.0

    def test_rebalance_excess_multiple_accounts(self):
        """Rebalance should cascade through multiple accounts."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="savings", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=75000.0,
                max_target_balance=50000.0,
            ),
            "savings": AccountState(
                id="savings",
                name="Savings",
                account_type="liquid",
                balance=30000.0,
                max_target_balance=25000.0,
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=100000.0,
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # Checking: 75000 -> 50000, excess 25000 to savings
        # Savings: 30000 + 25000 = 55000 -> 25000, excess 30000 to brokerage
        # Brokerage: 100000 + 30000 = 130000
        assert accounts["checking"].balance == 50000.0
        assert accounts["savings"].balance == 25000.0
        assert accounts["brokerage"].balance == 130000.0

    def test_rebalance_excess_last_account_respects_its_max(self):
        """Last account in chain also respects its own max_target_balance."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=75000.0,
                max_target_balance=50000.0,
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=200000.0,
                max_target_balance=100000.0,  # Also respects its max
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # 75000 - 50000 = 25000 excess moves from checking to brokerage
        assert accounts["checking"].balance == 50000.0
        # Brokerage: 200000 + 25000 = 225000, but capped at its own max 100000;
        # the remaining 125000 excess is dropped (no further account to spill to)
        assert accounts["brokerage"].balance == 100000.0

    def test_rebalance_excess_missing_accounts_skipped(self):
        """Missing accounts in chain should be skipped."""
        strategy = WaterfallStrategyConfig(
            surplus_allocation=[
                SurplusAllocationItem(account_id="checking", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="missing", max_annual_contribution=float("inf")),
                SurplusAllocationItem(account_id="brokerage", max_annual_contribution=float("inf")),
            ]
        )
        accounts = {
            "checking": AccountState(
                id="checking",
                name="Checking",
                account_type="liquid",
                balance=75000.0,
                max_target_balance=50000.0,
            ),
            "brokerage": AccountState(
                id="brokerage",
                name="Brokerage",
                account_type="taxable_brokerage",
                balance=100000.0,
            ),
        }
        resolver = WaterfallResolver(strategy)

        resolver.rebalance_excess(accounts)

        # 75000 - 50000 = 25000 excess from checking
        assert accounts["checking"].balance == 50000.0
        # 25000 skips the missing account and lands in brokerage: 100000 + 25000 = 125000
        assert accounts["brokerage"].balance == 125000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])