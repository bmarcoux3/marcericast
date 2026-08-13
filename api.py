"""
FastAPI backend for the Personal Cashflow Visualization Dashboard.

Exposes the simulation engine via REST API for interactive parameter exploration.
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import pandas as pd
import json
import yaml
from pathlib import Path
import os
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner
from src.schema import ScenarioConfig
from src.deflation import deflate_dataframe


app = FastAPI(
    title="Personal Cashflow Simulation API",
    description="API for running financial simulations and exploring scenarios",
    version="1.0.0",
)

# Enable CORS for local development. The dashboard is served from the same
# origin, so only allow explicit local origins (never "*" with credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/favicon.ico")
async def serve_favicon():
    """Serve the favicon."""
    return FileResponse("static/favicon.ico")

@app.get("/")
async def serve_frontend():
    """Serve the frontend application."""
    return FileResponse("static/index.html")


# --- Request/Response Models ---

class ScenarioParameter(BaseModel):
    """A single parameter that can be modified in a scenario."""
    path: str = Field(..., description="Dot-notation path to the parameter (e.g., 'macroeconomics.growth_rates.equities')")
    value: Any = Field(..., description="New value for the parameter")
    description: Optional[str] = Field(None, description="Human-readable description of the parameter")


class RunScenarioRequest(BaseModel):
    """Request to run a scenario with optional parameter overrides."""
    scenario_name: str = Field(..., description="Name of the scenario file (without .yaml)")
    parameter_overrides: List[ScenarioParameter] = Field(default_factory=list, description="Parameters to override")
    start_year: Optional[int] = Field(None, description="Override start year")
    end_year: Optional[int] = Field(None, description="Override end year")
    real_dollars: bool = Field(False, description="Deflate all future dollars to today's (start year) dollars")


class ScenarioInfo(BaseModel):
    """Information about an available scenario."""
    name: str
    display_name: str
    start_year: int
    end_year: int
    tax_status: str


class SimulationResponse(BaseModel):
    """Response containing simulation results."""
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    deflated: bool = Field(False, description="Whether values are expressed in today's (start year) dollars")


class ParameterInfo(BaseModel):
    """Information about a tunable parameter."""
    path: str
    current_value: Any
    default_value: Any
    description: str
    parameter_type: str  # "float", "int", "bool", "str"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    tags: Optional[List[str]] = None  # Event tags for categorization
    category: Optional[str] = None  # Category for grouping (e.g., "life_decisions", "macroeconomics")
    label: Optional[str] = None  # Friendly label for the UI (from .variable_meta)
    control: Optional[str] = None  # UI control hint (e.g., "toggle", "slider") from .variable_meta


# Variable override mechanics are generic: the loader recovers which scenario
# fields each YAML variable controls (variables[".alias_refs"]) by walking the
# YAML alias graph, so no per-scenario mappings are hardcoded here.


# --- Helper Functions ---

def get_scenarios_dir() -> Path:
    """Resolve the scenarios directory.

    Defaults to the project's ``scenarios/`` folder. Override via the
    SCENARIOS_DIR environment variable so tests (and other consumers) can point
    the API at their own set of scenario files.
    """
    override = os.environ.get("SCENARIOS_DIR")
    if override:
        return Path(override)
    return Path(__file__).parent / "scenarios"


def get_available_scenarios() -> List[ScenarioInfo]:
    """Get list of available scenario files."""
    scenarios_dir = get_scenarios_dir()
    scenarios = []
    for yaml_file in scenarios_dir.glob("*.yaml"):
        try:
            config, _ = load_scenario_from_yaml(yaml_file, return_variables=True)
            scenarios.append(ScenarioInfo(
                name=yaml_file.stem,
                display_name=config.meta.scenario_name,
                start_year=config.meta.start_year,
                end_year=config.meta.end_year,
                tax_status=config.meta.tax_status,
            ))
        except Exception as e:
            print(f"Error loading {yaml_file}: {e}")
    return scenarios


def apply_parameter_overrides(config: ScenarioConfig, overrides: List[ScenarioParameter], variables: Dict[str, Any] = None) -> tuple:
    """Apply parameter overrides to a scenario config and variables."""
    # Convert config to dict for easier manipulation
    config_dict = config.model_dump()

    # Handle variables overrides
    if variables is None:
        variables = {}
    variables_dict = dict(variables)

    # Map variable names to .variables list positions. The loader recovers the
    # anchor names (e.g. &social_security_enabled) into .variable_names, so no
    # positional assumptions are made here.
    var_names = variables_dict.get(".variable_names", [])
    var_name_to_index = {name: idx for idx, name in enumerate(var_names) if name is not None}

    # Map variable names to the fields they control (from the YAML alias graph).
    alias_refs = variables_dict.get(".alias_refs", {})


    def _set_key(target: Dict[str, Any], key: str, value: Any) -> None:
        """Set key on a dict, tolerating int-coerced keys (e.g. step year '2061')."""
        if not isinstance(target, dict):
            return
        if key in target:
            target[key] = value
        elif key.isdigit() and int(key) in target:
            target[int(key)] = value
        else:
            target[key] = value


    def set_config_path(config_dict: Dict[str, Any], path: str, value: Any) -> None:
        """Set a value at a dot path, resolving events (a list) by event id."""
        parts = path.split(".")
        if parts[0] == "events" and len(parts) >= 3:
            event_id = parts[1]
            for event in config_dict.get("events", []):
                if event.get("id") == event_id:
                    current: Any = event
                    for part in parts[2:-1]:
                        if not isinstance(current, dict):
                            return
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                    _set_key(current, parts[-1], value)
                    break
            return
        current: Any = config_dict
        for part in parts[:-1]:
            if part not in current:
                raise ValueError(f"Invalid path: {path} (missing {part})")
            current = current[part]
        _set_key(current, parts[-1], value)

    for override in overrides:
        path_parts = override.path.split(".")

        # Handle variables path
        if path_parts[0] == "variables":
            if len(path_parts) >= 2:
                var_name = path_parts[1]
                idx = var_name_to_index.get(var_name)
                if idx is None:
                    raise ValueError(f"Unknown variable: {var_name} (not declared in scenario .variables)")
                # Ensure .variables list exists and has enough elements
                if ".variables" not in variables_dict:
                    variables_dict[".variables"] = variables.get(".variables", []).copy()
                vars_list = variables_dict[".variables"]
                if idx < len(vars_list):
                    vars_list[idx] = override.value

                # Update every field this variable controls (step_adjustments,
                # base_amounts, years, etc.) via the alias-reference graph.
                for ref_path in alias_refs.get(var_name, []):
                    set_config_path(config_dict, ref_path, override.value)
            continue

        # Handle event paths (events are a list, not a dict)
        if path_parts[0] == "events":
            set_config_path(config_dict, override.path, override.value)
            continue

        # Handle config path
        set_config_path(config_dict, override.path, override.value)

    # Re-validate and return new config with updated variables
    new_config = ScenarioConfig.model_validate(config_dict)
    return new_config, variables_dict


def run_simulation(config: ScenarioConfig) -> pd.DataFrame:
    """Run the simulation and return the dataframe."""
    runner = SimulationRunner(config)
    return runner.run()


def deflate_results(df: pd.DataFrame, config: ScenarioConfig) -> pd.DataFrame:
    """Deflate a simulation dataframe to today's (start year) dollars."""
    return deflate_dataframe(
        df,
        base_year=config.meta.start_year,
        inflation_rate=config.macroeconomics.general_inflation_rate,
    )


