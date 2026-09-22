import pandas as pd
from typing import List, Dict, Any, Optional
from src.schema import ScenarioConfig, Tag
from src.domain_models import SimulationState, AccountState, AssetState, DebtState
from src.tax_engine import TaxCalculator
from src.waterfall import WaterfallResolver
from src.events import EventRegistry, BaseEvent, EventImpact


def calculate_mortgage_payment(principal: float, interest_rate: float, remaining_years: int) -> float:
    """Calculate annual mortgage payment using standard amortization formula."""
    if remaining_years <= 0 or principal <= 0:
        return 0.0
    if interest_rate <= 0:
        return principal / remaining_years
    # Annual payment formula: P * r / (1 - (1 + r)^-n)
    r = interest_rate
    n = remaining_years
    payment = principal * r / (1 - (1 + r) ** -n)
    return payment


# Single consolidated debt for all uncovered deficits (revolving, no fixed term)
UNCOVERED_DEFICIT_ID = "uncovered_deficit"
UNCOVERED_DEFICIT_NAME = "Uncovered Deficit (Revolving)"
# Typical credit card rate; interest accrues on the balance each year.
UNCOVERED_DEFICIT_RATE = 0.18


class SimulationRunner:
    """
    End-to-end simulation runner executing deterministic annual financial projections
    driven strictly by a ScenarioConfig object loaded from YAML.
    """

    def __init__(self, config: ScenarioConfig):
        self.config = config
        self.tax_calculator = TaxCalculator(config.tax_rules)
        self.waterfall_resolver = WaterfallResolver(config.waterfall_strategy)
        self.events: List[BaseEvent] = EventRegistry.from_configs(config.events)
        # Pre-compute birth year for age calculation
        self.birth_year = config.meta.birth_year

    def _get_growth_rate(self, growth_rate_ref: str, current_year: int) -> float:
        """Get the effective growth rate for a given reference, considering age-based derisking."""
        if not growth_rate_ref:
            return 0.0

        base_rate = self.config.macroeconomics.growth_rates.get(growth_rate_ref, 0.0)

        # Check if derisking applies
        if not self.birth_year:
            return base_rate

        derisking = self.config.macroeconomics.derisking_schedule.get(growth_rate_ref)
        if not derisking:
            return base_rate

        current_age = current_year - self.birth_year
        start_age = derisking.get("start_age")
        end_age = derisking.get("end_age")
        transition_to = derisking.get("transition_to")

        if start_age is None or end_age is None or transition_to is None:
            return base_rate

        if current_age <= start_age:
            return base_rate
        elif current_age >= end_age:
            return self.config.macroeconomics.growth_rates.get(transition_to, 0.0)
        elif end_age <= start_age:
            # Degenerate schedule - avoid division by zero
            return base_rate
        else:
            # Linear interpolation between base rate and transition rate
            transition_rate = self.config.macroeconomics.growth_rates.get(transition_to, 0.0)
            progress = (current_age - start_age) / (end_age - start_age)
            return base_rate + progress * (transition_rate - base_rate)

    def _initialize_state(self) -> SimulationState:
        accounts = {
            acc.id: AccountState(
                id=acc.id,
                name=acc.name,
                account_type=acc.type,
                balance=acc.balance,
                growth_rate_ref=acc.growth_rate_ref,
                is_cash_reserve=acc.is_cash_reserve,
                is_liquid=acc.is_liquid if acc.is_liquid is not None else acc.type in ("liquid", "taxable_brokerage"),
                min_target_balance=acc.min_target_balance,
                max_target_balance=acc.max_target_balance,
                cost_basis=acc.cost_basis,
            )
            for acc in self.config.accounts
        }
        return SimulationState(
            current_year=self.config.meta.start_year,
            accounts=accounts,
            assets={},
            debts={},
        )

    def _add_uncovered_deficit_as_debt(self, remaining_deficit: float, state: SimulationState, current_year: int) -> None:
        """
        Add any remaining uncovered deficit as a new debt liability.
        This represents borrowing (e.g., credit card debt, personal loan) to cover expenses.
        """
        # Use a simple interest rate for uncovered deficit (could be configurable)
        uncovered_deficit_rate = UNCOVERED_DEFICIT_RATE

        debt_id = UNCOVERED_DEFICIT_ID  # Single consolidated debt for all uncovered deficits
        debt_name = UNCOVERED_DEFICIT_NAME

        # If we already have uncovered deficit debt, add to it
        if debt_id in state.debts:
            state.debts[debt_id].principal += remaining_deficit
        else:
            state.debts[debt_id] = DebtState(
                id=debt_id,
                name=debt_name,
                principal=remaining_deficit,
                interest_rate=uncovered_deficit_rate,
                term_years=0,  # No fixed term - this is revolving debt
                remaining_years=0,
            )

    def run(self) -> pd.DataFrame:
        state = self._initialize_state()
        records: List[Dict[str, Any]] = []

        start_year = self.config.meta.start_year
        end_year = self.config.meta.end_year

        # Get all possible tags from the schema
        all_tags = list(Tag.__args__) if hasattr(Tag, '__args__') else []

        for year in range(start_year, end_year + 1):
            state.current_year = year
            period_data: Dict[str, Any] = {"Year": year}

            # Track spending by tag for aggregate columns
            tag_spending: Dict[str, float] = {tag: 0.0 for tag in all_tags}
            # Track lifestyle spending (all expenses except Investments and Taxes)
            lifestyle_spend = 0.0

            # 1. Apply Asset & Account Compounding Growth at start of period
            for acc in state.accounts.values():
                if acc.growth_rate_ref:
                    growth_rate = self._get_growth_rate(acc.growth_rate_ref, year)
                    acc.balance *= (1.0 + growth_rate)

            for asset in state.assets.values():
                if asset.growth_rate_ref:
                    growth_rate = self._get_growth_rate(asset.growth_rate_ref, year)
                    asset.value *= (1.0 + growth_rate)

            # 1b. Calculate recurring asset costs (percentage of current asset value)
            # These are calculated each year the asset exists in the simulation
            # We calculate them here (before events) so they apply even in liquidation year
            # but output the columns later in the expense section
            recurring_cost_records: Dict[str, float] = {}
            post_tax_expenses = 0.0
            # Map recurring cost types to tags
            cost_type_to_tag = {
                "tax": "Housing",
                "insurance": "Insurance",
                "maintenance": "Housing",
                "maintainance": "Housing",  # common typo
                "HOA": "Housing",
                "hoa": "Housing",
            }
            for asset in state.assets.values():
                for cost_type, percentage in asset.recurring_costs.items():
                    cost_amount = percentage * asset.value
                    recurring_cost_records[f"{asset.name}_{cost_type}"] = -cost_amount
                    post_tax_expenses += cost_amount
                    # Track recurring asset costs by tag based on cost type
                    tag = cost_type_to_tag.get(cost_type.lower(), "Housing")
                    tag_spending[tag] -= cost_amount
                    lifestyle_spend += cost_amount

            # 2. Evaluate & Execute Events for the current year
            gross_taxable_income = 0.0
            non_taxable_income = 0.0
            total_capital_gains = 0.0
            pre_tax_deductions = 0.0
            total_cash_inflow = 0.0  # Track actual cash received (excludes capital gains)
            total_contributions = 0.0  # 401k/Roth/529 transfers into accounts (not consumption)
            total_pre_tax_contributions = 0.0  # pre-tax portion of contributions (AGI-reducing)
            non_contribution_pre_tax = 0.0  # AGI deductions that are also cash outflows
            total_retirement_contributions = 0.0  # contributions into retirement accounts only
            contribution_records: Dict[str, float] = {}  # per-stream transfer info columns
            event_flow_records: Dict[str, float] = {}
            # Surplus-gated ("waterfall") contribution streams. Each entry is a
            # funding proposal: the amount only becomes real if the year's surplus
            # can cover it, funded in priority order (see step 4 below).
            gated_proposals: List[Dict[str, Any]] = []
            # Track fee breakdowns for detailed columns
            purchase_fee_columns: Dict[str, float] = {}
            sale_fee_columns: Dict[str, float] = {}

            for event in self.events:
                impact: EventImpact = event.evaluate(state, self.config.macroeconomics)
                gross_taxable_income += impact.gross_taxable_income
                non_taxable_income += impact.non_taxable_income
                total_capital_gains += impact.capital_gains
                pre_tax_deductions += impact.pre_tax_deductions
                post_tax_expenses += impact.post_tax_expenses
                total_cash_inflow += impact.cash_inflow
                total_contributions += impact.contribution_transfers
                total_pre_tax_contributions += impact.pre_tax_contribution
                if impact.contribution_transfers:
                    target_id = getattr(event.config, "target_account_id", None)
                    target_acc = state.accounts.get(target_id) if target_id else None
                    if target_acc and target_acc.account_type in ("traditional_401k", "roth_ira"):
                        total_retirement_contributions += impact.contribution_transfers
                    contribution_records[f"Contribution: {event.config.name}"] = -impact.contribution_transfers
                if impact.contribution_transfers == 0:
                    non_contribution_pre_tax += impact.pre_tax_deductions

                # Collect surplus-gated streams: unused here, funded in step 4.
                if impact.surplus_contribution > 0:
                    cfg = event.config
                    target_acc = state.accounts.get(cfg.target_account_id) if cfg.target_account_id else None
                    gated_proposals.append({
                        "name": cfg.name,
                        "account_id": cfg.target_account_id,
                        "is_retirement": bool(target_acc and target_acc.account_type in ("traditional_401k", "roth_ira")),
                        "is_pretax": bool(getattr(cfg, "is_pre_tax_deduction", False)),
                        "priority": int(getattr(cfg, "surplus_priority", 0)),
                        "tags": list(getattr(cfg, "tags", []) or []),
                        "proposal": impact.surplus_contribution,
                        "event_index": len(gated_proposals),
                    })

                # Net cash flow contribution for individual event column
                # Income positive, Expense negative
                # Only record event column when the event actually has an impact (trigger year)
                if impact.net_cash_flow != 0 or impact.cash_inflow != 0 or impact.post_tax_expenses != 0 or impact.gross_taxable_income != 0 or impact.non_taxable_income != 0:
                    event_key = f"Event: {event.config.name}"

                    # For asset purchase: show only down payment in main column
                    # For asset liquidation: show gross proceeds (sale - mortgage) in main column
                    # Fees are shown in separate breakdown columns
                    if event.config.type == "asset_purchase":
                        event_flow_records[event_key] = -event.config.down_payment
                    elif event.config.type == "asset_liquidation":
                        # Gross proceeds = cash_inflow (already excludes fees in current implementation)
                        event_flow_records[event_key] = impact.cash_inflow
                    else:
                        event_flow_records[event_key] = impact.net_cash_flow

                # Collect purchase fee breakdown for detailed columns
                for fee_type, amount in impact.purchase_fees.items():
                    column_name = f"Event: {event.config.name} - {fee_type}"
                    purchase_fee_columns[column_name] = -amount  # Negative for expense

                # Collect sale fee breakdown for detailed columns
                for fee_type, amount in impact.sale_fees.items():
                    column_name = f"Event: {event.config.name} - {fee_type}"
                    sale_fee_columns[column_name] = -amount  # Negative for expense

                # Track spending by tag
                # For income events, track as positive; for expense events, track as negative.
                # Contribution transfers (401k/Roth/529) are counted toward their tags
                # ("where did the money go") even though they are not consumption expenses.
                event_income = impact.gross_taxable_income + impact.non_taxable_income
                event_expense = impact.post_tax_expenses + impact.pre_tax_deductions + impact.contribution_transfers

                # Determine if this is an income or expense event
                # CashStreamEvent has category "income" or "expense"
                # AssetPurchaseEvent and AccountLiquidationEvent are expenses (down payment, transfer out)
                # AssetLiquidationEvent is income (sale proceeds) minus fees
                is_income_event = (
                    hasattr(event.config, 'category') and event.config.category == "income"
                ) or (
                    event.config.type == "asset_liquidation"  # Sale proceeds are income
                )

                for tag in event.config.tags:
                    if is_income_event:
                        tag_spending[tag] += event_income
                    else:
                        # Expense - add to tag spending as negative
                        # Asset purchases, liquidations (transfer out), and cash_stream expenses all count as expenses
                        tag_spending[tag] -= event_expense

                # Track lifestyle spending (all post-tax expenses except Investments and Taxes)
                is_investment = "Investments" in event.config.tags
                is_taxes = "Taxes" in event.config.tags
                is_expense_event = (
                    hasattr(event.config, 'category') and event.config.category == "expense"
                ) or (
                    event.config.type in ("asset_purchase", "account_liquidation")  # These are expenses
                )
                if is_expense_event and not is_investment and not is_taxes:
                    lifestyle_spend += impact.post_tax_expenses + impact.pre_tax_deductions

            # 3. Process mortgage payments for each debt (after events so new mortgages get first payment)
            # Mortgage payments are treated as post-tax expenses (principal + interest)
            mortgage_payment_records: Dict[str, float] = {}
            for debt in state.debts.values():
                # Skip uncovered deficit debt (no fixed term payments - just accrues interest)
                if debt.remaining_years <= 0:
                    # Accrue interest on revolving debt - this increases the debt balance
                    # but is NOT a cash outflow (the cash outflow was the original expense)
                    interest_accrual = debt.principal * debt.interest_rate
                    debt.principal += interest_accrual
                    # Track interest for reference but don't add to post_tax_expenses
                    # (to avoid double-counting: interest grows debt AND would create deficit)
                    continue

                if debt.principal > 0:
                    annual_payment = calculate_mortgage_payment(
                        principal=debt.principal,
                        interest_rate=debt.interest_rate,
                        remaining_years=debt.remaining_years
                    )

                    # Calculate interest and principal portions
                    interest_payment = debt.principal * debt.interest_rate
                    principal_payment = min(annual_payment - interest_payment, debt.principal)

                    # Add to expenses (interest is typically tax-deductible but we treat as post-tax for simplicity)
                    post_tax_expenses += annual_payment

                    # Reduce debt principal
                    debt.principal -= principal_payment
                    debt.remaining_years -= 1

                    # Track mortgage payment in period data (single column per mortgage)
                    mortgage_payment_records[f"Mortgage Payment: {debt.name}"] = -annual_payment

                    # Mortgage payments are Housing expenses - add to Housing tag and lifestyle
                    tag_spending["Housing"] -= annual_payment
                    lifestyle_spend += annual_payment

            # 4. Determine AGI & Inflated Standard Deduction / Taxable Income
            # pre_tax_deductions = deductions that are REAL cash outflows (non-contribution);
            # total_pre_tax_contributions = pre-tax 401k-style contributions that reduce
            # taxable income but are transfers, not expenses. Both reduce AGI.
            #
            # Surplus-gated ("waterfall") contributions are funded out of this year's
            # excess cash flow only (never by liquidating savings). Pre-tax contributions
            # reduce AGI -> reduce tax -> enlarge surplus, so resolve a small fixed-point
            # (allocations are monotone and capped, so a few passes converge).
            if gated_proposals:
                proposed_order = sorted(
                    range(len(gated_proposals)),
                    key=lambda i: (gated_proposals[i]["priority"], gated_proposals[i]["event_index"]),
                )
                uncovered_principal = state.debts.get(UNCOVERED_DEFICIT_ID).principal if UNCOVERED_DEFICIT_ID in state.debts else 0.0
                gated_alloc = [0.0] * len(gated_proposals)
                gated_pretax = 0.0
                for _ in range(6):
                    agi = max(0.0, gross_taxable_income - pre_tax_deductions - total_pre_tax_contributions - gated_pretax)
                    std_deduction = self.tax_calculator.get_inflated_standard_deduction(current_year=year, macro=self.config.macroeconomics)
                    taxable_income = max(0.0, agi - std_deduction)
                    # Capital gains are taxed at capital-gains bracket rates; ordinary income
                    # (AGI excluding gains) is taxed at ordinary rates. gross_taxable_income
                    # still includes gains for the reporting columns, so split them out here.
                    ordinary_income = max(0.0, agi - total_capital_gains)
                    ordinary_tax = self.tax_calculator.calculate_income_tax(ordinary_income, current_year=year, macro=self.config.macroeconomics)
                    cap_gains_tax = self.tax_calculator.calculate_cap_gains_tax(total_capital_gains, current_year=year, macro=self.config.macroeconomics)
                    federal_tax = ordinary_tax + cap_gains_tax

                    # total_cash_inflow already includes non-taxable income (CashStreamEvent
                    # credits cash_inflow for both taxable and non-taxable income), so adding
                    # non_taxable_income again would double-count it.
                    total_inflows = total_cash_inflow
                    total_outflows = post_tax_expenses + non_contribution_pre_tax
                    net_operating_cash_flow = total_inflows - total_outflows - federal_tax

                    # Surplus available for gated funding = operating cash flow after the
                    # unconditional contributions, with revolving deficit debt paid down
                    # before any investing.
                    surplus_for_gated = max(0.0, net_operating_cash_flow - total_contributions)
                    if uncovered_principal > 0:
                        surplus_for_gated = max(0.0, surplus_for_gated - min(surplus_for_gated, uncovered_principal))

                    new_alloc = [0.0] * len(gated_proposals)
                    remaining = surplus_for_gated
                    for i in proposed_order:
                        take = min(gated_proposals[i]["proposal"], remaining)
                        new_alloc[i] = take
                        remaining -= take
                    new_pretax = sum(new_alloc[i] for i, gp in enumerate(gated_proposals) if gp["is_pretax"])
                    if new_alloc == gated_alloc and new_pretax == gated_pretax:
                        break
                    gated_alloc, gated_pretax = new_alloc, new_pretax
            else:
                gated_alloc = []
                gated_pretax = 0.0
                agi = max(0.0, gross_taxable_income - pre_tax_deductions - total_pre_tax_contributions)
                std_deduction = self.tax_calculator.get_inflated_standard_deduction(current_year=year, macro=self.config.macroeconomics)
                taxable_income = max(0.0, agi - std_deduction)
                ordinary_income = max(0.0, agi - total_capital_gains)
                ordinary_tax = self.tax_calculator.calculate_income_tax(ordinary_income, current_year=year, macro=self.config.macroeconomics)
                cap_gains_tax = self.tax_calculator.calculate_cap_gains_tax(total_capital_gains, current_year=year, macro=self.config.macroeconomics)
                federal_tax = ordinary_tax + cap_gains_tax
                total_inflows = total_cash_inflow
                total_outflows = post_tax_expenses + non_contribution_pre_tax
                net_operating_cash_flow = total_inflows - total_outflows - federal_tax

            # Commit the surplus-funded gated contributions: credit accounts, fold them
            # into totals and per-stream/tag reporting.
            for i, gp in enumerate(gated_proposals):
                amount = gated_alloc[i]
                if amount <= 0.0:
                    continue
                state.accounts[gp["account_id"]].balance += amount
                total_contributions += amount
                if gp["is_pretax"]:
                    total_pre_tax_contributions += amount
                if gp["is_retirement"]:
                    total_retirement_contributions += amount
                contribution_records[f"Contribution: {gp['name']}"] = -amount
                for tag in gp["tags"]:
                    tag_spending[tag] -= amount

            # Investment/savings transfers (401k, Roth IRA, 529) are movements INTO
            # accounts, not consumption, so they are excluded from Net Cash Flow.
            # They still consume the year's cash: contributions are funded out of
            # surplus first; any shortfall left after funding them (cash_available
            # < 0) is resolved through the waterfall exactly as before. This keeps
            # the balance sheet identical while making Net Cash Flow reflect true
            # operating cash flow (income - consumption - taxes) instead of counting
            # savings twice (once as outflow, once when it is drawn back down).
            cash_available = net_operating_cash_flow - total_contributions

            # 5. Resolve Cash Flow Delta via Waterfall Strategy
            surplus_to_allocate = cash_available
            deficit_drawdown = 0.0
            if cash_available > 0:
                # Pay down revolving deficit debt before investing any surplus.
                # The paydown is a balance-sheet move (reduces a liability), so the
                # Net Cash Flow column still reports operating cash flow unchanged.
                uncovered = state.debts.get(UNCOVERED_DEFICIT_ID)
                if uncovered and uncovered.principal > 0:
                    repayment = min(cash_available, uncovered.principal)
                    uncovered.principal -= repayment
                    surplus_to_allocate = cash_available - repayment
                    if uncovered.principal <= 0.0:
                        del state.debts[UNCOVERED_DEFICIT_ID]
                self.waterfall_resolver.resolve_surplus(surplus_to_allocate, state.accounts)
            elif cash_available < 0:
                # Pass absolute value of deficit (resolve_deficit expects positive amount)
                # Track any remaining uncovered deficit as new debt
                deficit_to_resolve = abs(cash_available)
                remaining_deficit = self.waterfall_resolver.resolve_deficit(
                    deficit_to_resolve, state.accounts
                )
                deficit_drawdown = deficit_to_resolve - remaining_deficit
                if remaining_deficit > 0:
                    self._add_uncovered_deficit_as_debt(remaining_deficit, state, year)

            # 5b. Rebalance accounts that exceed max_target_balance after waterfall resolution
            self.waterfall_resolver.rebalance_excess(state.accounts)

            # 5c. Calculate Period Balances & Totals
            total_account_balances = sum(acc.balance for acc in state.accounts.values())
            total_asset_values = sum(asset.value for asset in state.assets.values())
            total_debt_liabilities = sum(debt.principal for debt in state.debts.values())

            total_assets = total_account_balances + total_asset_values
            net_worth = total_assets - total_debt_liabilities

            # 5d. High-Liquidity Net Worth: cash/savings + taxable brokerage (funds
            # available within a day), minus revolving (uncovered deficit) debt.
            # Mortgages and non-liquid assets (home, etc.) are intentionally excluded.
            liquid_assets = sum(acc.balance for acc in state.accounts.values() if acc.is_liquid)
            revolving_debt = state.debts.get(UNCOVERED_DEFICIT_ID).principal if UNCOVERED_DEFICIT_ID in state.debts else 0.0
            liquid_net_worth = liquid_assets - revolving_debt

            # Assemble period snapshot in explicit column group order:
            # LEFT SIDE: Non-cashflow items (balances, values, metrics for reference)
            # 1. Summary Metrics (leftmost - for quick reference)
            period_data["Gross Taxable Income"] = gross_taxable_income
            period_data["Pre-tax Deductions"] = pre_tax_deductions + total_pre_tax_contributions
            period_data["AGI"] = agi
            period_data["Net Cash Flow"] = net_operating_cash_flow
            period_data["Investment Contribution Transfers"] = -total_contributions
            period_data["Retirement Contribution Transfers"] = -total_retirement_contributions
            period_data["Deficit Drawdowns"] = deficit_drawdown

            # 2. Account Balances
            for acc in state.accounts.values():
                period_data[f"Account: {acc.name}"] = acc.balance

            # Retirement assets = balance held in retirement accounts (401k + Roth)
            retirement_account_ids = {acc.id for acc in state.accounts.values()
                                      if acc.account_type in ("traditional_401k", "roth_ira")}
            retirement_assets = sum(acc.balance for acc in state.accounts.values() if acc.id in retirement_account_ids)
            period_data["Retirement Assets"] = retirement_assets

            # 3. Asset Values (grouped with other balances on left)
            for asset in state.assets.values():
                period_data[f"Asset: {asset.name}"] = asset.value

            # 4. Debt Liabilities
            for debt in state.debts.values():
                period_data[f"Debt: {debt.name}"] = debt.principal

            # 5. Totals & Net Worth
            period_data["Total Account Balances"] = total_account_balances
            period_data["Liquid Assets"] = liquid_assets
            period_data["Liquid Net Worth"] = liquid_net_worth
            period_data["Total Assets"] = total_assets
            period_data["Total Liabilities"] = total_debt_liabilities
            period_data["Net Worth"] = net_worth

            # 6. Granular Tax Details (informational, not cashflow)
            period_data["Tax: Standard Deduction"] = std_deduction
            period_data["Tax: Taxable Income"] = taxable_income

            # RIGHT SIDE: All Expenses & Cash Flows (grouped together for easy summing)
            # 7a. Recurring Asset Costs (from pre-calculated records)
            for cost_key, cost_val in recurring_cost_records.items():
                period_data[cost_key] = cost_val

            # 7b. Mortgage Payments (single column per mortgage)
            for mp_key, mp_val in mortgage_payment_records.items():
                period_data[mp_key] = mp_val

            # 7c. Individual Life Events (net cash flow)
            for e_key, e_val in event_flow_records.items():
                period_data[e_key] = e_val

            # 7d. Purchase/Sale Fee Breakdowns (detailed columns)
            for fee_key, fee_val in purchase_fee_columns.items():
                period_data[fee_key] = fee_val
            for fee_key, fee_val in sale_fee_columns.items():
                period_data[fee_key] = fee_val

            # 7e. Federal Tax as negative expense (for manual cash flow checks)
            period_data["Federal Tax"] = -federal_tax
            # Track federal tax in Taxes tag
            tag_spending["Taxes"] -= federal_tax

            # 7f. Contribution stream info columns (transfers INTO accounts; shown
            # for visibility, excluded from Net Cash Flow and spending totals).
            for c_key, c_val in contribution_records.items():
                period_data[c_key] = c_val

            # 7g. Tag Aggregate Columns (sum of spending by tag, negative for expenses)
            for tag in all_tags:
                period_data[f"Tag: {tag}"] = tag_spending[tag]

            # 7h. General Lifestyle Spend (all expenses except Investments and Taxes)
            period_data["General Lifestyle Spend"] = -lifestyle_spend  # Negative for expense

            records.append(period_data)

        df = pd.DataFrame(records).set_index("Year")

        # Reorder columns with explicit grouping:
        # LEFT SIDE (non-cashflow): Summary metrics, Accounts, Totals, Net Worth, Tax info
        # MIDDLE-LEFT: All Asset values, All Debt liabilities (grouped together after tax)
        # MIDDLE: Tag aggregates, General Lifestyle Spend
        # RIGHT SIDE (cashflow/expenses): Events, fees, recurring costs, mortgage payments, Federal Tax

        left_cols = []
        asset_cols = []
        debt_cols = []
        middle_cols = []
        right_cols = []

        for col in df.columns:
            # LEFT: Summary metrics, Account balances, Totals, Net Worth, Tax details
            if col.startswith(("Account: ", "Total ", "Net Worth", "Liquid ",
                              "Gross Taxable", "Pre-tax", "AGI", "Net Cash Flow",
                              "Investment Contribution", "Deficit Drawdowns",
                              "Tax: Standard", "Tax: Taxable")) or col in (
                    "Retirement Assets", "Retirement Contribution Transfers"):
                left_cols.append(col)
            # ASSETS: All asset values grouped together
            elif col.startswith("Asset: "):
                asset_cols.append(col)
            # DEBTS: All debt liabilities grouped together
            elif col.startswith("Debt: "):
                debt_cols.append(col)
            # MIDDLE: Tag aggregates and General Lifestyle Spend
            elif col.startswith("Tag: ") or col == "General Lifestyle Spend":
                middle_cols.append(col)
            # RIGHT: Everything else (Event columns, recurring costs, mortgage payments, fees, Federal Tax)
            else:
                right_cols.append(col)

        # Order: left + assets + debts + middle + right
        ordered_cols = left_cols + asset_cols + debt_cols + middle_cols + right_cols
        df = df[ordered_cols]

        return df