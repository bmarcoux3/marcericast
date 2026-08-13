from typing import List, Optional
from src.schema import TaxBracket, FederalTaxRules, CapitalGainsTaxRules, TaxRulesConfig, MacroeconomicsConfig
from src.inflation import calculate_inflated_amount


def calculate_bracket_tax(taxable_amount: float, brackets: List[TaxBracket]) -> float:
    """Calculates progressive tax across a sorted list of TaxBrackets."""
    if taxable_amount <= 0 or not brackets:
        return 0.0

    tax_owed = 0.0
    previous_limit = 0.0

    for bracket in brackets:
        if taxable_amount > previous_limit:
            amount_in_bracket = min(taxable_amount, bracket.limit) - previous_limit
            tax_owed += amount_in_bracket * bracket.rate
            previous_limit = bracket.limit
        else:
            break

    return tax_owed


class TaxCalculator:
    """Configurable tax engine driven entirely by declarative TaxRulesConfig with inflation indexation."""

    def __init__(self, config: TaxRulesConfig):
        self.config = config

    def _get_inflation_factor(self, current_year: Optional[int], macro: Optional[MacroeconomicsConfig]) -> float:
        if not self.config.inflate_brackets or not current_year or not self.config.reference_year or not macro:
            return 1.0

        inflation_rate = 0.0
        if self.config.inflation_ref == "general_inflation_rate":
            inflation_rate = macro.general_inflation_rate
        elif self.config.inflation_ref in macro.growth_rates:
            inflation_rate = macro.growth_rates[self.config.inflation_ref]

        years_elapsed = current_year - self.config.reference_year
        if years_elapsed <= 0:
            return 1.0

        return (1.0 + inflation_rate) ** years_elapsed

    def get_inflated_standard_deduction(self, current_year: Optional[int] = None, macro: Optional[MacroeconomicsConfig] = None) -> float:
        factor = self._get_inflation_factor(current_year, macro)
        return self.config.federal.standard_deduction * factor

    def get_inflated_federal_brackets(self, current_year: Optional[int] = None, macro: Optional[MacroeconomicsConfig] = None) -> List[TaxBracket]:
        factor = self._get_inflation_factor(current_year, macro)
        if factor == 1.0:
            return self.config.federal.brackets

        return [
            TaxBracket(
                limit=b.limit if b.limit == float("inf") else b.limit * factor,
                rate=b.rate,
            )
            for b in self.config.federal.brackets
        ]

    def get_inflated_cap_gains_brackets(self, current_year: Optional[int] = None, macro: Optional[MacroeconomicsConfig] = None) -> List[TaxBracket]:
        factor = self._get_inflation_factor(current_year, macro)
        if factor == 1.0:
            return self.config.capital_gains.brackets

        return [
            TaxBracket(
                limit=b.limit if b.limit == float("inf") else b.limit * factor,
                rate=b.rate,
            )
            for b in self.config.capital_gains.brackets
        ]

    def calculate_income_tax(self, agi: float, current_year: Optional[int] = None, macro: Optional[MacroeconomicsConfig] = None) -> float:
        std_deduction = self.get_inflated_standard_deduction(current_year, macro)
        taxable_income = max(0.0, agi - std_deduction)
        brackets = self.get_inflated_federal_brackets(current_year, macro)
        return calculate_bracket_tax(taxable_income, brackets)

    def calculate_cap_gains_tax(self, gains: float, current_year: Optional[int] = None, macro: Optional[MacroeconomicsConfig] = None) -> float:
        brackets = self.get_inflated_cap_gains_brackets(current_year, macro)
        return calculate_bracket_tax(gains, brackets)