def dataframe_to_response(df: pd.DataFrame) -> Dict[str, Any]:
    """Convert dataframe to JSON-serializable response."""
    # Convert to records - include the index (Year) as a column
    records = df.reset_index().to_dict(orient="records")

    # Include the index name in columns list
    columns = [df.index.name] + df.columns.tolist() if df.index.name else df.columns.tolist()

    # Calculate summary statistics
    summary = {
        "years": len(df),
        "start_year": int(df.index.min()),
        "end_year": int(df.index.max()),
        "final_net_worth": float(df["Net Worth"].iloc[-1]) if "Net Worth" in df.columns else None,
        "peak_net_worth": float(df["Net Worth"].max()) if "Net Worth" in df.columns else None,
        "min_net_worth": float(df["Net Worth"].min()) if "Net Worth" in df.columns else None,
    }

    # Add key metrics summary
    if "Gross Taxable Income" in df.columns:
        summary["total_income"] = float(df["Gross Taxable Income"].sum())
    if "Federal Tax" in df.columns:
        summary["total_tax"] = float(df["Federal Tax"].sum())
    if "Net Cash Flow" in df.columns:
        summary["total_cash_flow"] = float(df["Net Cash Flow"].sum())

    # Total expenses across all spending categories (including taxes and
    # investments). Tag columns are negative for expenses and positive for
    # income, so only the negative contributions count as spending.
    tag_columns = [col for col in df.columns if col.startswith("Tag: ")]
    if tag_columns:
        total_expenses = float(df[tag_columns].clip(upper=0).sum().sum())
        summary["total_expenses"] = -total_expenses

    return {
        "data": records,
        "columns": columns,
        "summary": summary,
    }


