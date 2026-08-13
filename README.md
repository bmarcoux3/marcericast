# Personal Cashflow Scenario Engine - README & LLM Generator System Prompt

> **Instructions for LLM Context Prompting:**
> Copy this entire README into any LLM context window (Gemini, Claude, ChatGPT, etc.) alongside a natural language description of your personal financial situation, goals, accounts, and planned events. The LLM will use the exact schema rules, data structures, and engine execution logic below to generate a fully valid `scenario.yaml` file compatible with the cashflow engine.

---

## 1. Overview & Engine Execution Order

The **Personal Cashflow Engine** simulates annual personal cash flow, account growth, taxes, asset accumulation, and debt modeling deterministically across a given timeline.

For each simulation year (from `start_year` to `end_year`), the engine executes the following 5-step sequence:

1. **Asset & Account Compounding Growth**:
   - Accounts and physical assets compound at the start of the year based on `growth_rates` defined in `macroeconomics`.
2. **Event Evaluation & Impact Calculation**:
   - Evaluates all configured `events` for the current year.
   - Computes `gross_taxable_income`, `non_taxable_income`, `pre_tax_deductions`, and `post_tax_expenses`.
   - Executes structural state changes (e.g., adding assets/debts for `asset_purchase` or moving balances for `account_liquidation`).
3. **Tax & Net Cash Flow Determination**:
   - Calculates Adjusted Gross Income (AGI): `AGI = max(0.0, gross_taxable_income - pre_tax_deductions)`.
   - Calculates Standard Deduction (inflated annually using `general_inflation_rate` if `inflate_brackets: true`).
   - Calculates Federal Tax according to tax brackets.
   - Computes Net Operating Cash Flow: `Net Cash Flow = (gross_taxable_income + non_taxable_income) - (post_tax_expenses + pre_tax_deductions) - federal_tax`.
4. **Waterfall Strategy Resolution**:
   - **If Net Cash Flow > 0 (Surplus)**: Deposits surplus into accounts listed under `waterfall_strategy.surplus_allocation` in priority order up to `max_annual_contribution`.
   - **If Net Cash Flow < 0 (Deficit)**: Withdraws deficit from accounts listed under `waterfall_strategy.deficit_drawdown_order` in priority order.
5. **Snapshot & Net Worth Calculation**:
   - Summarizes total account balances, physical asset values, and debt liabilities.
   - Computes `Net Worth = Total Accounts + Total Assets - Total Debt Liabilities`.

---

## 2. Complete YAML Schema Specification

Every scenario YAML file **must strictly conform** to the following schema structure. All extra fields are forbidden (`extra="forbid"`).

### Root Structure

```yaml
version: "1.0"

meta:
  scenario_name: string          # Required. E.g., "Early Retirement Baseline"
  start_year: int                # Required. E.g., 2026
  end_year: int                  # Required. Must be >= start_year. E.g., 2056
  time_step: "annual"            # Optional. Default: "annual"
  tax_status: string             # Optional. Options: "Single", "MFJ", "MFS", "HeadOfHousehold". Default: "MFJ"

macroeconomics:
  general_inflation_rate: float # Optional. Default: 0.0 (e.g., 0.025 = 2.5%)
  growth_rates:                 # Optional dictionary of asset/account return rates
    equities: float
    bonds: float
    real_estate: float

tax_rules:
  inflate_brackets: bool         # Optional. Default: true
  reference_year: int            # Optional. Default: 2026
  inflation_ref: string          # Optional. Default: "general_inflation_rate"
  federal:
    standard_deduction: float    # Base standard deduction amount (e.g., 32200)
    brackets:
      - limit: float             # Upper income threshold for bracket (.inf for final bracket)
        rate: float              # Marginal tax rate (e.g., 0.12 = 12%)

accounts:
  - id: string                   # Required unique identifier (e.g., "checking_primary")
    name: string                 # Required descriptive name
    type: string                 # Required. Options: "liquid", "taxable_brokerage", "traditional_401k", "roth_ira", "debt"
    balance: float               # Optional. Default: 0.0
    growth_rate_ref: string      # Optional. Reference key in macroeconomics.growth_rates (e.g., "equities")
    is_cash_reserve: bool        # Optional. Default: false
    min_target_balance: float    # Optional. Default: 0.0
    cost_basis: float            # Optional. Default: 0.0

waterfall_strategy:
  surplus_allocation:
    - account_id: string         # ID of target account
      max_annual_contribution: float # Optional. Default: .inf
  deficit_drawdown_order:
    - account_id: string         # ID of account to draw down in order

events:
  - ... # Polymorphic list of events (see Event Specifications below)
```

