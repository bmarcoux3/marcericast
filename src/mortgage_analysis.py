"""
Mortgage What-If Analysis Sidecar

This module provides mortgage affordability analysis and scenario testing
without modifying core simulation logic. It's a pure analysis layer that
can be used independently or alongside the main simulation.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class MortgageParams:
    """Parameters for a mortgage scenario."""
    home_price: float
    down_payment: float
    interest_rate: float  # Annual rate (e.g., 0.065 for 6.5%)
    term_years: int = 30
    property_tax_rate: float = 0.0  # Annual as percentage of home value
    insurance_rate: float = 0.0     # Annual as percentage of home value
    hoa_fee: float = 0.0            # Monthly HOA fee
    pmi_rate: float = 0.0           # Annual PMI rate (if down payment < 20%)


@dataclass
class AffordabilityResult:
    """Result of affordability analysis."""
    monthly_payment: float
    monthly_principal_interest: float
    monthly_property_tax: float
    monthly_insurance: float
    monthly_hoa: float
    monthly_pmi: float
    total_monthly: float
    loan_amount: float
    down_payment_pct: float
    max_affordable_price: Optional[float] = None


@dataclass
class AmortizationRow:
    """Single row in amortization schedule."""
    year: int
    beginning_balance: float
    payment: float
    principal: float
    interest: float
    ending_balance: float
    cumulative_principal: float
    cumulative_interest: float


def calculate_monthly_payment(principal: float, annual_rate: float, term_years: int) -> float:
    """Calculate monthly mortgage payment (principal + interest only)."""
    if principal <= 0 or term_years <= 0:
        return 0.0
    if annual_rate <= 0:
        return principal / (term_years * 12)

    monthly_rate = annual_rate / 12
    num_payments = term_years * 12
    payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -num_payments)
    return payment


def calculate_affordability(
    monthly_income: float,
    max_dti_ratio: float = 0.36,  # Standard debt-to-income ratio
    existing_monthly_debts: float = 0.0,
    params: Optional[MortgageParams] = None,
) -> AffordabilityResult:
    """
    Calculate mortgage affordability based on income and DTI ratio.

    Args:
        monthly_income: Gross monthly income
        max_dti_ratio: Maximum debt-to-income ratio (default 36%)
        existing_monthly_debts: Other monthly debt payments (car, student loans, etc.)
        params: Mortgage parameters (if None, uses defaults for calculation)

    Returns:
        AffordabilityResult with payment breakdown and max affordable price
    """
    max_monthly_debt = monthly_income * max_dti_ratio
    available_for_mortgage = max_monthly_debt - existing_monthly_debts

    if params is None:
        # Default params for reverse calculation
        params = MortgageParams(
            home_price=500000,
            down_payment=100000,
            interest_rate=0.065,
            term_years=30,
        )

    loan_amount = params.home_price - params.down_payment
    down_payment_pct = params.down_payment / params.home_price if params.home_price > 0 else 0

    # Principal & Interest
    monthly_pi = calculate_monthly_payment(loan_amount, params.interest_rate, params.term_years)

    # Property tax (annual / 12)
    monthly_tax = (params.home_price * params.property_tax_rate) / 12

    # Insurance (annual / 12)
    monthly_insurance = (params.home_price * params.insurance_rate) / 12

    # HOA
    monthly_hoa = params.hoa_fee

    # PMI (if down payment < 20%)
    monthly_pmi = 0.0
    if down_payment_pct < 0.20 and params.pmi_rate > 0:
        monthly_pmi = (loan_amount * params.pmi_rate) / 12

    total_monthly = monthly_pi + monthly_tax + monthly_insurance + monthly_hoa + monthly_pmi

    # Calculate max affordable price if total exceeds available
    max_affordable_price = None
    if total_monthly > available_for_mortgage and available_for_mortgage > 0:
        # Reverse calculate: solve for home_price where total_monthly == available_for_mortgage
        # This is iterative since PMI depends on down payment %
        max_affordable_price = _reverse_calculate_max_price(
            available_for_mortgage=available_for_mortgage,
            down_payment_pct=down_payment_pct,
            interest_rate=params.interest_rate,
            term_years=params.term_years,
            property_tax_rate=params.property_tax_rate,
            insurance_rate=params.insurance_rate,
            hoa_fee=params.hoa_fee,
            pmi_rate=params.pmi_rate,
        )

    return AffordabilityResult(
        monthly_payment=monthly_pi,
        monthly_principal_interest=monthly_pi,
        monthly_property_tax=monthly_tax,
        monthly_insurance=monthly_insurance,
        monthly_hoa=monthly_hoa,
        monthly_pmi=monthly_pmi,
        total_monthly=total_monthly,
        loan_amount=loan_amount,
        down_payment_pct=down_payment_pct,
        max_affordable_price=max_affordable_price,
    )


def _reverse_calculate_max_price(
    available_for_mortgage: float,
    down_payment_pct: float,
    interest_rate: float,
    term_years: int,
    property_tax_rate: float,
    insurance_rate: float,
    hoa_fee: float,
    pmi_rate: float,
    tolerance: float = 1.0,
    max_iterations: int = 100,
) -> float:
    """
    Reverse calculate maximum affordable home price using binary search.
    """
    # Better upper bound: assume all available goes to P&I, solve for loan
    # Loan = payment * (1 - (1+r)^-n) / r
    if interest_rate > 0:
        monthly_rate = interest_rate / 12
        num_payments = term_years * 12
        max_loan = available_for_mortgage * (1 - (1 + monthly_rate) ** -num_payments) / monthly_rate
        high = max_loan / (1 - down_payment_pct) * 1.2  # 20% buffer
    else:
        high = available_for_mortgage * 12 * term_years / (1 - down_payment_pct)

    low = 0.0
    best_price = 0.0

    for _ in range(max_iterations):
        mid = (low + high) / 2
        down_payment = mid * down_payment_pct
        loan_amount = mid - down_payment

        monthly_pi = calculate_monthly_payment(loan_amount, interest_rate, term_years)
        monthly_tax = (mid * property_tax_rate) / 12
        monthly_insurance = (mid * insurance_rate) / 12
        monthly_pmi = 0.0
        if down_payment_pct < 0.20 and pmi_rate > 0:
            monthly_pmi = (loan_amount * pmi_rate) / 12

        total = monthly_pi + monthly_tax + monthly_insurance + hoa_fee + monthly_pmi

        if abs(total - available_for_mortgage) < tolerance:
            return mid

        if total < available_for_mortgage:
            best_price = mid
            low = mid
        else:
            high = mid

    return best_price


def generate_amortization_schedule(
    principal: float,
    annual_rate: float,
    term_years: int,
    extra_monthly_payment: float = 0.0,
) -> List[AmortizationRow]:
    """
    Generate full amortization schedule.

    Args:
        principal: Loan amount
        annual_rate: Annual interest rate
        term_years: Loan term in years
        extra_monthly_payment: Optional extra payment per month toward principal

    Returns:
        List of AmortizationRow for each year
    """
    monthly_payment = calculate_monthly_payment(principal, annual_rate, term_years)
    monthly_rate = annual_rate / 12
    num_payments = term_years * 12

    schedule = []
    balance = principal
    cumulative_principal = 0.0
    cumulative_interest = 0.0

    for year in range(1, term_years + 1):
        beginning_balance = balance
        year_principal = 0.0
        year_interest = 0.0

        for month in range(12):
            if balance <= 0:
                break
            interest_payment = balance * monthly_rate
            principal_payment = monthly_payment - interest_payment + extra_monthly_payment
            principal_payment = min(principal_payment, balance)

            balance -= principal_payment
            year_principal += principal_payment
            year_interest += interest_payment

        cumulative_principal += year_principal
        cumulative_interest += year_interest

        schedule.append(AmortizationRow(
            year=year,
            beginning_balance=beginning_balance,
            payment=monthly_payment * 12,
            principal=year_principal,
            interest=year_interest,
            ending_balance=max(0, balance),
            cumulative_principal=cumulative_principal,
            cumulative_interest=cumulative_interest,
        ))

        if balance <= 0:
            break

    return schedule


def compare_scenarios(
    base_params: MortgageParams,
    variations: List[Dict[str, Any]],
    monthly_income: float,
    max_dti_ratio: float = 0.36,
    existing_monthly_debts: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Compare multiple mortgage scenarios side by side.

    Args:
        base_params: Base mortgage parameters
        variations: List of dicts with parameter overrides (e.g., {"interest_rate": 0.07})
        monthly_income: Gross monthly income for affordability check
        max_dti_ratio: Maximum DTI ratio
        existing_monthly_debts: Other monthly debts

    Returns:
        List of scenario results for comparison
    """
    results = []

    # Base scenario
    base_result = calculate_affordability(
        monthly_income=monthly_income,
        max_dti_ratio=max_dti_ratio,
        existing_monthly_debts=existing_monthly_debts,
        params=base_params,
    )
    results.append({
        "name": "Base",
        "params": base_params,
        "result": base_result,
    })

    # Variation scenarios
    for i, var in enumerate(variations):
        var_params = MortgageParams(
            home_price=var.get("home_price", base_params.home_price),
            down_payment=var.get("down_payment", base_params.down_payment),
            interest_rate=var.get("interest_rate", base_params.interest_rate),
            term_years=var.get("term_years", base_params.term_years),
            property_tax_rate=var.get("property_tax_rate", base_params.property_tax_rate),
            insurance_rate=var.get("insurance_rate", base_params.insurance_rate),
            hoa_fee=var.get("hoa_fee", base_params.hoa_fee),
            pmi_rate=var.get("pmi_rate", base_params.pmi_rate),
        )
        var_result = calculate_affordability(
            monthly_income=monthly_income,
            max_dti_ratio=max_dti_ratio,
            existing_monthly_debts=existing_monthly_debts,
            params=var_params,
        )
        results.append({
            "name": var.get("name", f"Scenario {i+1}"),
            "params": var_params,
            "result": var_result,
        })

    return results


