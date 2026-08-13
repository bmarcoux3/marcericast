"""Tests for YAML loader."""
import pytest
import yaml
from pathlib import Path
from src.loader import load_scenario_from_yaml
from src.schema import ScenarioConfig


class TestLoadScenarioFromYaml:
    """Tests for load_scenario_from_yaml function."""

    def test_load_from_dict(self):
        """Loading from dictionary should work."""
        data = {
            "version": "1.0",
            "meta": {
                "scenario_name": "Test",
                "start_year": 2026,
                "end_year": 2030,
            },
            "macroeconomics": {
                "general_inflation_rate": 0.02,
            },
            "tax_rules": {
                "federal": {
                    "standard_deduction": 30000,
                    "brackets": [
                        {"limit": 50000, "rate": 0.10},
                        {"limit": float("inf"), "rate": 0.20},
                    ],
                }
            },
            "accounts": [
                {"id": "checking", "name": "Checking", "type": "liquid", "balance": 10000.0}
            ],
            "waterfall_strategy": {
                "surplus_allocation": [{"account_id": "checking"}],
                "deficit_drawdown_order": [{"account_id": "checking"}],
            },
            "events": [],
        }
        config = load_scenario_from_yaml(data)
        assert isinstance(config, ScenarioConfig)
        assert config.meta.scenario_name == "Test"

    def test_load_from_yaml_string(self):
        """Loading from YAML string should work."""
        yaml_str = """
        version: "1.0"
        meta:
          scenario_name: "Test"
          start_year: 2026
          end_year: 2030
        macroeconomics:
          general_inflation_rate: 0.02
        tax_rules:
          federal:
            standard_deduction: 30000
            brackets:
              - limit: 50000
                rate: 0.10
              - limit: .inf
                rate: 0.20
        accounts:
          - id: "checking"
            name: "Checking"
            type: "liquid"
            balance: 10000.0
        waterfall_strategy:
          surplus_allocation:
            - account_id: "checking"
          deficit_drawdown_order:
            - account_id: "checking"
        events: []
        """
        config = load_scenario_from_yaml(yaml_str)
        assert isinstance(config, ScenarioConfig)
        assert config.meta.scenario_name == "Test"

    def test_load_from_file(self, tmp_path):
        """Loading from file path should work."""
        yaml_content = """
        version: "1.0"
        meta:
          scenario_name: "File Test"
          start_year: 2026
          end_year: 2030
        macroeconomics:
          general_inflation_rate: 0.02
        tax_rules:
          federal:
            standard_deduction: 30000
            brackets:
              - limit: .inf
                rate: 0.10
        accounts:
          - id: "checking"
            name: "Checking"
            type: "liquid"
            balance: 10000.0
        waterfall_strategy:
          surplus_allocation:
            - account_id: "checking"
          deficit_drawdown_order:
            - account_id: "checking"
        events: []
        """
        file_path = tmp_path / "test_scenario.yaml"
        file_path.write_text(yaml_content)

        config = load_scenario_from_yaml(file_path)
        assert isinstance(config, ScenarioConfig)
        assert config.meta.scenario_name == "File Test"

    def test_load_from_path_object(self, tmp_path):
        """Loading from pathlib.Path should work."""
        yaml_content = """
        version: "1.0"
        meta:
          scenario_name: "Path Test"
          start_year: 2026
          end_year: 2030
        macroeconomics:
          general_inflation_rate: 0.02
        tax_rules:
          federal:
            standard_deduction: 30000
            brackets:
              - limit: .inf
                rate: 0.10
        accounts:
          - id: "checking"
            name: "Checking"
            type: "liquid"
            balance: 10000.0
        waterfall_strategy:
          surplus_allocation:
            - account_id: "checking"
          deficit_drawdown_order:
            - account_id: "checking"
        events: []
        """
        file_path = tmp_path / "test_scenario.yaml"
        file_path.write_text(yaml_content)

        config = load_scenario_from_yaml(Path(file_path))
        assert isinstance(config, ScenarioConfig)
        assert config.meta.scenario_name == "Path Test"

    def test_strips_dot_prefixed_keys(self):
        """Dot-prefixed keys (YAML anchors/aliases) should be stripped."""
        data = {
            ".variables": {"salary": 100000},
            "version": "1.0",
            "meta": {
                "scenario_name": "Test",
                "start_year": 2026,
                "end_year": 2030,
            },
            "macroeconomics": {"general_inflation_rate": 0.02},
            "tax_rules": {"federal": {"standard_deduction": 30000, "brackets": [{"limit": 50000, "rate": 0.10}, {"limit": float("inf"), "rate": 0.20}]}},
            "accounts": [{"id": "checking", "name": "Checking", "type": "liquid", "balance": 10000.0}],
            "waterfall_strategy": {
                "surplus_allocation": [{"account_id": "checking"}],
                "deficit_drawdown_order": [{"account_id": "checking"}],
            },
            "events": [],
        }
        config = load_scenario_from_yaml(data)
        assert isinstance(config, ScenarioConfig)

    def test_invalid_source_type_raises(self):
        """Invalid source type should raise TypeError."""
        with pytest.raises(TypeError) as excinfo:
            load_scenario_from_yaml(12345)
        assert "Expected file path, raw YAML string, or dict" in str(excinfo.value)

    def test_nonexistent_file_raises(self):
        """Nonexistent file path is treated as YAML string and fails to parse."""
        with pytest.raises(ValueError) as excinfo:
            load_scenario_from_yaml("/nonexistent/path.yaml")
        assert "YAML content did not parse to a dict" in str(excinfo.value)

    def test_invalid_yaml_raises(self):
        """Invalid YAML content should raise error."""
        invalid_yaml = """
        version: "1.0"
        meta:
          scenario_name: "Test"
          start_year: 2026
          end_year: 2030
        macroeconomics:
          general_inflation_rate: 0.02
        tax_rules:
          federal:
            standard_deduction: 30000
            brackets:
              - limit: .inf
                rate: 0.10
        accounts:
          - id: "checking"
            name: "Checking"
            type: "liquid"
            balance: 10000.0
        waterfall_strategy:
          surplus_allocation:
            - account_id: "checking"
          deficit_drawdown_order:
            - account_id: "checking"
        events: []
        invalid_key: invalid: yaml: [
        """
        with pytest.raises(Exception):
            load_scenario_from_yaml(invalid_yaml)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])