"""Tests for generic YAML-variable overrides and opt-in tunable parameters."""
import pytest

from src.loader import load_scenario_from_yaml
from api import apply_parameter_overrides, get_tunable_parameters, ScenarioParameter


def _minimal_yaml_with_aliases():
    """Build a YAML string where variables are declared once with anchors and
    referenced via aliases in events (as real scenarios author them)."""
    return """
.version: "1.0"
.variables:
  - &social_security_enabled 1
  - &retirement 2061
.variable_meta:
  social_security_enabled:
    label: "Social Security Enabled"
    control: "toggle"
  retirement:
    label: "Retirement Year"
    control: "slider"
    min: 2040
    max: 2075
    step: 1
meta:
  scenario_name: "Minimal"
  start_year: 2026
  end_year: 2080
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
events:
  - id: "primary_salary"
    name: "Primary Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: *retirement
    base_amount: 120000
  - id: "social_security_primary"
    name: "Primary SS"
    type: "cash_stream"
    category: "income"
    start_year: *retirement
    end_year: 2080
    base_amount: 42000
    step_adjustments:
      2061: *social_security_enabled
"""


class TestVariableMetaLoading:
    """The loader returns .variable_meta alongside .variables."""

    def test_variable_meta_preserved_in_variables(self):
        config, variables = load_scenario_from_yaml(_minimal_yaml_with_aliases(), return_variables=True)
        assert ".variable_meta" in variables
        assert variables[".variable_meta"]["social_security_enabled"]["control"] == "toggle"
        assert "retirement" in variables[".variable_meta"]

    def test_variable_meta_stripped_from_config(self):
        config, variables = load_scenario_from_yaml(_minimal_yaml_with_aliases(), return_variables=True)
        assert not hasattr(config, "variable_meta")

    def test_alias_refs_use_event_ids_not_positions(self):
        config, variables = load_scenario_from_yaml(_minimal_yaml_with_aliases(), return_variables=True)
        refs = variables[".alias_refs"]
        assert "events.social_security_primary.step_adjustments.2061" in refs.get("social_security_enabled", [])
        assert "events.primary_salary.end_year" in refs.get("retirement", [])


class TestGenericOverrides:
    """Overriding any anchored variable updates every aliased field."""

    def _load(self):
        return load_scenario_from_yaml(_minimal_yaml_with_aliases(), return_variables=True)

    def test_toggle_updates_step_adjustments(self):
        config, variables = self._load()
        new_config, new_vars = apply_parameter_overrides(
            config,
            [ScenarioParameter(path="variables.social_security_enabled", value=0)],
            variables,
        )
        event = next(e for e in new_config.events if e.id == "social_security_primary")
        assert event.step_adjustments[2061] == 0.0

    def test_retirement_updates_event_end_year(self):
        config, variables = self._load()
        new_config, new_vars = apply_parameter_overrides(
            config,
            [ScenarioParameter(path="variables.retirement", value=2050)],
            variables,
        )
        event = next(e for e in new_config.events if e.id == "primary_salary")
        assert event.end_year == 2050
        assert new_vars[".variables"][new_vars[".variable_names"].index("retirement")] == 2050

    def test_unknown_variable_override_raises(self):
        config, variables = self._load()
        with pytest.raises(ValueError):
            apply_parameter_overrides(
                config,
                [ScenarioParameter(path="variables.nonexistent_var", value=1)],
                variables,
            )


class TestTunableParameters:
    """Only variables declared in .variable_meta are exposed."""

    def _params(self):
        config, variables = load_scenario_from_yaml(_minimal_yaml_with_aliases(), return_variables=True)
        return get_tunable_parameters(config, variables)

    def test_only_opted_in_variables_exposed(self):
        params = self._params()
        variable_paths = [p.path for p in params if p.path.startswith("variables.")]
        assert set(variable_paths) == {"variables.social_security_enabled", "variables.retirement"}

    def test_toggle_parameter_shape(self):
        params = self._params()
        toggle = next(p for p in params if p.path == "variables.social_security_enabled")
        assert toggle.parameter_type == "bool"
        assert toggle.control == "toggle"
        assert toggle.label == "Social Security Enabled"
        assert toggle.category == "life_decisions"

    def test_slider_parameter_shape(self):
        params = self._params()
        slider = next(p for p in params if p.path == "variables.retirement")
        assert slider.parameter_type == "int"
        assert slider.control == "slider"
        assert slider.label == "Retirement Year"
        assert slider.min_value == 2040
        assert slider.max_value == 2075

    def test_internal_step_adjustments_not_duplicated(self):
        params = self._params()
        # Only the SS start event should carry internal per-year step adjustments
        internal = [p for p in params if "step_adjustments." in p.path]
        assert len(internal) == 1
        assert internal[0].path == "events.social_security_primary.step_adjustments.2061"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