def get_tunable_parameters(config: ScenarioConfig, variables: Dict[str, Any] = None) -> List[ParameterInfo]:
    """Extract tunable parameters from the scenario config."""
    parameters = []

    # Variables from YAML (like kid_four_exists) are exposed to the UI only when
    # they are declared in the optional .variable_meta block (opt-in "life
    # decision" controls). The loader recovers anchor names into
    # .variable_names (in order), so each .variables entry can be addressed by
    # its declared name.
    if variables:
        variable_names = variables.get(".variable_names", [])
        variables_list = variables.get(".variables", [])
        variable_meta = variables.get(".variable_meta", {})

        name_to_index = {name: i for i, name in enumerate(variable_names) if name is not None}

        for param_name, meta in variable_meta.items():
            idx = name_to_index.get(param_name)
            if idx is None or idx >= len(variables_list):
                continue
            value = variables_list[idx]

            if isinstance(value, bool):
                base_type = "bool"
            elif isinstance(value, int):
                base_type = "int"
            elif isinstance(value, float):
                base_type = "float"
            else:
                base_type = "str"

            control = meta.get("control")
            label = meta.get("label")
            description = meta.get("description")

            if control == "toggle":
                param_type = "bool"
                category = "life_decisions"
                min_value = 0
                max_value = 1
                step = 1
            elif control == "slider":
                param_type = base_type
                category = "life_decisions"
                min_value = meta.get("min")
                max_value = meta.get("max")
                step = meta.get("step")
            else:
                param_type = base_type
                category = meta.get("category", "life_decisions")
                min_value = meta.get("min")
                max_value = meta.get("max")
                step = meta.get("step", 1 if base_type == "int" else 0.001)

            parameters.append(ParameterInfo(
                path=f"variables.{param_name}",
                current_value=value,
                default_value=value,
                description=description or label or f"YAML variable: {param_name}",
                label=label,
                parameter_type=param_type,
                min_value=min_value,
                max_value=max_value,
                step=step,
                category=category,
                control=control,
            ))

    # Macroeconomics parameters
    if config.macroeconomics.general_inflation_rate is not None:
        parameters.append(ParameterInfo(
            path="macroeconomics.general_inflation_rate",
            current_value=config.macroeconomics.general_inflation_rate,
            default_value=config.macroeconomics.general_inflation_rate,
            description="General inflation rate (annual)",
            parameter_type="float",
            min_value=0.0,
            max_value=0.15,
            step=0.001,
        ))

    for key, value in config.macroeconomics.growth_rates.items():
        parameters.append(ParameterInfo(
            path=f"macroeconomics.growth_rates.{key}",
            current_value=value,
            default_value=value,
            description=f"Growth rate for {key}",
            parameter_type="float",
            min_value=0.0,
            max_value=0.20,
            step=0.001,
        ))

    # Derisking parameters
    for key, derisk in config.macroeconomics.derisking_schedule.items():
        if isinstance(derisk, dict):
            for param_key, param_value in derisk.items():
                if isinstance(param_value, (int, float)):
                    parameters.append(ParameterInfo(
                        path=f"macroeconomics.derisking_schedule.{key}.{param_key}",
                        current_value=param_value,
                        default_value=param_value,
                        description=f"Derisking {param_key} for {key}",
                        parameter_type="int" if isinstance(param_value, int) else "float",
                        min_value=0 if isinstance(param_value, int) else 0.0,
                        max_value=100 if isinstance(param_value, int) else 1.0,
                        step=1 if isinstance(param_value, int) else 0.1,
                    ))

    # Tax rules
    if config.tax_rules.federal.standard_deduction:
        parameters.append(ParameterInfo(
            path="tax_rules.federal.standard_deduction",
            current_value=config.tax_rules.federal.standard_deduction,
            default_value=config.tax_rules.federal.standard_deduction,
            description="Federal standard deduction",
            parameter_type="float",
            min_value=0,
            max_value=100000,
            step=100,
        ))

    # Meta parameters
    if config.meta.birth_year:
        parameters.append(ParameterInfo(
            path="meta.birth_year",
            current_value=config.meta.birth_year,
            default_value=config.meta.birth_year,
            description="Birth year (used for age-based calculations)",
            parameter_type="int",
            min_value=1940,
            max_value=2010,
            step=1,
        ))

    # Account parameters
    for account in config.accounts:
        if account.balance is not None:
            parameters.append(ParameterInfo(
                path=f"accounts.{account.id}.balance",
                current_value=account.balance,
                default_value=account.balance,
                description=f"Initial balance for {account.name}",
                parameter_type="float",
                min_value=0,
                max_value=10000000,
                step=1000,
            ))
        if account.growth_rate_ref:
            parameters.append(ParameterInfo(
                path=f"accounts.{account.id}.growth_rate_ref",
                current_value=account.growth_rate_ref,
                default_value=account.growth_rate_ref,
                description=f"Growth rate reference for {account.name}",
                parameter_type="str",
            ))
        if account.max_target_balance:
            parameters.append(ParameterInfo(
                path=f"accounts.{account.id}.max_target_balance",
                current_value=account.max_target_balance,
                default_value=account.max_target_balance,
                description=f"Max target balance for {account.name}",
                parameter_type="float",
                min_value=0,
                max_value=10000000,
                step=1000,
            ))

    # Waterfall strategy
    for item in config.waterfall_strategy.surplus_allocation:
        if item.max_annual_contribution != float("inf"):
            parameters.append(ParameterInfo(
                path=f"waterfall_strategy.surplus_allocation.{item.account_id}.max_annual_contribution",
                current_value=item.max_annual_contribution,
                default_value=item.max_annual_contribution,
                description=f"Max annual contribution for {item.account_id}",
                parameter_type="float",
                min_value=0,
                max_value=1000000,
                step=1000,
            ))

    # Event parameters (key ones)
    for event in config.events:
        event_tags = getattr(event, 'tags', [])

        # Add category as a parameter for UI detection
        if hasattr(event, 'category'):
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.category",
                current_value=event.category,
                default_value=event.category,
                description=f"Category for {event.name}",
                parameter_type="str",
                tags=event_tags,
            ))

        # Add is_earned_income for salary detection
        if hasattr(event, 'is_earned_income'):
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.is_earned_income",
                current_value=event.is_earned_income,
                default_value=event.is_earned_income,
                description=f"Is earned income for {event.name}",
                parameter_type="bool",
                tags=event_tags,
            ))
        if hasattr(event, 'base_amount') and event.base_amount is not None:
            # Check if this is a salary/income event
            is_income = event.category == "income"
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.base_amount",
                current_value=event.base_amount,
                default_value=event.base_amount,
                description=f"Base amount for {event.name}",
                parameter_type="float",
                min_value=0,
                max_value=10000000,
                step=1000,
                tags=event_tags,
                category="Income" if is_income else None,
            ))
        if hasattr(event, 'start_year'):
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.start_year",
                current_value=event.start_year,
                default_value=event.start_year,
                description=f"Start year for {event.name}",
                parameter_type="int",
                min_value=config.meta.start_year,
                max_value=config.meta.end_year,
                step=1,
                tags=event_tags,
                category="Income" if event.category == "income" else None,
            ))
        if hasattr(event, 'end_year'):
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.end_year",
                current_value=event.end_year,
                default_value=event.end_year,
                description=f"End year for {event.name}",
                parameter_type="int",
                min_value=config.meta.start_year,
                max_value=config.meta.end_year,
                step=1,
                tags=event_tags,
                # Salary end_years are usually driven by a .variable_meta slider
                # (e.g. the `retirement` variable); keep them under Income.
                category="Income" if event.category == "income" else None,
            ))
        if hasattr(event, 'inflation_ref'):
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.inflation_ref",
                current_value=event.inflation_ref,
                default_value=event.inflation_ref,
                description=f"Inflation reference for {event.name}",
                parameter_type="str",
                tags=event_tags,
                category="Income" if event.category == "income" else None,
            ))
        if hasattr(event, 'gap_years') and event.gap_years is not None:
            parameters.append(ParameterInfo(
                path=f"events.{event.id}.gap_years",
                current_value=event.gap_years,
                default_value=event.gap_years,
                description=f"Gap years for {event.name} (years when event is skipped)",
                parameter_type="list",
                tags=event_tags,
                category="Income" if event.category == "income" else None,
            ))
        if hasattr(event, 'step_adjustments') and event.step_adjustments is not None:
            # For income events, expose the full step_adjustments dict as a single parameter
            is_income = event.category == "income"
            step_path = f"events.{event.id}.step_adjustments"
            # Step adjustments that alias a YAML variable (e.g. a life-decision
            # toggle) are controlled by that variable, not edited here directly.
            alias_paths = {p for refs in variables.get(".alias_refs", {}).values() for p in refs}
            internal_years = [y for y in event.step_adjustments if f"{step_path}.{y}" in alias_paths]
            if internal_years:
                # For internal events, add individual step_adjustments without category
                for year in internal_years:
                    value = event.step_adjustments[year]
                    parameters.append(ParameterInfo(
                        path=f"{step_path}.{year}",
                        current_value=value,
                        default_value=value,
                        description=f"Step adjustment for {event.name} in {year} (internal)",
                        parameter_type="float" if isinstance(value, float) else "int",
                        min_value=0,
                        max_value=1,
                        step=1,
                        tags=event_tags,
                        # No category - these are internal, controlled by variables like kid_four_exists
                    ))
            else:
                # For user-editable events (like salary), expose as a single dict parameter
                parameters.append(ParameterInfo(
                    path=step_path,
                    current_value=event.step_adjustments,
                    default_value=event.step_adjustments,
                    description=f"Step adjustments for {event.name} (year -> multiplier dict)",
                    parameter_type="dict",
                    min_value=None,
                    max_value=None,
                    step=None,
                    tags=event_tags,
                    category="Income" if is_income else None,
                ))

        # Asset purchase specific parameters
        # Check if this is an asset purchase event (has down_payment)
        if event.__class__.__name__ == 'AssetPurchaseEventConfig':
            if event.down_payment is not None:
                parameters.append(ParameterInfo(
                    path=f"events.{event.id}.down_payment",
                    current_value=event.down_payment,
                    default_value=event.down_payment,
                    description=f"Down payment for {event.name}",
                    parameter_type="float",
                    min_value=0,
                    max_value=10000000,
                    step=1000,
                    tags=event_tags,
                    category="Asset Information",
                ))
            if event.asset_initial_value is not None:
                parameters.append(ParameterInfo(
                    path=f"events.{event.id}.asset_initial_value",
                    current_value=event.asset_initial_value,
                    default_value=event.asset_initial_value,
                    description=f"Initial asset value for {event.name}",
                    parameter_type="float",
                    min_value=0,
                    max_value=10000000,
                    step=1000,
                    tags=event_tags,
                    category="Asset Information",
                ))
            if event.mortgage:
                parameters.append(ParameterInfo(
                    path=f"events.{event.id}.mortgage.principal",
                    current_value=event.mortgage.principal,
                    default_value=event.mortgage.principal,
                    description=f"Mortgage principal for {event.name} (auto-calculated: asset value - down payment)",
                    parameter_type="float",
                    min_value=0,
                    max_value=10000000,
                    step=1000,
                    tags=event_tags,
                    category="Asset Information",
                ))
                parameters.append(ParameterInfo(
                    path=f"events.{event.id}.mortgage.interest_rate",
                    current_value=event.mortgage.interest_rate,
                    default_value=event.mortgage.interest_rate,
                    description=f"Mortgage interest rate for {event.name}",
                    parameter_type="float",
                    min_value=0.0,
                    max_value=0.20,
                    step=0.001,
                    tags=event_tags,
                    category="Asset Information",
                ))
                parameters.append(ParameterInfo(
                    path=f"events.{event.id}.mortgage.term_years",
                    current_value=event.mortgage.term_years,
                    default_value=event.mortgage.term_years,
                    description=f"Mortgage term (years) for {event.name}",
                    parameter_type="int",
                    min_value=1,
                    max_value=50,
                    step=1,
                    tags=event_tags,
                    category="Asset Information",
                ))

        # Step adjustments for conditional events (e.g. "fourth kid exists")
        # are handled above via the generic .alias_refs mechanism.

    return parameters