### Scenario Variables (`.variables` & `.variable_meta`)

Scenario-wide tunable variables are declared as YAML anchors in the top-level
`.variables` list and referenced anywhere in the scenario with aliases:

```yaml
.variables:
  - &retirement 2061
  - &social_security_enabled 1

events:
  - id: "swe_salary"
    type: "cash_stream"
    category: "income"
    end_year: *retirement
  - id: "social_security"
    type: "cash_stream"
    category: "income"
    start_year: *retirement
```

Overrides posted to the simulation (`variables.<name>`) update the variable
everywhere it is aliased, so one toggle can control multiple events.

`.variable_meta` optionally declares which variables the dashboard exposes in
the "Life Decisions" panel and how they render:

```yaml
.variable_meta:
  retirement:
    label: "Retirement Year"
    control: "slider"
    min: 2040
    max: 2075
    step: 1
  social_security_enabled:
    label: "Social Security Enabled"
    control: "toggle"
```

Supported `control` values: `toggle` (checkbox, values 0/1), `slider` (number
input constrained by `min`/`max`/`step`), or omitted (plain number/text field).
Variables not listed in `.variable_meta` stay hidden from the UI.

---

---

## 3. Polymorphic Event Specifications

There are three supported event types in `events`. All events require a `tags` list containing at least one valid tag (see Tag Taxonomy below).

### Type 1: `cash_stream`
Represents recurring income or expenses over a range of years, with optional inflation adjustments and payroll deductions.

```yaml
- id: string                     # Required unique ID (e.g., "swe_salary")
  name: string                   # Required name
  type: "cash_stream"            # Required
  category: "income" | "expense" # Required
  start_year: int                # Required
  end_year: int                  # Required
  base_amount: float             # Required annual amount in reference_year dollars
  tags: [string]                 # Required list of tags (at least 1 item; e.g., ["Food & Living"])
  reference_year: int            # Optional. Base year for inflation indexing (e.g. 2026)
  inflation_ref: string          # Optional. Key in growth_rates or "general_inflation_rate"
  gap_years: [int]               # Optional. List of years where this cash stream is inactive
  is_taxable_income: bool        # Optional. Default: false (Only for income)
  is_earned_income: bool         # Optional. Default: false (Only for income)
  is_pre_tax_deduction: bool     # Optional. Default: false (Only for expense; reduces taxable income)
  target_account_id: string      # Optional. Account to directly deposit into (e.g., 401k pre-tax)
  step_adjustments:              # Optional. Step changes in income/expenses (year: multiplier)
    2030: 1.2                    # E.g., 20% promotion starting in 2030
```

### Type 2: `asset_purchase`
Represents purchasing a major physical asset (e.g., real estate) financed via a down payment and mortgage debt.

```yaml
- id: string                     # Required unique ID (e.g., "buy_home")
  name: string                   # Required name
  type: "asset_purchase"         # Required
  trigger_year: int              # Required. Year of purchase
  down_payment: float            # Required cash outflow in trigger year
  asset_name: string             # Required name of physical asset
  asset_initial_value: float     # Required total initial value of asset
  tags: [string]                 # Required list of tags (at least 1 item; e.g., ["Housing"])
  growth_rate_ref: string        # Optional. Key in growth_rates for asset appreciation
  mortgage:                      # Optional mortgage debt liability creation
    principal: float             # Initial loan amount
    interest_rate: float         # Annual interest rate (e.g., 0.065)
    term_years: int              # Mortgage term in years (e.g., 30)
```

### Type 3: `account_liquidation`
Represents an explicit lump-sum transfer from one account to another in a specific year.

```yaml
- id: string                     # Required unique ID (e.g., "rebalance_transfer")
  name: string                   # Required name
  type: "account_liquidation"    # Required
  trigger_year: int              # Required
  source_account_id: string      # Required account to pull funds from
  target_account_id: string      # Required account to transfer funds to
  amount: float                  # Required maximum amount to transfer
  tags: [string]                 # Required list of tags (at least 1 item; e.g., ["Investments"])
```

