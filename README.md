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
  scenario_name: string          # Required. E.g., "Generic Family Demo Plan"
  start_year: int                # Required. E.g., 2026
  end_year: int                  # Required. Must be >= start_year. E.g., 2079
  time_step: "annual"            # Optional. Options: "annual", "monthly". Default: "annual"
  tax_status: string             # Optional. Options: "Single", "MFJ", "MFS", "HeadOfHousehold". Default: "MFJ"
  birth_year: int                # Optional. Used for age-based derisking calculations

macroeconomics:
  general_inflation_rate: float  # Optional. Default: 0.0 (e.g., 0.025 = 2.5%)
  growth_rates:                  # Optional dictionary of asset/account return rates
    equities: float
    bonds: float
    real_estate: float
    cash_equivalents: float      # Optional. E.g., for cash-reserve accounts
  derisking_schedule:            # Optional. Age-based glide path per growth_rate_ref
    equities:                    # Shift equities into bonds as the household ages
      start_age: int             # Age when the transition begins
      end_age: int               # Age when the transition completes
      transition_to: string      # Growth rate key to shift toward (e.g., "bonds")

tax_rules:
  inflate_brackets: bool         # Optional. Default: true
  reference_year: int            # Optional. Default: 2026
  inflation_ref: string          # Optional. Default: "general_inflation_rate"
  federal:
    standard_deduction: float    # Base standard deduction amount (e.g., 32200)
    brackets:
      - limit: float             # Upper income threshold for bracket (.inf for final bracket)
        rate: float              # Marginal tax rate (e.g., 0.12 = 12%)
  capital_gains:                 # Optional. Long-term capital gains brackets
    brackets:
      - limit: float             # Upper income threshold for bracket (.inf for final bracket)
        rate: float              # Capital gains rate (e.g., 0.15 = 15%)

accounts:
  - id: string                   # Required unique identifier (e.g., "checking_primary_joint")
    name: string                 # Required descriptive name
    type: string                 # Required. Options: "liquid", "taxable_brokerage", "traditional_401k", "roth_ira", "debt"
    balance: float               # Optional. Default: 0.0
    growth_rate_ref: string      # Optional. Reference key in macroeconomics.growth_rates (e.g., "equities")
    is_cash_reserve: bool        # Optional. Default: false
    min_target_balance: float    # Optional. Default: 0.0
    max_target_balance: float    # Optional. Default: 0.0. Surplus above this is swept onward in the waterfall
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

**Dot-prefixed authoring keys:** Top-level keys beginning with `.` (e.g.
`.version`, `.variables`, `.variable_meta`) are YAML-authoring helpers. They are
stripped before validation, so they never reach the engine. `version` may also
be written as a plain `version: "1.0"` key; the demo file uses `.version: "1.0"`.

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

There are four supported event types in `events`. All events should carry a `tags` list containing at least one valid tag (see Tag Taxonomy below).

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
  costs:                         # Optional. Annual costs as fraction of current asset value
    tax: float                   # E.g., 0.019 for 1.9% annual property tax
    insurance: float             # E.g., 0.015 for 1.5% annual insurance
    maintenance: float           # E.g., 0.02 for 2% annual maintenance
    HOA: float                   # E.g., 0.0048 for 0.48% annual HOA
  purchase_fees:                 # Optional. One-time fees as fraction of purchase price
    closing_costs: float         # E.g., 0.03 for 3% closing costs
    title_insurance: float       # E.g., 0.005 for 0.5% title insurance
```

Note: `down_payment + mortgage.principal` must equal `asset_initial_value` (buy outright with no mortgage, or finance the difference).

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

### Type 4: `asset_liquidation`
Represents selling a physical asset (e.g., downsizing the family home). Sale proceeds flow into the liquid account and any associated mortgage is paid off by default.

```yaml
- id: string                     # Required unique ID (e.g., "sell_home")
  name: string                   # Required name
  type: "asset_liquidation"      # Required
  trigger_year: int              # Required. Year of sale
  asset_name: string             # Required name of physical asset to sell
  sale_price: float              # Optional. Fixed sale price; defaults to current asset value
  mortgage_payoff: bool          # Optional. Default: true. Pay off associated mortgage
  primary_residence_exclusion: float  # Optional. IRS Sec. 121 gain exclusion (0 = none; 500000 for MFJ primary residence)
  sale_fees:                     # Optional. One-time fees as fraction of sale price
    agent_commission: float      # E.g., 0.06 for 6% agent commission
    closing_costs: float         # E.g., 0.02 for 2% closing costs
  tags: [string]                 # Required list of tags (at least 1 item; e.g., ["Housing"])
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
- `tags` is recommended on all events and should contain at least one valid tag (`min_length: 1` recommended; the schema tolerates missing tags for backward compatibility).
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

