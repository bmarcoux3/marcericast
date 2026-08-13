import pytest
from src.schema import TaxBracket, FederalTaxRules, CapitalGainsTaxRules, TaxRulesConfig, MacroeconomicsConfig
from src.tax_engine import TaxCalculator


@pytest.fixture
def tax_config_with_inflation():
    return TaxRulesConfig(
        inflate_brackets=True,
        reference_year=2026,
        inflation_ref="general_inflation_rate",
        federal=FederalTaxRules(
            standard_deduction=30000,
            brackets=[
                TaxBracket(limit=20000, rate=0.10),
                TaxBracket(limit=100000, rate=0.20),
                TaxBracket(limit=float("inf"), rate=0.30),
            ],
        ),
        capital_gains=CapitalGainsTaxRules(
            brackets=[
                TaxBracket(limit=10000, rate=0.0),
                TaxBracket(limit=float("inf"), rate=0.15),
            ],
        ),
    )


@pytest.fixture
def macro_config():
    return MacroeconomicsConfig(general_inflation_rate=0.05)  # 5% annual inflation


def test_tax_bracket_inflation_in_reference_year(tax_config_with_inflation, macro_config):
    calc = TaxCalculator(tax_config_with_inflation)
    # In reference year (2026), standard deduction is $30,000
    # AGI = $50,000 -> Taxable = $20,000 -> Hits 1st bracket limit ($20,000 @ 10%) = $2,000
    assert calc.calculate_income_tax(50000.0, current_year=2026, macro=macro_config) == 2000.0


def test_tax_bracket_inflation_in_future_year(tax_config_with_inflation, macro_config):
    calc = TaxCalculator(tax_config_with_inflation)
    # In 2028 (2 years from 2026 @ 5% inflation factor = 1.05^2 = 1.1025):
    # Inflated standard deduction = $30,000 * 1.1025 = $33,075
    # Inflated 1st bracket limit = $20,000 * 1.1025 = $22,050
    #
    # Test AGI = $55,125 (exact $50,000 * 1.1025)
    # Taxable = $55,125 - $33,075 = $22,050 (exactly hits inflated 1st bracket limit!)
    # Tax owed = $22,050 * 0.10 = $2,205.0
    tax_owed = calc.calculate_income_tax(55125.0, current_year=2028, macro=macro_config)
    assert tax_owed == pytest.approx(2205.0)


def test_tax_bracket_inflation_disabled():
    config = TaxRulesConfig(
        inflate_brackets=False,
        reference_year=2026,
        federal=FederalTaxRules(
            standard_deduction=30000,
            brackets=[
                TaxBracket(limit=20000, rate=0.10),
                TaxBracket(limit=float("inf"), rate=0.20),
            ],
        ),
    )
    macro = MacroeconomicsConfig(general_inflation_rate=0.10)
    calc = TaxCalculator(config)

    # In 2030, with inflation disabled, standard deduction stays $30,000
    # AGI = $50,000 -> Taxable = $20,000 -> Tax = $2,000
    assert calc.calculate_income_tax(50000.0, current_year=2030, macro=macro) == 2000.0


def test_cap_gains_bracket_inflation_in_reference_year(tax_config_with_inflation, macro_config):
    calc = TaxCalculator(tax_config_with_inflation)
    # In the reference year (2026), the 0% cap-gains bracket tops out at $10,000
    assert calc.calculate_cap_gains_tax(10000.0, current_year=2026, macro=macro_config) == 0.0
    # Above the limit, gains are taxed at 15%
    assert calc.calculate_cap_gains_tax(15000.0, current_year=2026, macro=macro_config) == pytest.approx(750.0)


def test_cap_gains_bracket_inflation_in_future_year(tax_config_with_inflation, macro_config):
    calc = TaxCalculator(tax_config_with_inflation)
    # In 2028 (2 years from 2026 @ 5% -> factor 1.05^2 = 1.1025):
    # Inflated 0% cap-gains bracket limit = $10,000 * 1.1025 = $11,025
    assert calc.calculate_cap_gains_tax(11025.0, current_year=2028, macro=macro_config) == 0.0
    # Exactly at the inflated limit is still 0%; above it, gains are taxed at 15%
    assert calc.calculate_cap_gains_tax(21025.0, current_year=2028, macro=macro_config) == pytest.approx(1500.0)