---

## 3a. Tag Taxonomy

Every event must include a `tags` array containing one or more strings from the following allowed vocabulary:

- `Children`
- `Food & Living`
- `Healthcare`
- `Housing`
- `Insurance`
- `Investments`
- `Legal`
- `Life Events`
- `Pets`
- `Taxes`
- `Technology`
- `Transportation`
- `Travel & Discretionary`
- `Utilities`

**Rules:**
- `tags` is required on all events and must contain at least one valid tag (`min_length: 1`).
- An event may carry multiple tags (e.g., `tags: ["Housing", "Utilities"]`).
- Tag totals represent filtered views (e.g., "spend associated with Housing") and should **not** be summed across tags to avoid double-counting.

---

## 4. LLM Scenario Generation Prompting Guide

When copying this README to an LLM to generate a `scenario.yaml`, include the system prompt format below:

```text
[INSERT THIS ENTIRE README]

---

USER FINANCIAL CONTEXT & REQUIREMENTS: (FICTIONAL EXAMPLE - invented for illustration, not a real family)
- Primary Earner: Software Engineer making $180,000/yr starting in 2026, increasing by 15% in 2030. Retires in 2060.
- Primary Checking: $50,000 balance (keep minimum $50,000 cash reserve).
- Brokerage Account: $250,000 balance ($180,000 cost basis), invested in equities (7% annual return).
- Home Purchase: In 2027, buy a primary residence for $600,000 with $120,000 down payment and $480,000 mortgage at 6.5% interest for 30 years. Home appreciates at 3% per year.
- Waterfall strategy: Put extra cash into Taxable Brokerage; pull deficit from Primary Checking then Taxable Brokerage.

Life Events:
Create Life events using appropriate tags from the Tag Taxonomy (e.g., Children, Healthcare, Life Events, Travel & Discretionary).

TASK:
Based on the schema and engine rules in the README above, generate a complete, valid `scenario.yaml` document representing this user's situation. Ensure all account IDs match between accounts, waterfall_strategy, and events, and every event includes at least one valid tag.
```

---

## 5. Sample Valid `scenario.yaml`

Below is a complete reference scenario file:

```yaml
version: "1.0"

meta:
  scenario_name: "Baseline Early Retirement Plan"
  start_year: 2026
  end_year: 2056
  tax_status: "MFJ"

macroeconomics:
  general_inflation_rate: 0.025
  growth_rates:
    equities: 0.07
    bonds: 0.035
    real_estate: 0.03

tax_rules:
  federal:
    standard_deduction: 32200
    brackets:
      - limit: 24800
        rate: 0.10
      - limit: 100800
        rate: 0.12
      - limit: 211400
        rate: 0.22
      - limit: 403550
        rate: 0.24
      - limit: 512450
        rate: 0.32
      - limit: 768700
        rate: 0.35
      - limit: .inf
        rate: 0.37

accounts:
  - id: "checking_primary"
    name: "Primary Checking"
    type: "liquid"
    balance: 50000.0
    growth_rate_ref: "bonds"
    is_cash_reserve: true
    min_target_balance: 20000.0

  - id: "brokerage_vti"
    name: "Taxable Brokerage"
    type: "taxable_brokerage"
    balance: 250000.0
    growth_rate_ref: "equities"
    cost_basis: 180000.0

waterfall_strategy:
  surplus_allocation:
    - account_id: "brokerage_vti"

  deficit_drawdown_order:
    - account_id: "checking_primary"
    - account_id: "brokerage_vti"

events:
  - id: "tech_job_salary"
    name: "Software Engineer Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2045
    base_amount: 180000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags:
      - "Life Events"

  - id: "living_expenses"
    name: "Living Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2056
    base_amount: 75000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags:
      - "Food & Living"

  - id: "buy_home"
    name: "Purchase Primary Residence"
    type: "asset_purchase"
    trigger_year: 2030
    down_payment: 120000.0
    asset_name: "Primary Home"
    asset_initial_value: 600000.0
    growth_rate_ref: "real_estate"
    mortgage:
      principal: 480000.0
      interest_rate: 0.065
      term_years: 30
    tags:
      - "Housing"
```

