#!/usr/bin/env python3
"""
Mortgage What-If Analysis CLI

A standalone tool for mortgage affordability analysis and scenario comparison.
Does not modify core simulation logic - pure analysis sidecar.
"""

import argparse
import sys
from src.mortgage_analysis import (
    MortgageParams,
    calculate_affordability,
    compare_scenarios,
    generate_amortization_schedule,
    format_affordability_result,
    format_comparison,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Mortgage What-If Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic affordability check
  python -m src.mortgage_cli --price 500000 --down 100000 --rate 0.065 --income 10000

  # Compare multiple scenarios
  python -m src.mortgage_cli --price 500000 --down 100000 --rate 0.065 --income 10000 \
    --compare rate=0.07 rate=0.075 rate=0.08

  # Show amortization schedule
  python -m src.mortgage_cli --price 500000 --down 100000 --rate 0.065 --amortize

  # What-if with property tax and insurance
  python -m src.mortgage_cli --price 500000 --down 100000 --rate 0.065 \
    --tax-rate 0.02 --insurance-rate 0.005 --hoa 300 --pmi 0.005
        """
    )

    # Basic parameters
    parser.add_argument("--price", type=float, required=True, help="Home price")
    parser.add_argument("--down", type=float, required=True, help="Down payment")
    parser.add_argument("--rate", type=float, required=True, help="Annual interest rate (e.g., 0.065 for 6.5%)")
    parser.add_argument("--term", type=int, default=30, help="Loan term in years (default: 30)")

    # Additional costs
    parser.add_argument("--tax-rate", type=float, default=0.0, help="Annual property tax rate (e.g., 0.02 for 2%)")
    parser.add_argument("--insurance-rate", type=float, default=0.0, help="Annual insurance rate (e.g., 0.005 for 0.5%)")
    parser.add_argument("--hoa", type=float, default=0.0, help="Monthly HOA fee")
    parser.add_argument("--pmi", type=float, default=0.0, help="Annual PMI rate (if down payment < 20%)")

    # Income for affordability
    parser.add_argument("--income", type=float, help="Gross monthly income for affordability analysis")
    parser.add_argument("--dti", type=float, default=0.36, help="Max debt-to-income ratio (default: 0.36)")
    parser.add_argument("--debts", type=float, default=0.0, help="Other monthly debt payments")

    # Output options
    parser.add_argument("--amortize", action="store_true", help="Show full amortization schedule")
    parser.add_argument("--compare", nargs="+", help="Compare scenarios (format: key=value,key=value...)")
    parser.add_argument("--extra-payment", type=float, default=0.0, help="Extra monthly payment toward principal")

    return parser.parse_args()


def parse_compare_args(compare_args: list) -> list:
    """Parse --compare arguments into list of variation dicts."""
    variations = []
    for arg in compare_args:
        var = {}
        for pair in arg.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                try:
                    var[key] = float(value)
                except ValueError:
                    var[key] = value
        if var:
            variations.append(var)
    return variations


def build_params_from_args(args, overrides=None) -> MortgageParams:
    """Build MortgageParams from args with optional overrides."""
    overrides = overrides or {}
    return MortgageParams(
        home_price=overrides.get("home_price", args.price),
        down_payment=overrides.get("down", args.down),
        interest_rate=overrides.get("interest_rate", overrides.get("rate", args.rate)),
        term_years=overrides.get("term_years", overrides.get("term", args.term)),
        property_tax_rate=overrides.get("property_tax_rate", overrides.get("tax_rate", args.tax_rate)),
        insurance_rate=overrides.get("insurance_rate", overrides.get("insurance_rate", args.insurance_rate)),
        hoa_fee=overrides.get("hoa_fee", overrides.get("hoa", args.hoa)),
        pmi_rate=overrides.get("pmi_rate", overrides.get("pmi", args.pmi)),
    )


def main():
    args = parse_args()

    # Build base params
    base_params = build_params_from_args(args)

    # If income provided, do affordability analysis
    if args.income:
        result = calculate_affordability(
            monthly_income=args.income,
            max_dti_ratio=args.dti,
            existing_monthly_debts=args.debts,
            params=base_params,
        )
        print(format_affordability_result(result, base_params))
        print()

    # If compare args provided, do scenario comparison
    if args.compare:
        variations = parse_compare_args(args.compare)
        # Build variation params
        var_params_list = [build_params_from_args(args, var) for var in variations]
        results = []

        # Base scenario
        base_result = calculate_affordability(
            monthly_income=args.income or 10000,
            max_dti_ratio=args.dti,
            existing_monthly_debts=args.debts,
            params=base_params,
        )
        results.append({
            "name": "Base",
            "params": base_params,
            "result": base_result,
        })

        # Variation scenarios
        for i, var_params in enumerate(var_params_list):
            var_result = calculate_affordability(
                monthly_income=args.income or 10000,
                max_dti_ratio=args.dti,
                existing_monthly_debts=args.debts,
                params=var_params,
            )
            results.append({
                "name": variations[i].get("name", f"Scenario {i+1}"),
                "params": var_params,
                "result": var_result,
            })

        print(format_comparison(results))
        print()

    # If amortize requested, show schedule
    if args.amortize:
        loan_amount = args.price - args.down
        schedule = generate_amortization_schedule(
            principal=loan_amount,
            annual_rate=args.rate,
            term_years=args.term,
            extra_monthly_payment=args.extra_payment,
        )

        print(f"=== Amortization Schedule ===")
        print(f"Loan Amount: ${loan_amount:,.2f}")
        print(f"Interest Rate: {args.rate:.3%}")
        print(f"Term: {args.term} years")
        if args.extra_payment > 0:
            print(f"Extra Monthly Payment: ${args.extra_payment:,.2f}")
        print()

        # Print header
        print(f"{'Year':>4} {'Begin Balance':>14} {'Payment':>12} {'Principal':>12} {'Interest':>12} {'End Balance':>14} {'Cum Principal':>14} {'Cum Interest':>14}")
        print("-" * 106)

        for row in schedule:
            print(f"{row.year:>4} ${row.beginning_balance:>13,.2f} ${row.payment:>11,.2f} ${row.principal:>11,.2f} ${row.interest:>11,.2f} ${row.ending_balance:>13,.2f} ${row.cumulative_principal:>13,.2f} ${row.cumulative_interest:>13,.2f}")

        # Summary
        if schedule:
            last = schedule[-1]
            print()
            print(f"Total Interest Paid: ${last.cumulative_interest:,.2f}")
            print(f"Total Principal Paid: ${last.cumulative_principal:,.2f}")
            print(f"Total Payments: ${sum(r.payment for r in schedule):,.2f}")

    # If no specific output requested, show basic payment
    if not args.income and not args.compare and not args.amortize:
        from src.mortgage_analysis import calculate_monthly_payment
        loan_amount = args.price - args.down
        monthly_pi = calculate_monthly_payment(loan_amount, args.rate, args.term)
        monthly_tax = (args.price * args.tax_rate) / 12
        monthly_insurance = (args.price * args.insurance_rate) / 12
        total = monthly_pi + monthly_tax + monthly_insurance + args.hoa

        print(f"Home Price: ${args.price:,.2f}")
        print(f"Down Payment: ${args.down:,.2f}")
        print(f"Loan Amount: ${loan_amount:,.2f}")
        print(f"Monthly P&I: ${monthly_pi:,.2f}")
        print(f"Monthly Tax: ${monthly_tax:,.2f}")
        print(f"Monthly Insurance: ${monthly_insurance:,.2f}")
        print(f"Monthly HOA: ${args.hoa:,.2f}")
        print(f"Total Monthly: ${total:,.2f}")


if __name__ == "__main__":
    main()