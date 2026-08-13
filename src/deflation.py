"""Deflation utilities for expressing future dollars in today's purchasing power."""
import pandas as pd


def deflation_factor(base_year: int, current_year: int, inflation_rate: float) -> float:
    """
    Return the multiplier that converts a dollar amount in current_year to
    base_year (today's) dollars given an annual inflation rate.

    A future dollar is worth less in today's dollars, so factors are below 1.0
    for years after base_year and above 1.0 for years before it.
    """
    if inflation_rate == 0.0:
        return 1.0
    return (1.0 + inflation_rate) ** (base_year - current_year)


def deflate_dataframe(df: pd.DataFrame, base_year: int, inflation_rate: float) -> pd.DataFrame:
    """
    Return a copy of df with every monetary column scaled into base_year
    (today's) dollars. The index is expected to be the simulation year.

    No-op when inflation_rate is 0.0. Non-numeric columns pass through unchanged.
    """
    if inflation_rate == 0.0:
        return df.copy()

    factors = {
        year: deflation_factor(base_year, year, inflation_rate)
        for year in df.index
    }
    # Build all columns at once so the frame stays in a single block instead of
    # becoming fragmented (which triggers a pandas PerformanceWarning downstream).
    columns = {
        col: [
            value * factors[year] if isinstance(value, (int, float)) else value
            for year, value in zip(df.index, df[col])
        ]
        for col in df.columns
    }
    return pd.DataFrame(columns, index=df.index)
