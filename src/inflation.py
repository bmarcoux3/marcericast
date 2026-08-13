from typing import Dict, Optional


def calculate_inflated_amount(
    base_amount: float,
    current_year: int,
    reference_year: Optional[int],
    inflation_rate: float,
    multiplier: float = 1.0,
) -> float:
    """
    Calculates an inflated cash flow amount relative to a reference year.
    If reference_year is None, returns base_amount * multiplier without inflation compounding.
    """
    if reference_year is None:
        return base_amount * multiplier

    years_elapsed = current_year - reference_year
    return (base_amount * multiplier) * ((1.0 + inflation_rate) ** years_elapsed)
