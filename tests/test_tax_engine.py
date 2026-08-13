import pytest
from src.schema import TaxBracket, FederalTaxRules, CapitalGainsTaxRules, TaxRulesConfig
from src.tax_engine import (
    calculate_bracket_tax,
    TaxCalculator,
)


@pytest.fixture
def sample_tax_config():
    return TaxRulesConfig(
        federal=FederalTaxRules(
            standard_deduction=32200,
            brackets=[
                TaxBracket(limit=24800, rate=0.10),
                TaxBracket(limit=100800, rate=0.12),
                TaxBracket(limit=211400, rate=0.22),
                TaxBracket(limit=float("inf"), rate=0.24),
            ],
        ),
        capital_gains=CapitalGainsTaxRules(
            brackets=[
                TaxBracket(limit=94050, rate=0.0),
                TaxBracket(limit=583750, rate=0.15),
                TaxBracket(limit=float("inf"), rate=0.20),
            ]
        ),
    )


def test_zero_or_negative_income():
    brackets = [TaxBracket(limit=10000, rate=0.10)]
    # 0 taxable income -> 0 * 10% = 0
    assert calculate_bracket_tax(0, brackets) == 0.0
    # Negative income clamped to 0 taxable -> 0 tax
    assert calculate_bracket_tax(-5000, brackets) == 0.0


def test_single_bracket_tax():
    brackets = [TaxBracket(limit=10000, rate=0.10), TaxBracket(limit=float("inf"), rate=0.20)]
    # $5,000 all at 10%
    assert calculate_bracket_tax(5000, brackets) == 500.0


def test_multi_bracket_progressive_tax():
    brackets = [
        TaxBracket(limit=10000, rate=0.10),
        TaxBracket(limit=30000, rate=0.20),
        TaxBracket(limit=float("inf"), rate=0.30),
    ]
    # $10k * 0.10 = $1,000
    # $20k * 0.20 = $4,000
    # $10k * 0.30 = $3,000
    # Total = $8,000
    assert calculate_bracket_tax(40000, brackets) == 8000.0


def test_federal_income_tax_under_standard_deduction(sample_tax_config):
    calc = TaxCalculator(sample_tax_config)
    # AGI below standard deduction ($32,200) -> 0 taxable income -> 0 tax
    assert calc.calculate_income_tax(30000) == 0.0
    assert calc.calculate_income_tax(32200) == 0.0


def test_federal_income_tax_above_standard_deduction(sample_tax_config):
    calc = TaxCalculator(sample_tax_config)
    # AGI = $57,000 -> Taxable = $57,000 - $32,200 = $24,800
    # Exactly hits 1st bracket limit ($24,800 @ 10%) -> $2,480.0
    assert calc.calculate_income_tax(57000) == 2480.0


def test_capital_gains_tax(sample_tax_config):
    calc = TaxCalculator(sample_tax_config)
    # $50,000 gain -> within 0% bracket limit of $94,050
    assert calc.calculate_cap_gains_tax(50000) == 0.0

    # $150,000 gain -> $94,050 @ 0% + ($150,000 - $94,050) @ 15%
    # 55,950 * 0.15 = 8,392.50
    assert calc.calculate_cap_gains_tax(150000) == pytest.approx(8392.50)