def format_affordability_result(result: AffordabilityResult, params: MortgageParams) -> str:
    """Format affordability result as a readable string."""
    lines = [
        f"=== Mortgage Affordability Analysis ===",
        f"Home Price: ${params.home_price:,.2f}",
        f"Down Payment: ${params.down_payment:,.2f} ({result.down_payment_pct:.1%})",
        f"Loan Amount: ${result.loan_amount:,.2f}",
        f"Interest Rate: {params.interest_rate:.3%}",
        f"Term: {params.term_years} years",
        f"",
        f"Monthly Payment Breakdown:",
        f"  Principal & Interest: ${result.monthly_principal_interest:,.2f}",
        f"  Property Tax:         ${result.monthly_property_tax:,.2f}",
        f"  Insurance:            ${result.monthly_insurance:,.2f}",
        f"  HOA:                  ${result.monthly_hoa:,.2f}",
        f"  PMI:                  ${result.monthly_pmi:,.2f}",
        f"  ─────────────────────────────",
        f"  Total Monthly:        ${result.total_monthly:,.2f}",
        f"",
    ]
    if result.max_affordable_price:
        lines.append(f"Max Affordable Price (at DTI limit): ${result.max_affordable_price:,.2f}")
    return "\n".join(lines)


def format_comparison(results: List[Dict[str, Any]]) -> str:
    """Format multiple scenario comparison as a readable table."""
    lines = ["=== Mortgage Scenario Comparison ===", ""]
    header = f"{'Scenario':<20} {'Price':>12} {'Down':>10} {'Rate':>8} {'Term':>5} {'Monthly P&I':>14} {'Total Monthly':>14} {'Affordable':>12}"
    lines.append(header)
    lines.append("-" * len(header))

    for r in results:
        p = r["params"]
        res = r["result"]
        affordable = "Yes" if res.total_monthly <= (res.monthly_principal_interest * 3) else "No"
        if res.max_affordable_price:
            affordable = f"${res.max_affordable_price:,.0f}"

        line = f"{r['name']:<20} ${p.home_price:>11,.0f} ${p.down_payment:>9,.0f} {p.interest_rate:>7.3%} {p.term_years:>4}yr ${res.monthly_principal_interest:>13,.2f} ${res.total_monthly:>13,.2f} {affordable:>12}"
        lines.append(line)

    return "\n".join(lines)