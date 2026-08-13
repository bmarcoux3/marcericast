"""
Integration tests for the FastAPI backend API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)


class TestScenariosEndpoint:
    """Tests for /api/scenarios endpoint."""

    def test_list_scenarios(self):
        """Test listing all scenarios."""
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 5  # At least the 5 built-in scenarios

        # Check structure of each scenario
        for scenario in data:
            assert "name" in scenario
            assert "display_name" in scenario
            assert "start_year" in scenario
            assert "end_year" in scenario
            assert "tax_status" in scenario

    def test_scenario_names(self):
        """Test that expected scenarios are present."""
        response = client.get("/api/scenarios")
        data = response.json()
        names = [s["name"] for s in data]
        assert "generic-family" in names
        assert "baseline" in names
        assert "comprehensive-baseline" in names
        assert "comprehensive-baseline-custom" in names
        assert "baseline_test" in names


class TestParametersEndpoint:
    """Tests for /api/scenarios/{name}/parameters endpoint."""

    def test_get_parameters_generic_family(self):
        """Test getting parameters for generic-family scenario."""
        response = client.get("/api/scenarios/generic-family/parameters")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 100  # Many parameters

        # Check structure of each parameter
        for param in data:
            assert "path" in param
            assert "current_value" in param
            assert "default_value" in param
            assert "description" in param
            assert "parameter_type" in param

    def test_get_parameters_baseline(self):
        """Test getting parameters for baseline scenario."""
        response = client.get("/api/scenarios/baseline/parameters")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 20

    def test_get_parameters_not_found(self):
        """Test 404 for non-existent scenario."""
        response = client.get("/api/scenarios/nonexistent/parameters")
        assert response.status_code == 404

    def test_parameter_types(self):
        """Test that different parameter types are present."""
        response = client.get("/api/scenarios/generic-family/parameters")
        data = response.json()
        types = {p["parameter_type"] for p in data}
        assert "float" in types
        assert "int" in types
        assert "str" in types

    def test_parameter_min_max(self):
        """Test that numeric parameters have min/max values."""
        response = client.get("/api/scenarios/generic-family/parameters")
        data = response.json()
        for param in data:
            if param["parameter_type"] in ("float", "int"):
                # Not all have min/max but many should
                if param["path"].startswith("macroeconomics."):
                    assert param.get("min_value") is not None
                    assert param.get("max_value") is not None

    def test_opted_in_variables_exposed_with_control(self):
        """Only .variable_meta variables are exposed, each with a control."""
        response = client.get("/api/scenarios/generic-family/parameters")
        data = response.json()
        variables = [p for p in data if p["path"].startswith("variables.")]
        paths = {p["path"] for p in variables}
        # Opt-in set from the fixture generic-family.yaml .variable_meta
        assert paths == {
            "variables.end_year",
            "variables.retirement",
            "variables.assisted_living_start",
            "variables.kid_four_exists",
            "variables.social_security_enabled",
        }
        # Toggles are bools with a control hint
        toggles = [p for p in variables if p["control"] == "toggle"]
        assert {p["path"] for p in toggles} == {
            "variables.kid_four_exists",
            "variables.social_security_enabled",
        }
        assert all(p["parameter_type"] == "bool" for p in toggles)
        # Sliders carry min/max/step and a label
        sliders = [p for p in variables if p["control"] == "slider"]
        assert len(sliders) == 3
        assert all(p.get("min_value") is not None and p.get("max_value") is not None for p in sliders)
        assert all(p.get("label") for p in sliders)


class TestRunEndpoint:
    """Tests for /api/scenarios/{name}/run endpoint."""

    def test_run_generic_family_get(self):
        """Test running generic-family scenario via GET."""
        response = client.get("/api/scenarios/generic-family/run")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] is not None
        assert data["columns"] is not None
        assert data["summary"] is not None
        assert len(data["data"]) > 50  # 54 years

    def test_run_baseline_get(self):
        """Test running baseline scenario via GET."""
        response = client.get("/api/scenarios/baseline/run")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) > 30

    def test_run_with_start_year(self):
        """Test running with custom start year."""
        response = client.get("/api/scenarios/generic-family/run?start_year=2028")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # First data row is the requested start year
        assert data["data"][0]["Year"] == 2028

    def test_run_with_end_year(self):
        """Test running with custom end year."""
        response = client.get("/api/scenarios/generic-family/run?end_year=2050")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Last data row is the requested end year
        assert data["data"][-1]["Year"] == 2050

    def test_run_with_param_override(self):
        """Test running with parameter override."""
        response = client.get(
            "/api/scenarios/generic-family/run?param.macroeconomics.general_inflation_rate=0.05"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_run_with_multiple_param_overrides(self):
        """Test running with multiple parameter overrides."""
        response = client.get(
            "/api/scenarios/generic-family/run"
            "?param.macroeconomics.general_inflation_rate=0.05"
            "&param.macroeconomics.growth_rates.equities=0.08"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_run_not_found(self):
        """Test 404 for non-existent scenario."""
        response = client.get("/api/scenarios/nonexistent/run")
        assert response.status_code == 404

    def test_run_post(self):
        """Test running scenario via POST with JSON body."""
        response = client.post(
            "/api/scenarios/generic-family/run",
            json={
                "scenario_name": "generic-family",
                "parameter_overrides": [
                    {"path": "macroeconomics.general_inflation_rate", "value": 0.04}
                ],
                "start_year": 2026,
                "end_year": 2050,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # POST body start_year=2026 / end_year=2050 reflected in output rows
        assert data["data"][0]["Year"] == 2026
        assert data["data"][-1]["Year"] == 2050

    def test_variable_toggle_override_changes_result(self):
        """A .variable_meta toggle override must change simulation output."""
        base = client.post(
            "/api/scenarios/generic-family/run",
            json={"scenario_name": "generic-family"},
        ).json()
        toggled = client.post(
            "/api/scenarios/generic-family/run",
            json={
                "scenario_name": "generic-family",
                "parameter_overrides": [
                    {"path": "variables.kid_four_exists", "value": 0},
                    {"path": "variables.social_security_enabled", "value": 1},
                ],
            },
        ).json()
        assert base["success"] is True and toggled["success"] is True
        assert base["summary"]["final_net_worth"] != toggled["summary"]["final_net_worth"]

    def test_unknown_variable_override_errors(self):
        """Overriding an undeclared variable should fail cleanly."""
        response = client.post(
            "/api/scenarios/generic-family/run",
            json={
                "scenario_name": "generic-family",
                "parameter_overrides": [
                    {"path": "variables.not_a_real_variable", "value": 1}
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert "Unknown variable" in response.json()["error"]


class TestExportEndpoint:
    """Tests for /api/export/{name} endpoint."""

    def test_export_generic_family(self):
        """Test exporting generic-family scenario as CSV."""
        response = client.get("/api/export/generic-family")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert "generic-family-output.csv" in response.headers["content-disposition"]

    def test_export_baseline(self):
        """Test exporting baseline scenario as CSV."""
        response = client.get("/api/export/baseline")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"

    def test_export_not_found(self):
        """Test 404 for non-existent scenario."""
        response = client.get("/api/export/nonexistent")
        assert response.status_code == 404


class TestFrontendServing:
    """Tests for frontend static file serving."""

    def test_root_serves_html(self):
        """Test that root serves index.html."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Personal Cashflow Dashboard" in response.text

    def test_static_css(self):
        """Test that CSS is served."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_static_js(self):
        """Test that JavaScript is served."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]


