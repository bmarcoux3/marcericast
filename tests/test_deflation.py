"""Tests for today's dollars (deflation) calculations and API flag."""
import pytest
import pandas as pd
from fastapi.testclient import TestClient
from api import app
from src.deflation import deflation_factor, deflate_dataframe

client = TestClient(app)


class TestDeflationFactor:
    """Tests for deflation_factor function."""

    def test_base_year_identity(self):
        """Base year always has factor 1.0 regardless of inflation rate."""
        # (1.025)^(2026-2026) = (1.025)^0 = 1.0
        assert deflation_factor(2026, 2026, 0.025) == 1.0
        # Same base-year exponent: (1.0)^0 = 1.0
        assert deflation_factor(2026, 2026, 0.0) == 1.0

    def test_future_year_discounted(self):
        """Future years get discounted below 1.0."""
        # $100 in 2028 is worth 100 / (1.05)^2 = 90.70 in 2026 dollars
        assert deflation_factor(2026, 2028, 0.05) == pytest.approx(1.0 / (1.05 ** 2))
        # $100 in 2030 is worth 100 / (1.025)^4 in 2026 dollars
        assert deflation_factor(2026, 2030, 0.025) == pytest.approx(1.0 / (1.025 ** 4))

    def test_zero_inflation_identity(self):
        """Zero inflation rate gives factor 1.0 everywhere."""
        # (1.0)^(2026-2050) = 1.0 (any exponent of 1.0 is 1.0)
        assert deflation_factor(2026, 2050, 0.0) == 1.0
        # Same: (1.0)^(2026-2040) = 1.0
        assert deflation_factor(2026, 2040, 0.0) == 1.0


class TestDeflateDataframe:
    """Tests for deflate_dataframe function."""

    def _make_df(self):
        df = pd.DataFrame(
            {
                "Net Worth": [100.0, 110.0, 121.0],
                "Gross Taxable Income": [50.0, 60.0, 72.0],
            },
            index=[2026, 2027, 2028],
        )
        df.index.name = "Year"
        return df

    def test_noop_when_zero_inflation(self):
        """Zero inflation returns an equal copy."""
        df = self._make_df()
        result = deflate_dataframe(df, 2026, 0.0)
        pd.testing.assert_frame_equal(result, df)
        assert result is not df  # Returns a copy

    def test_scales_by_year_factor(self):
        """Each year's values are scaled by (1+r)^(base_year - year)."""
        df = self._make_df()
        result = deflate_dataframe(df, 2026, 0.05)
        expected = pd.DataFrame(
            {
                "Net Worth": [100.0, 110.0 / 1.05, 121.0 / (1.05 ** 2)],
                "Gross Taxable Income": [50.0, 60.0 / 1.05, 72.0 / (1.05 ** 2)],
            },
            index=[2026, 2027, 2028],
        )
        expected.index.name = "Year"
        pd.testing.assert_frame_equal(result, expected)

    def test_original_unchanged(self):
        """The input dataframe is not mutated."""
        df = self._make_df()
        df_copy = df.copy()
        deflate_dataframe(df, 2026, 0.05)
        pd.testing.assert_frame_equal(df, df_copy)

    def test_non_numeric_columns_untouched(self):
        """Non-numeric columns pass through unchanged."""
        df = self._make_df()
        df["label"] = ["a", "b", "c"]
        result = deflate_dataframe(df, 2026, 0.05)
        assert list(result["label"]) == ["a", "b", "c"]

    def test_deflate_fewer_years(self):
        """Works when df covers a subset starting after base year."""
        df = pd.DataFrame({"Net Worth": [200.0]}, index=[2028])
        df.index.name = "Year"
        result = deflate_dataframe(df, 2026, 0.025)
        assert result["Net Worth"].iloc[0] == pytest.approx(200.0 / (1.025 ** 2))


class TestRunEndpointRealDollars:
    """Tests for the real_dollars flag on the run endpoints."""

    def _nominal_and_deflated(self):
        nominal = client.get("/api/scenarios/generic-family/run").json()
        deflated = client.get("/api/scenarios/generic-family/run?real_dollars=true").json()
        return nominal, deflated

    def test_default_is_nominal(self):
        """Without the flag, the run is nominal (deflated flag false)."""
        response = client.get("/api/scenarios/generic-family/run")
        data = response.json()
        assert data["success"] is True
        assert data["deflated"] is False

    def test_flag_returned_when_enabled(self):
        """Response reports deflated=true when requested."""
        response = client.get("/api/scenarios/generic-family/run?real_dollars=true")
        data = response.json()
        assert data["success"] is True
        assert data["deflated"] is True

    def test_first_year_identical(self):
        """First year values are unchanged (factor 1.0)."""
        nominal, deflated = self._nominal_and_deflated()
        start_year = nominal["data"][0]["Year"]
        assert deflated["data"][0]["Year"] == start_year
        for col in ("Net Worth", "Total Assets", "Gross Taxable Income"):
            assert deflated["data"][0][col] == pytest.approx(nominal["data"][0][col])

    def test_future_years_discounted_by_inflation(self):
        """Later year values equal nominal * (1.025)^(2026 - year)."""
        nominal, deflated = self._nominal_and_deflated()
        last_nominal = nominal["data"][-1]
        last_deflated = deflated["data"][-1]
        year = last_nominal["Year"]
        factor = (1.025 ** (2026 - year))
        assert deflated["data"][-1]["Year"] == year
        assert last_deflated["Net Worth"] == pytest.approx(last_nominal["Net Worth"] * factor)
        assert last_deflated["Total Assets"] == pytest.approx(last_nominal["Total Assets"] * factor)

    def test_deflated_net_worth_lower_in_future(self):
        """For an inflation-positive scenario, deflated final net worth is lower."""
        nominal, deflated = self._nominal_and_deflated()
        assert abs(deflated["data"][-1]["Net Worth"]) < abs(nominal["data"][-1]["Net Worth"])

    def test_summary_deflated(self):
        """Summary totals are computed from deflated values."""
        nominal, deflated = self._nominal_and_deflated()
        assert deflated["summary"]["final_net_worth"] == pytest.approx(
            nominal["summary"]["final_net_worth"] * (1.025 ** (2026 - nominal["summary"]["end_year"]))
        )

    def test_post_with_real_dollars(self):
        """POST request body accepts real_dollars=true."""
        response = client.post(
            "/api/scenarios/generic-family/run",
            json={
                "scenario_name": "generic-family",
                "real_dollars": True,
            },
        )
        data = response.json()
        assert data["success"] is True
        assert data["deflated"] is True
        assert data["data"][-1]["Net Worth"] < 0 or abs(data["data"][-1]["Net Worth"]) < abs(
            client.post("/api/scenarios/generic-family/run", json={"scenario_name": "generic-family"}).json()["data"][-1]["Net Worth"]
        )

    def test_post_default_nominal(self):
        """POST without real_dollars stays nominal."""
        response = client.post(
            "/api/scenarios/generic-family/run",
            json={"scenario_name": "generic-family"},
        )
        assert response.json()["deflated"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
