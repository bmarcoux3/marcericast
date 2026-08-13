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

    def _add_uncovered_deficit_as_debt(self, remaining_deficit: float, state: SimulationState) -> None:
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
            event_flow_records: Dict[str, float] = {}
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

                # Net cash flow contribution for individual event column
                # Income positive, Expense negative
                # Only record event column when the event actually has an impact (trigger year)
                if impact.net_cash_flow != 0 or impact.cash_inflow != 0 or impact.post_tax_expenses != 0 or impact.pre_tax_deductions != 0 or impact.gross_taxable_income != 0 or impact.non_taxable_income != 0:
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
                # For income events, track as positive; for expense events, track as negative
                event_income = impact.gross_taxable_income + impact.non_taxable_income
                event_expense = impact.post_tax_expenses + impact.pre_tax_deductions

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
            agi = max(0.0, gross_taxable_income - pre_tax_deductions)
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
            total_outflows = post_tax_expenses + pre_tax_deductions
            net_operating_cash_flow = total_inflows - total_outflows - federal_tax

            # 5. Resolve Cash Flow Delta via Waterfall Strategy
            surplus_to_allocate = net_operating_cash_flow
            if net_operating_cash_flow > 0:
                # Pay down revolving deficit debt before investing any surplus.
                # The paydown is a balance-sheet move (reduces a liability), so the
                # Net Cash Flow column still reports operating cash flow unchanged.
                uncovered = state.debts.get(UNCOVERED_DEFICIT_ID)
                if uncovered and uncovered.principal > 0:
                    repayment = min(net_operating_cash_flow, uncovered.principal)
                    uncovered.principal -= repayment
                    surplus_to_allocate = net_operating_cash_flow - repayment
                    if uncovered.principal <= 0.0:
                        del state.debts[UNCOVERED_DEFICIT_ID]
                self.waterfall_resolver.resolve_surplus(surplus_to_allocate, state.accounts)
            elif net_operating_cash_flow < 0:
                # Pass absolute value of deficit (resolve_deficit expects positive amount)
                # Track any remaining uncovered deficit as new debt
                remaining_deficit = self.waterfall_resolver.resolve_deficit(
                    abs(net_operating_cash_flow), state.accounts
                )
                if remaining_deficit > 0:
                    self._add_uncovered_deficit_as_debt(remaining_deficit, state)

            # 5b. Rebalance accounts that exceed max_target_balance after waterfall resolution
            self.waterfall_resolver.rebalance_excess(state.accounts)

            # 5c. Calculate Period Balances & Totals
            total_account_balances = sum(acc.balance for acc in state.accounts.values())
            total_asset_values = sum(asset.value for asset in state.assets.values())
            total_debt_liabilities = sum(debt.principal for debt in state.debts.values())

            total_assets = total_account_balances + total_asset_values
            net_worth = total_assets - total_debt_liabilities

            # Assemble period snapshot in explicit column group order:
            # LEFT SIDE: Non-cashflow items (balances, values, metrics for reference)
            # 1. Summary Metrics (leftmost - for quick reference)
            period_data["Gross Taxable Income"] = gross_taxable_income
            period_data["Pre-tax Deductions"] = pre_tax_deductions
            period_data["AGI"] = agi
            period_data["Net Cash Flow"] = net_operating_cash_flow

            # 2. Account Balances
            for acc in state.accounts.values():
                period_data[f"Account: {acc.name}"] = acc.balance

            # 3. Asset Values (grouped with other balances on left)
            for asset in state.assets.values():
                period_data[f"Asset: {asset.name}"] = asset.value

            # 4. Debt Liabilities
            for debt in state.debts.values():
                period_data[f"Debt: {debt.name}"] = debt.principal

            # 5. Totals & Net Worth
            period_data["Total Account Balances"] = total_account_balances
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

            # 7f. Tag Aggregate Columns (sum of spending by tag, negative for expenses)
            for tag in all_tags:
                period_data[f"Tag: {tag}"] = tag_spending[tag]

            # 7g. General Lifestyle Spend (all expenses except Investments and Taxes)
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
            if col.startswith(("Account: ", "Total ", "Net Worth",
                              "Gross Taxable", "Pre-tax", "AGI", "Net Cash Flow",
                              "Tax: Standard", "Tax: Taxable")):
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