class TestDataQuality:
    """Tests for data quality of simulation results."""

    def test_net_worth_final_positive(self):
        """Test that final net worth is positive for generic-family."""
        response = client.get("/api/scenarios/generic-family/run")
        data = response.json()
        final_net_worth = data["data"][-1]["Net Worth"]
        assert final_net_worth > 0

    def test_columns_exist(self):
        """Test that expected columns exist."""
        response = client.get("/api/scenarios/generic-family/run")
        data = response.json()
        columns = data["columns"]
        assert "Year" in columns
        assert "Net Worth" in columns
        assert "Total Assets" in columns
        assert "Total Liabilities" in columns
        assert "Gross Taxable Income" in columns
        assert "Federal Tax" in columns

    def test_tag_columns_exist(self):
        """Test that tag aggregate columns exist."""
        response = client.get("/api/scenarios/generic-family/run")
        data = response.json()
        columns = data["columns"]
        tag_columns = [c for c in columns if c.startswith("Tag: ")]
        assert len(tag_columns) >= 10  # At least 10 tag categories

    def test_summary_fields(self):
        """Test that summary has expected fields."""
        response = client.get("/api/scenarios/generic-family/run")
        data = response.json()
        summary = data["summary"]
        assert "years" in summary
        assert "start_year" in summary
        assert "end_year" in summary
        assert "final_net_worth" in summary
        assert "peak_net_worth" in summary
        assert "total_income" in summary
        assert "total_tax" in summary
        assert "total_cash_flow" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])