# --- API Endpoints ---

@app.get("/api/scenarios", response_model=List[ScenarioInfo])
async def list_scenarios():
    """List all available scenarios."""
    return get_available_scenarios()


@app.get("/api/scenarios/{scenario_name}/parameters", response_model=List[ParameterInfo])
async def get_scenario_parameters(scenario_name: str):
    """Get all tunable parameters for a scenario."""
    scenario_path = get_scenarios_dir() / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found")

    config, variables = load_scenario_from_yaml(scenario_path, return_variables=True)
    return get_tunable_parameters(config, variables)


@app.post("/api/scenarios/{scenario_name}/run", response_model=SimulationResponse)
async def run_scenario(scenario_name: str, request: RunScenarioRequest):
    """Run a scenario with optional parameter overrides."""
    scenario_path = get_scenarios_dir() / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found")

    try:
        config, variables = load_scenario_from_yaml(scenario_path, return_variables=True)

        # Apply parameter overrides (including variables)
        if request.parameter_overrides:
            config, variables = apply_parameter_overrides(config, request.parameter_overrides, variables)

        # Apply year overrides
        if request.start_year is not None:
            config.meta.start_year = request.start_year
        if request.end_year is not None:
            config.meta.end_year = request.end_year

        # Run simulation
        df = run_simulation(config)

        # Optionally express all future dollars in today's dollars
        if request.real_dollars:
            df = deflate_results(df, config)

        # Convert to response
        result = dataframe_to_response(df)

        return SimulationResponse(
            success=True,
            data=result["data"],
            columns=result["columns"],
            summary=result["summary"],
            deflated=request.real_dollars,
        )
    except Exception as e:
        return SimulationResponse(
            success=False,
            error=str(e),
        )