Below is the complete reference scenario shipped with this repo
(`scenarios/generic-demo.yaml`). It is a fictional, generic family plan that
exercises every engine feature: YAML variables (`.variables`), optional
life-decision UI controls (`.variable_meta`), federal and capital-gains tax
rules, an age-based derisking schedule, cash streams, asset purchases and
liquidations, account liquidations, and a waterfall strategy.

```yaml
.version: "1.0"

.variables:
  # ==========================================
  # TIME VARIABLES
  # ==========================================
  - &end_year 2079
  - &retirement 2061
  - &assisted_living_start 2074
  # Two children, born ~2024 and ~2026
  - &kid_one_18 2042
  - &kid_two_18 2044
  - &kid_one_22 2046
  - &kid_two_22 2048
  - &kid_one_wedding 2052
  - &kid_two_wedding 2054
  - &kid_one_car 2040
  - &kid_two_car 2042
  - &kid_one_braces 2036
  - &kid_one_braces_end 2037
  - &kid_two_braces 2038
  - &kid_two_braces_end 2039
  # Life Events
  - &summer_camps_start 2029
  - &summer_camps_end 2041
  - &back_to_school_start 2029
  - &back_to_school_end 2043
  - &school_field_trips_start 2029
  - &school_field_trips_end 2043
  - &extracurriculars_start 2029
  - &extracurriculars_end 2043
  - &birthday_parties_start 2026
  - &birthday_parties_end 2043
  - &allowances_start 2032
  - &allowances_end 2043
  - &passport_tsa_start 2026
  - &home_furniture_start 2032
  - &home_furniture_end 2056
  # Social Security (claiming at age 67)
  - &social_security_enabled 1
  - &ss_primary_annual 42000
  - &ss_secondary_annual 28000
  - &social_security_start 2061
  - &assisted_living_start_secondary 2076

  # ==========================================
  # BASE COST VARIABLES
  # ==========================================
  # Children
  - &daycare_base 12000
  - &college_base 28000
  - &wedding_cost 20000
  - &kid_car_cost 15000
  - &braces_cost 5500.0
  - &afterschool_care_annual 3500
  - &summer_camps_per_kid 2000
  - &kids_extracurricular_annual 800
  - &kids_bday_party_per_kid 400
  - &back_to_school_per_kid 350
  - &kids_allowance_annual 500
  - &kids_laptop_cost 1000
  # Healthcare
  - &grocery_base_individual 3500
  - &medical_premium_individual 1200
  - &medicare_multiplier_65 7.8
  - &medicare_multiplier_75 8.6
  - &medicare_multiplier_80 9.4
  - &medicare_multiplier_85 10.2
  - &out_of_pocket_medical_emergency 4000
  - &assisted_living_cost 58000
  # Housing
  - &kitchen_remodel_cost 40000
  - &furniture_upgrade_cost 15000
  - &deck_patio_cost 5000
  # Transportation
  - &vehicle_cost 40000
  - &auto_tires_annual 228
  - &auto_brakes_cost 450
  - &auto_body_repair_cost 2500
  # Insurance
  - &auto_insurance_annual 2200
  - &term_life_annual 1000
  - &disability_insurance_annual 1500
  - &homeowners_deductible 2000
  # Food and living
  - &holiday_gifts_annual 1200
  - &healthcare_copays_annual 1000
  - &pet_care_annual 1000
  - &digital_security_annual 200
  - &charitable_giving_annual 1500
  - &passport_tsa_cost 400
  - &smartphone_annual 228
  - &small_appliance_cost 300
  - &adult_clothing_annual 900
  - &legal_fees_annual 500
  - &electricity_annual 2200
  - &water_sewer_trash_annual 1500
  - &internet_annual 960
  - &cell_phone_per_line_annual 360
  - &household_supplies_annual 1500
  - &diapers_wipes_annual 1200
  - &fuel_gas_annual 4000
  - &tolls_parking_annual 500
  - &dining_out_annual 3600
  - &haircuts_annual 1000
  - &hvac_filters_annual 300
  - &school_field_trips_annual 200
  - &otc_meds_annual 500
  - &entertainment_annual 2000
  - &date_nights_annual 1800
  - &digital_subscriptions_annual 500
  - &family_vacation_cost 4500
  - &family_photos_cost 500
  - &funeral_cost 20000
  - &vet_emergency_cost 2500
  - &anniversary_trip_cost 4000

# ==========================================
# OPTIONAL: UI controls for life-decision variables
# Variables listed here are exposed in the "life decisions" panel;
# all other variables stay hidden unless added to this block.
# ==========================================
.variable_meta:
  end_year:
    label: "End Year"
    control: "slider"
    min: 2050
    max: 2099
    step: 1
  retirement:
    label: "Retirement Year"
    control: "slider"
    min: 2040
    max: 2075
    step: 1
  assisted_living_start:
    label: "Assisted Living Start Year"
    control: "slider"
    min: 2060
    max: 2090
    step: 1
  social_security_enabled:
    label: "Social Security Enabled"
    description: "Whether Social Security benefits are modeled."
    control: "toggle"

meta:
  scenario_name: "Generic Family Demo Plan"
  start_year: 2026
  end_year: *end_year
  tax_status: "MFJ"
  birth_year: 1994

macroeconomics:
  general_inflation_rate: 0.025
  growth_rates:
    equities: 0.07
    bonds: 0.035
    real_estate: 0.03
    cash_equivalents: 0.02
    college_inflation: 0.05
    medical_inflation: 0.05
  derisking_schedule:
    equities:
      start_age: 40
      end_age: 75
      transition_to: "bonds"

tax_rules:
  inflate_brackets: true
  reference_year: 2026
  inflation_ref: "general_inflation_rate"
  federal:
    standard_deduction: 32200.0
    brackets:
      - limit: 24800.0
        rate: 0.10
      - limit: 100800.0
        rate: 0.12
      - limit: 211400.0
        rate: 0.22
      - limit: 403550.0
        rate: 0.24
      - limit: 512450.0
        rate: 0.32
      - limit: 768700.0
        rate: 0.35
      - limit: .inf
        rate: 0.37
  capital_gains:
    brackets:
      - limit: 94050.0
        rate: 0.0
      - limit: 583750.0
        rate: 0.15
      - limit: .inf
        rate: 0.20

accounts:
  - id: "checking_primary_joint"
    name: "Joint Household Checking & Savings"
    type: "liquid"
    balance: 60000.0
    growth_rate_ref: "cash_equivalents"
    is_cash_reserve: true
    min_target_balance: 15000.0
    max_target_balance: 50000.0

  - id: "brokerage_primary"
    name: "Taxable Brokerage"
    type: "taxable_brokerage"
    balance: 200000.0
    growth_rate_ref: "equities"
    cost_basis: 120000.0

  - id: "retirement_pretax"
    name: "Pre-Tax Retirement (401k/Traditional IRA)"
    type: "traditional_401k"
    balance: 80000.0
    growth_rate_ref: "equities"

  - id: "retirement_roth"
    name: "Roth IRA"
    type: "roth_ira"
    balance: 100000.0
    growth_rate_ref: "equities"
    cost_basis: 100000.0

  - id: "college_529"
    name: "College 529 Plans"
    type: "taxable_brokerage"
    balance: 20000.0
    growth_rate_ref: "equities"
    cost_basis: 20000.0

waterfall_strategy:
  surplus_allocation:
    - account_id: "checking_primary_joint"
      max_annual_contribution: 50000.0
    - account_id: "brokerage_primary"
    - account_id: "retirement_roth"
      max_annual_contribution: 0
    - account_id: "retirement_pretax"
      max_annual_contribution: 0

  deficit_drawdown_order:
    - account_id: "checking_primary_joint"
    - account_id: "brokerage_primary"
    - account_id: "retirement_pretax"
    - account_id: "retirement_roth"

events:
  # ==========================================
  # INCOME & RETIREMENT CONTRIBUTIONS
  # ==========================================
  - id: "primary_salary"
    name: "Primary Earner Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: *retirement
    base_amount: 125000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    is_earned_income: true
    gap_years: []
    step_adjustments:
      2036: 1.05
      2046: 1.1025
      2056: 1.157625

  - id: "secondary_salary"
    name: "Secondary Earner Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: *retirement
    base_amount: 80000.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    is_earned_income: true
    gap_years: []

  - id: "retirement_contributions_pretax"
    name: "Pre-Tax Retirement Contributions"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *retirement
    base_amount: 18000
    reference_year: 2026
    target_account_id: retirement_pretax
    inflation_ref: "general_inflation_rate"
    is_pre_tax_deduction: true
    tags: ["Investments"]

  - id: "retirement_contributions_roth"
    name: "Roth IRA Contributions"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *retirement
    base_amount: 14000
    reference_year: 2026
    target_account_id: retirement_roth
    inflation_ref: "general_inflation_rate"
    is_pre_tax_deduction: false
    tags: ["Investments"]

  - id: "college_529_contributions"
    name: "College 529 Contributions"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2042
    base_amount: 10000
    reference_year: 2026
    target_account_id: college_529
    inflation_ref: "general_inflation_rate"
    is_pre_tax_deduction: false
    tags: ["Investments", "Children"]

  - id: "social_security_primary"
    name: "Social Security - Primary Earner"
    type: "cash_stream"
    category: "income"
    start_year: *social_security_start
    end_year: *end_year
    base_amount: *ss_primary_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    is_earned_income: false
    step_adjustments:
      2061: *social_security_enabled

  - id: "social_security_secondary"
    name: "Social Security - Secondary Earner"
    type: "cash_stream"
    category: "income"
    start_year: *social_security_start
    end_year: *end_year
    base_amount: *ss_secondary_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    is_earned_income: false
    step_adjustments:
      2061: *social_security_enabled

  # ==========================================
  # Children
  # ==========================================
  - id: "daycare_kid1"
    name: "Daycare - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2029
    base_amount: *daycare_base
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "daycare_kid2"
    name: "Daycare - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2031
    base_amount: *daycare_base
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "afterschool_care_kid1"
    name: "Afterschool Care - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2029
    end_year: 2036
    base_amount: *afterschool_care_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "afterschool_care_kid2"
    name: "Afterschool Care - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2031
    end_year: 2038
    base_amount: *afterschool_care_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "college_tuition_kid1"
    name: "College Tuition & Room/Board - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2042
    end_year: 2045
    base_amount: *college_base
    reference_year: 2026
    inflation_ref: "college_inflation"
    tags: ["Children"]

  - id: "college_tuition_kid2"
    name: "College Tuition & Room/Board - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2044
    end_year: 2047
    base_amount: *college_base
    reference_year: 2026
    inflation_ref: "college_inflation"
    tags: ["Children"]

  - id: "college_529_liquidation_2042"
    name: "529 to Checking (College 2042)"
    type: "account_liquidation"
    trigger_year: 2042
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 58360.0
    tags: ["Investments", "Children"]

  - id: "college_529_liquidation_2043"
    name: "529 to Checking (College 2043)"
    type: "account_liquidation"
    trigger_year: 2043
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 61278.0
    tags: ["Investments", "Children"]

  - id: "college_529_liquidation_2044"
    name: "529 to Checking (College 2044)"
    type: "account_liquidation"
    trigger_year: 2044
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 64342.0
    tags: ["Investments", "Children"]

  - id: "college_529_liquidation_2045"
    name: "529 to Checking (College 2045)"
    type: "account_liquidation"
    trigger_year: 2045
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 67559.0
    tags: ["Investments", "Children"]

  - id: "college_529_liquidation_2046"
    name: "529 to Checking (College 2046)"
    type: "account_liquidation"
    trigger_year: 2046
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 70937.0
    tags: ["Investments", "Children"]

  - id: "college_529_liquidation_2047"
    name: "529 to Checking (College 2047)"
    type: "account_liquidation"
    trigger_year: 2047
    source_account_id: college_529
    target_account_id: checking_primary_joint
    amount: 74484.0
    tags: ["Investments", "Children"]

  - id: "wedding_kid1"
    name: "Kid's Wedding 1"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_one_wedding
    end_year: *kid_one_wedding
    base_amount: *wedding_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Life Events", "Children"]

  - id: "wedding_kid2"
    name: "Kid's Wedding 2"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_two_wedding
    end_year: *kid_two_wedding
    base_amount: *wedding_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Life Events", "Children"]

  - id: "transportation_kids_vehicle_1"
    name: "Kid's First Vehicle 1"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_one_car
    end_year: *kid_one_car
    base_amount: *kid_car_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation", "Children"]

  - id: "transportation_kids_vehicle_2"
    name: "Kid's First Vehicle 2"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_two_car
    end_year: *kid_two_car
    base_amount: *kid_car_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation", "Children"]

  - id: "summer_camps_kid1"
    name: "Summer Camps - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *summer_camps_start
    end_year: 2041
    base_amount: *summer_camps_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "summer_camps_kid2"
    name: "Summer Camps - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2031
    end_year: 2043
    base_amount: *summer_camps_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "back_to_school_kid1"
    name: "Back to School - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *back_to_school_start
    end_year: *kid_one_18
    base_amount: *back_to_school_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "back_to_school_kid2"
    name: "Back to School - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: *back_to_school_start
    end_year: *kid_two_18
    base_amount: *back_to_school_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "school_field_trips_kid1"
    name: "School Field Trips - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *school_field_trips_start
    end_year: *kid_one_18
    base_amount: *school_field_trips_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "school_field_trips_kid2"
    name: "School Field Trips - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: *school_field_trips_start
    end_year: *kid_two_18
    base_amount: *school_field_trips_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "extracurriculars_kid1"
    name: "Extracurriculars - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *extracurriculars_start
    end_year: *kid_one_18
    base_amount: *kids_extracurricular_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "extracurriculars_kid2"
    name: "Extracurriculars - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: *extracurriculars_start
    end_year: *kid_two_18
    base_amount: *kids_extracurricular_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "birthday_parties_kid1"
    name: "Birthday Party - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *birthday_parties_start
    end_year: *kid_one_18
    base_amount: *kids_bday_party_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "birthday_parties_kid2"
    name: "Birthday Party - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: *birthday_parties_start
    end_year: *kid_two_18
    base_amount: *kids_bday_party_per_kid
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "allowances_kid1"
    name: "Allowance - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: *allowances_start
    end_year: *kid_one_18
    base_amount: *kids_allowance_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "allowances_kid2"
    name: "Allowance - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2034
    end_year: *kid_two_18
    base_amount: *kids_allowance_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  - id: "kids_laptop_kid1"
    name: "Laptop - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2036
    end_year: *kid_one_18
    base_amount: *kids_laptop_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2037, 2038, 2040, 2041]
    tags: ["Children", "Technology"]

  - id: "kids_laptop_kid2"
    name: "Laptop - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2038
    end_year: *kid_two_18
    base_amount: *kids_laptop_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2039, 2040, 2042, 2043]
    tags: ["Children", "Technology"]

  - id: "healthcare_orthodontics_braces_kid1"
    name: "Orthodontics / Braces (Kid 1)"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_one_braces
    end_year: *kid_one_braces_end
    base_amount: *braces_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  - id: "healthcare_orthodontics_braces_kid2"
    name: "Orthodontics / Braces (Kid 2)"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_two_braces
    end_year: *kid_two_braces_end
    base_amount: *braces_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  # ==========================================
  # Food and Living
  # ==========================================
  - id: "groceries_adult1"
    name: "Groceries - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *grocery_base_individual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "groceries_adult2"
    name: "Groceries - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *grocery_base_individual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "groceries_kid1"
    name: "Groceries - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_22
    base_amount: *grocery_base_individual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "groceries_kid2"
    name: "Groceries - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_22
    base_amount: *grocery_base_individual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "dining_out"
    name: "Dining Out / Takeout / Coffee"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *dining_out_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "household_supplies"
    name: "Household Supplies"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *household_supplies_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "adult_clothing_adult1"
    name: "Adult Clothing & Shoe Replacements - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *adult_clothing_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "adult_clothing_adult2"
    name: "Adult Clothing & Shoe Replacements - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *adult_clothing_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "adult_clothing_kid1"
    name: "Adult Clothing & Shoe Replacements - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_18
    base_amount: *adult_clothing_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "adult_clothing_kid2"
    name: "Adult Clothing & Shoe Replacements - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_18
    base_amount: *adult_clothing_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "haircuts_adult1"
    name: "Haircuts / Personal Grooming - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *haircuts_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "haircuts_adult2"
    name: "Haircuts / Personal Grooming - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *haircuts_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living"]

  - id: "haircuts_kid1"
    name: "Haircuts / Personal Grooming - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_18
    base_amount: *haircuts_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "haircuts_kid2"
    name: "Haircuts / Personal Grooming - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_18
    base_amount: *haircuts_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Food & Living", "Children"]

  - id: "small_appliance_replacements"
    name: "Small Appliance Replacements"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *small_appliance_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2027, 2028, 2030, 2031, 2032, 2034, 2035, 2036, 2038, 2039, 2040, 2042, 2043, 2044, 2046, 2047, 2048, 2050, 2051, 2052, 2054, 2055, 2056, 2058, 2059, 2060, 2062, 2063, 2064, 2066, 2067, 2068, 2070, 2071, 2072, 2074, 2075, 2076, 2078, 2079]
    tags: ["Food & Living"]

  - id: "diapers_wipes"
    name: "Diapers and Wipes (per kid)"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2028
    base_amount: *diapers_wipes_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Children"]

  # ==========================================
  # Healthcare
  # ==========================================
  - id: "healthcare_premiums_adult1"
    name: "Healthcare Premiums - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *medical_premium_individual
    reference_year: 2026
    inflation_ref: "medical_inflation"
    step_adjustments:
      2059: *medicare_multiplier_65
      2069: *medicare_multiplier_75
      2074: *medicare_multiplier_80
      2079: *medicare_multiplier_85
    tags: ["Healthcare"]

  - id: "healthcare_premiums_adult2"
    name: "Healthcare Premiums - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *medical_premium_individual
    reference_year: 2026
    inflation_ref: "medical_inflation"
    step_adjustments:
      2059: *medicare_multiplier_65
      2069: *medicare_multiplier_75
      2074: *medicare_multiplier_80
      2079: *medicare_multiplier_85
    tags: ["Healthcare"]

  - id: "healthcare_premiums_kid1"
    name: "Healthcare Premiums - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_22
    base_amount: *medical_premium_individual
    reference_year: 2026
    inflation_ref: "medical_inflation"
    tags: ["Healthcare", "Children"]

  - id: "healthcare_premiums_kid2"
    name: "Healthcare Premiums - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_22
    base_amount: *medical_premium_individual
    reference_year: 2026
    inflation_ref: "medical_inflation"
    tags: ["Healthcare", "Children"]

  - id: "long_term_care_assisted_living_adult1"
    name: "Long-Term Care / Assisted Living - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: *assisted_living_start
    end_year: *end_year
    base_amount: *assisted_living_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "long_term_care_assisted_living_adult2"
    name: "Long-Term Care / Assisted Living - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: *assisted_living_start_secondary
    end_year: *end_year
    base_amount: *assisted_living_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "healthcare_copays_adult1"
    name: "Healthcare Copays / Routine Meds - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *healthcare_copays_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "healthcare_copays_adult2"
    name: "Healthcare Copays / Routine Meds - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *healthcare_copays_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "healthcare_copays_kid1"
    name: "Healthcare Copays / Routine Meds - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_22
    base_amount: *healthcare_copays_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  - id: "healthcare_copays_kid2"
    name: "Healthcare Copays / Routine Meds - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_22
    base_amount: *healthcare_copays_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  - id: "healthcare_out_of_pocket_emergencies_adult1"
    name: "Out-of-Pocket Medical Emergencies - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2028
    end_year: *end_year
    base_amount: *out_of_pocket_medical_emergency
    gap_years: [2029, 2030, 2031, 2032, 2034, 2035, 2036, 2037, 2039, 2040, 2041, 2042, 2044, 2045, 2046, 2047, 2049, 2050, 2051, 2052, 2054, 2055, 2056, 2057, 2059, 2060, 2061, 2062, 2064, 2065, 2066, 2067, 2069, 2070, 2071, 2072, 2074, 2075, 2076, 2077, 2079, 2080]
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "healthcare_out_of_pocket_emergencies_adult2"
    name: "Out-of-Pocket Medical Emergencies - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2028
    end_year: *end_year
    base_amount: *out_of_pocket_medical_emergency
    gap_years: [2029, 2030, 2031, 2032, 2034, 2035, 2036, 2037, 2039, 2040, 2041, 2042, 2044, 2045, 2046, 2047, 2049, 2050, 2051, 2052, 2054, 2055, 2056, 2057, 2059, 2060, 2061, 2062, 2064, 2065, 2066, 2067, 2069, 2070, 2071, 2072, 2074, 2075, 2076, 2077, 2079, 2080]
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "otc_meds_adult1"
    name: "OTC Medications / First Aid - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *otc_meds_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "otc_meds_adult2"
    name: "OTC Medications / First Aid - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *otc_meds_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare"]

  - id: "otc_meds_kid1"
    name: "OTC Medications / First Aid - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_one_22
    base_amount: *otc_meds_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  - id: "otc_meds_kid2"
    name: "OTC Medications / First Aid - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *kid_two_22
    base_amount: *otc_meds_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Healthcare", "Children"]

  # ==========================================
  # Housing
  # ==========================================
  - id: "primary_residence_acquisition"
    name: "Primary Residence Purchase"
    type: "asset_purchase"
    trigger_year: 2026
    down_payment: 100000.0
    asset_name: "Family Home"
    asset_initial_value: 400000.0
    growth_rate_ref: "real_estate"
    mortgage:
      principal: 300000.0
      interest_rate: 0.065
      term_years: 30
    costs:
      tax: 0.019
      insurance: 0.015
      maintainance: 0.02
      HOA: 0.0048
    purchase_fees:
      closing_costs: 0.03
      title_insurance: 0.005
    tags: ["Housing"]

  - id: "family_home_liquidation"
    name: "Sell Family Home (Downsize)"
    type: "asset_liquidation"
    trigger_year: *retirement
    asset_name: "Family Home"
    primary_residence_exclusion: 500000.0
    sale_fees:
      agent_commission: 0.06
      closing_costs: 0.02
    tags: ["Housing"]

  - id: "retirement_home_acquisition"
    name: "Retirement Home Purchase"
    type: "asset_purchase"
    trigger_year: *retirement
    down_payment: 350000.0
    asset_name: "Retirement Home"
    asset_initial_value: 350000.0
    growth_rate_ref: "real_estate"
    mortgage: null
    costs:
      tax: 0.015
      insurance: 0.01
      maintainance: 0.01
      HOA: 0.008
    purchase_fees:
      closing_costs: 0.03
      title_insurance: 0.005
    tags: ["Housing"]

  - id: "retirement_home_liquidation"
    name: "Sell Retirement Home (Assisted Living)"
    type: "asset_liquidation"
    trigger_year: *assisted_living_start
    asset_name: "Retirement Home"
    primary_residence_exclusion: 500000.0
    sale_fees:
      agent_commission: 0.06
      closing_costs: 0.02
    tags: ["Housing"]

  - id: "housing_maintenance_kitchen_remodel"
    name: "Kitchen Remodel"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *kitchen_remodel_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2037, 2038, 2039, 2041, 2042, 2043, 2044, 2045, 2046, 2047, 2048, 2049, 2050, 2051, 2052, 2053, 2054, 2056, 2057, 2058, 2059, 2060, 2061, 2062, 2063, 2064, 2065, 2066, 2067, 2068, 2069, 2071, 2072, 2073, 2074, 2075, 2076, 2077, 2078, 2079]
    tags: ["Housing"]

  - id: "home_furniture_upgrade"
    name: "Home Furniture and Mattress Overhaul"
    type: "cash_stream"
    category: "expense"
    start_year: *home_furniture_start
    end_year: *home_furniture_end
    gap_years: [2033, 2034, 2035, 2036, 2037, 2038, 2039, 2040, 2041, 2043, 2044, 2045, 2046, 2047, 2048, 2049, 2050, 2051, 2053, 2054, 2055]
    base_amount: *furniture_upgrade_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Housing"]

  - id: "deck_patio_build"
    name: "Deck / Patio Build or Upgrade"
    type: "cash_stream"
    category: "expense"
    start_year: 2040
    end_year: 2040
    base_amount: *deck_patio_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Housing"]

  - id: "hvac_filters"
    name: "HVAC Filters"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *hvac_filters_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Housing"]

  # ==========================================
  # Transportation
  # ==========================================
  - id: "vehicles_adult1"
    name: "Vehicle Replacements - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *vehicle_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2037, 2038, 2039, 2040, 2041, 2042, 2043, 2044, 2045, 2047, 2048, 2049, 2050, 2051, 2052, 2053, 2054, 2055, 2057, 2058, 2059, 2060, 2061, 2062, 2063, 2064, 2065, 2067, 2068, 2069, 2070, 2071, 2072, 2073, 2074, 2075, 2077, 2078, 2079]
    tags: ["Transportation"]

  - id: "vehicles_adult2"
    name: "Vehicle Replacements - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2031
    end_year: *end_year
    base_amount: *vehicle_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2032, 2033, 2034, 2035, 2036, 2037, 2038, 2039, 2040, 2042, 2043, 2044, 2045, 2046, 2047, 2048, 2049, 2050, 2052, 2053, 2054, 2055, 2056, 2057, 2058, 2059, 2060, 2062, 2063, 2064, 2065, 2066, 2067, 2068, 2069, 2070, 2072, 2073, 2074, 2075, 2076, 2077, 2078, 2079]
    tags: ["Transportation"]

  - id: "auto_tires_adult1"
    name: "Auto Tires - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *auto_tires_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation"]

  - id: "auto_brakes_adult1"
    name: "Auto Brake Pads and Rotors - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *auto_brakes_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation"]

  - id: "auto_body_repair_adult1"
    name: "Auto Body Repair / Insurance Deductibles - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *auto_body_repair_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation"]

  - id: "fuel_gas"
    name: "Monthly Fuel / Gas"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *fuel_gas_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation"]

  - id: "tolls_parking"
    name: "Tolls / Parking Fees"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *tolls_parking_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Transportation"]

  # ==========================================
  # Utilities
  # ==========================================
  - id: "utilities_electricity"
    name: "Electricity"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *electricity_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  - id: "utilities_water_sewer_trash"
    name: "Water/Sewer/Trash"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *water_sewer_trash_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  - id: "utilities_internet"
    name: "Internet"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *internet_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  - id: "utilities_cell_phone_adult1"
    name: "Cell Phone Plan - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *cell_phone_per_line_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  - id: "utilities_cell_phone_adult2"
    name: "Cell Phone Plan - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *cell_phone_per_line_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  - id: "utilities_cell_phone_kid1"
    name: "Cell Phone Plan - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2036
    end_year: *kid_one_22
    base_amount: *cell_phone_per_line_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities", "Children"]

  - id: "utilities_cell_phone_kid2"
    name: "Cell Phone Plan - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2038
    end_year: *kid_two_22
    base_amount: *cell_phone_per_line_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities", "Children"]

  - id: "utilities_digital_subscriptions"
    name: "Digital Subscriptions (Streaming/E-books)"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *digital_subscriptions_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Utilities"]

  # ==========================================
  # Insurance
  # ==========================================
  - id: "homeowners_deductible"
    name: "Homeowners Insurance Deductible Events"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *homeowners_deductible
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance"]

  - id: "auto_insurance"
    name: "Auto Insurance Premiums"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *auto_insurance_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance"]

  - id: "auto_insurance_kid1"
    name: "Auto Insurance Premiums - Kid 1 (Teen Driver)"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_one_car
    end_year: *kid_one_22
    base_amount: 1800.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance", "Children"]

  - id: "auto_insurance_kid2"
    name: "Auto Insurance Premiums - Kid 2 (Teen Driver)"
    type: "cash_stream"
    category: "expense"
    start_year: *kid_two_car
    end_year: *kid_two_22
    base_amount: 1800.0
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance", "Children"]

  - id: "term_life"
    name: "Term Life Insurance Premiums"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: 2059
    base_amount: *term_life_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance"]

  - id: "disability_insurance"
    name: "Disability Insurance Premiums"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *retirement
    base_amount: *disability_insurance_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Insurance"]

  # ==========================================
  # Technology
  # ==========================================
  - id: "digital_security"
    name: "Digital Security / Cloud Subscriptions"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *digital_security_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Technology"]

  - id: "smartphone_upgrades_adult1"
    name: "Smartphone Upgrades - Adult 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *smartphone_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Technology"]

  - id: "smartphone_upgrades_adult2"
    name: "Smartphone Upgrades - Adult 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *smartphone_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Technology"]

  - id: "smartphone_upgrades_kid1"
    name: "Smartphone Upgrades - Kid 1"
    type: "cash_stream"
    category: "expense"
    start_year: 2036
    end_year: *kid_one_22
    base_amount: *smartphone_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Technology", "Children"]

  - id: "smartphone_upgrades_kid2"
    name: "Smartphone Upgrades - Kid 2"
    type: "cash_stream"
    category: "expense"
    start_year: 2038
    end_year: *kid_two_22
    base_amount: *smartphone_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Technology", "Children"]

  # ==========================================
  # Travel and Discretionary
  # ==========================================
  - id: "travel_major_family_vacations"
    name: "Family Vacations"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *family_vacation_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  - id: "family_photos"
    name: "Family Photos"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *family_photos_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  - id: "anniversary_trips"
    name: "Anniversary Trips"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *anniversary_trip_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2027, 2028, 2029, 2031, 2032, 2033, 2034, 2036, 2037, 2038, 2039, 2041, 2042, 2043, 2044, 2046, 2047, 2048, 2049, 2051, 2052, 2053, 2054, 2056, 2057, 2058, 2059, 2061, 2062, 2063, 2064, 2066, 2067, 2068, 2069, 2071, 2072, 2073, 2074, 2076, 2077, 2078, 2079]
    tags: ["Travel & Discretionary"]

  - id: "holiday_gifts"
    name: "Holiday Gifts"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *holiday_gifts_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  - id: "charitable_giving"
    name: "Charitable Giving / Donations"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *charitable_giving_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  - id: "passports_tsa"
    name: "Passports / TSA PreCheck"
    type: "cash_stream"
    category: "expense"
    start_year: *passport_tsa_start
    end_year: *end_year
    base_amount: *passport_tsa_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    gap_years: [2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2036, 2037, 2038, 2039, 2040, 2041, 2042, 2043, 2044, 2045, 2046, 2047, 2048, 2049, 2050, 2051, 2052, 2053, 2054, 2056, 2057, 2058, 2059, 2060, 2061, 2062, 2063, 2064, 2065, 2066, 2067, 2068, 2069, 2070, 2071, 2072, 2073, 2074, 2075, 2076, 2077, 2078, 2079]
    tags: ["Travel & Discretionary"]

  - id: "entertainment"
    name: "Entertainment (Movies, Outings)"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *entertainment_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  - id: "date_nights"
    name: "Date Nights"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *date_nights_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Travel & Discretionary"]

  # ==========================================
  # Life Events
  # ==========================================
  - id: "life_events_funeral"
    name: "Funeral / End of Life Expenses"
    type: "cash_stream"
    category: "expense"
    start_year: *end_year
    end_year: *end_year
    base_amount: *funeral_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Life Events"]

  # ==========================================
  # Pets
  # ==========================================
  - id: "vet_emergencies"
    name: "Veterinary Emergencies"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *vet_emergency_cost
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Pets"]

  - id: "pet_care"
    name: "Pet Care (Vaccines, Checkups, Food)"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *pet_care_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Pets"]

  # ==========================================
  # Legal
  # ==========================================
  - id: "legal_fees"
    name: "Legal Fees (Minor Disputes)"
    type: "cash_stream"
    category: "expense"
    start_year: 2026
    end_year: *end_year
    base_amount: *legal_fees_annual
    reference_year: 2026
    inflation_ref: "general_inflation_rate"
    tags: ["Legal"]
```

You can run this exact file directly:

```bash
python3 main.py            # defaults to scenarios/generic-demo.yaml
python3 main.py generic-demo
```

The dashboard (`api.py`) also lists this scenario under its `scenario_name`
and exposes its `.variable_meta` controls in the "Life Decisions" panel.
