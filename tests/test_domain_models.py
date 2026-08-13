"""Tests for domain models."""
import pytest
from src.domain_models import AccountState, AssetState, DebtState, SimulationState


class TestAccountState:
    """Tests for AccountState dataclass."""

    def test_basic_account(self):
        """Basic account creation."""
        acc = AccountState(
            id="checking",
            name="Checking Account",
            account_type="liquid",
            balance=10000.0,
        )
        assert acc.id == "checking"
        assert acc.name == "Checking Account"
        assert acc.account_type == "liquid"
        assert acc.balance == 10000.0

    def test_account_with_optional_fields(self):
        """Account with all optional fields."""
        acc = AccountState(
            id="brokerage",
            name="Brokerage",
            account_type="taxable_brokerage",
            balance=50000.0,
            growth_rate_ref="equities",
            is_cash_reserve=False,
            min_target_balance=0.0,
            cost_basis=40000.0,
        )
        assert acc.growth_rate_ref == "equities"
        assert acc.is_cash_reserve is False
        assert acc.min_target_balance == 0.0
        assert acc.cost_basis == 40000.0

    def test_cash_reserve_account(self):
        """Cash reserve account with min target balance."""
        acc = AccountState(
            id="checking",
            name="Checking",
            account_type="liquid",
            balance=15000.0,
            is_cash_reserve=True,
            min_target_balance=10000.0,
        )
        assert acc.is_cash_reserve is True
        assert acc.min_target_balance == 10000.0


class TestAssetState:
    """Tests for AssetState dataclass."""

    def test_basic_asset(self):
        """Basic asset creation."""
        asset = AssetState(
            id="primary_home",
            name="Primary Home",
            value=300000.0,
        )
        assert asset.id == "primary_home"
        assert asset.name == "Primary Home"
        assert asset.value == 300000.0

    def test_asset_with_growth_and_costs(self):
        """Asset with growth rate and recurring costs."""
        asset = AssetState(
            id="primary_home",
            name="Primary Home",
            value=300000.0,
            growth_rate_ref="real_estate",
            cost_basis=300000.0,
            recurring_costs={"maintenance": 0.01, "property_tax": 0.015},
        )
        assert asset.growth_rate_ref == "real_estate"
        assert asset.cost_basis == 300000.0
        assert asset.recurring_costs == {"maintenance": 0.01, "property_tax": 0.015}

    def test_asset_empty_costs_default(self):
        """Asset should have empty recurring_costs by default."""
        asset = AssetState(
            id="primary_home",
            name="Primary Home",
            value=300000.0,
        )
        assert asset.recurring_costs == {}


class TestDebtState:
    """Tests for DebtState dataclass."""

    def test_basic_debt(self):
        """Basic debt creation."""
        debt = DebtState(
            id="mortgage",
            name="Home Mortgage",
            principal=250000.0,
            interest_rate=0.06,
            term_years=30,
            remaining_years=30,
        )
        assert debt.id == "mortgage"
        assert debt.name == "Home Mortgage"
        assert debt.principal == 250000.0
        assert debt.interest_rate == 0.06
        assert debt.term_years == 30
        assert debt.remaining_years == 30


class TestSimulationState:
    """Tests for SimulationState dataclass."""

    def test_basic_state(self):
        """Basic simulation state creation."""
        state = SimulationState(
            current_year=2026,
        )
        assert state.current_year == 2026
        assert state.accounts == {}
        assert state.assets == {}
        assert state.debts == {}

    def test_state_with_accounts(self):
        """State with accounts."""
        accounts = {
            "checking": AccountState(
                id="checking", name="Checking", account_type="liquid", balance=10000.0
            ),
        }
        state = SimulationState(
            current_year=2026,
            accounts=accounts,
        )
        assert "checking" in state.accounts
        assert state.accounts["checking"].balance == 10000.0

    def test_state_with_assets_and_debts(self):
        """State with assets and debts."""
        assets = {
            "primary_home": AssetState(
                id="primary_home", name="Primary Home", value=300000.0
            ),
        }
        debts = {
            "mortgage": DebtState(
                id="mortgage", name="Home Mortgage", principal=250000.0,
                interest_rate=0.06, term_years=30, remaining_years=30
            ),
        }
        state = SimulationState(
            current_year=2026,
            assets=assets,
            debts=debts,
        )
        assert "primary_home" in state.assets
        assert "mortgage" in state.debts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])