@app.get("/api/scenarios/{scenario_name}/run", response_model=SimulationResponse)
async def run_scenario_get(
    scenario_name: str,
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    real_dollars: bool = Query(False, description="Deflate all future dollars to today's (start year) dollars"),
):
    """Run a scenario via GET with query parameter overrides."""
    scenario_path = get_scenarios_dir() / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found")

    try:
        config, variables = load_scenario_from_yaml(scenario_path, return_variables=True)

        if start_year is not None:
            config.meta.start_year = start_year
        if end_year is not None:
            config.meta.end_year = end_year

        # Apply parameter overrides from query params (prefixed with "param.")
        query_params = dict(request.query_params)
        param_overrides = {}
        for key, value in query_params.items():
            if key.startswith("param."):
                param_path = key[6:]  # Remove "param." prefix
                # Try to convert value to appropriate type
                try:
                    # Handle boolean strings
                    if value.lower() == "true":
                        param_overrides[param_path] = 1
                    elif value.lower() == "false":
                        param_overrides[param_path] = 0
                    elif "." in value:
                        param_overrides[param_path] = float(value)
                    else:
                        param_overrides[param_path] = int(value)
                except ValueError:
                    param_overrides[param_path] = value

        if param_overrides:
            overrides = [
                ScenarioParameter(path=k, value=v)
                for k, v in param_overrides.items()
            ]
            config, _ = apply_parameter_overrides(config, overrides, variables)

        df = run_simulation(config)

        # Optionally express all future dollars in today's dollars
        if real_dollars:
            df = deflate_results(df, config)

        result = dataframe_to_response(df)

        return SimulationResponse(
            success=True,
            data=result["data"],
            columns=result["columns"],
            summary=result["summary"],
            deflated=real_dollars,
        )
    except Exception as e:
        return SimulationResponse(
            success=False,
            error=str(e),
        )


@app.get("/api/export/{scenario_name}")
async def export_csv(scenario_name: str):
    """Export scenario results as CSV."""
    scenario_path = get_scenarios_dir() / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found")

    config = load_scenario_from_yaml(scenario_path)
    df = run_simulation(config)

    # Return CSV
    from fastapi.responses import StreamingResponse
    import io

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer)
    csv_buffer.seek(0)

    return StreamingResponse(
        io.BytesIO(csv_buffer.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={scenario_name}-output.csv"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)