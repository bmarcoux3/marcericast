# Personal Cashflow Visualization Dashboard

An interactive web-based dashboard for visualizing personal financial projections. Built on top of the existing Python simulation engine that processes YAML scenario files and outputs CSV data.

## Features

- **Interactive Parameter Controls** - Adjust inflation rates, growth rates, account balances, mortgage terms, event amounts/timing, and more with real-time updates
- **Multiple Visualizations**:
  - Net Worth Over Time (line/area chart)
  - Annual Cash Flow (bar/line chart)
  - Income vs Expenses (grouped bar chart)
  - Asset Allocation (doughnut chart - final year)
  - Spending by Category (stacked area or horizontal bar chart)
  - Debt Paydown (line chart)
  - Tax Burden Over Time (dual-axis line chart)
  - Account Balances (stacked area chart)
- **Summary Cards** - Key metrics at a glance (Total Income, Expenses, Net Worth, Peak Net Worth, Cash Flow, Taxes)
- **Data Table** - Full tabular data with search/filter and CSV export
- **Theme Support** - Light/dark mode with persisted preference
- **Scenario Management** - Switch between different YAML scenario files
- **Parameter Search & Filtering** - Find parameters quickly by name, description, or category

## Architecture

```
personal-cashflow/
├── api.py                 # FastAPI backend with REST endpoints
├── static/
│   ├── index.html         # Main HTML entry point
│   ├── style.css          # Styling (dataviz skill palette)
│   └── app.js             # Frontend application logic
├── src/                   # Original simulation engine
│   ├── engine.py          # Simulation runner
│   ├── loader.py          # YAML loading & validation
│   ├── schema.py          # Pydantic models
│   ├── tax_engine.py      # Tax calculations
│   ├── waterfall.py       # Cash flow allocation
│   ├── events.py          # Event processing
│   └── domain_models.py   # State models
├── scenarios/             # YAML scenario definitions
│   ├── generic-demo.yaml    # Simple demo scenario
│   └── ...
├── requirements.txt       # Python dependencies
└── DASHBOARD_README.md    # This file
```

## Installation

### Prerequisites

- Python 3.10+
- pip

### Setup

```bash
# Clone/navigate to the project
cd personal-cashflow

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Application

### Option 1: Run the Web Dashboard (Recommended)

```bash
# Start the FastAPI server (serves both API and frontend)
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000

# Open in browser
# http://localhost:8000
```

The dashboard will be available at **http://localhost:8000**

### Option 2: Run Simulation from Command Line (Original)

```bash
# Run a scenario and output CSV to artifacts/
python3 main.py generic-demo

# Or with default generic-demo scenario
python3 main.py
```

### Option 3: Run Tests

```bash
pytest tests/
```

## Using the Dashboard

### Basic Workflow

1. **Select a Scenario** - Choose from the dropdown (e.g., "generic-demo" or "generic-family")
2. **Adjust Parameters** - Expand categories in the sidebar and modify values using:
   - Number inputs for precise values
   - Sliders for rates and percentages
   - Dropdowns for growth rate references
3. **Run Simulation** - Click "Run Simulation" or press `Ctrl+Enter`
4. **Analyze Results** - View charts, summary cards, and data table
5. **Export Data** - Click "Export CSV" for the full dataset or "Download CSV" from the table view

### Keyboard Shortcuts

- `Ctrl+Enter` - Run simulation
- `Ctrl+S` - Export CSV

### Parameter Categories

- **Macroeconomics** - Inflation rate, equity/bond/real estate growth rates, derisking schedule
- **Tax Rules** - Standard deduction, bracket thresholds
- **Accounts** - Initial balances, growth rate references, target balances
- **Waterfall Strategy** - Surplus allocation limits
- **Events** - Income/expense amounts, timing (start/end years), mortgage terms, asset values

### Charts

Each chart has a type selector (line/area/bar) and interactive tooltips. Hover over data points to see exact values for all series at that year.

## API Endpoints

The backend exposes a REST API for programmatic access:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scenarios` | GET | List all available scenarios |
| `/api/scenarios/{name}/parameters` | GET | Get tunable parameters for a scenario |
| `/api/scenarios/{name}/run` | GET/POST | Run simulation with optional parameter overrides |
| `/api/export/{name}` | GET | Download results as CSV |

### Example API Usage

```bash
# Run simulation with custom inflation rate
curl "http://localhost:8000/api/scenarios/generic-demo/run?param.macroeconomics.general_inflation_rate=0.04"

# Run with custom equity growth rate and start year
curl "http://localhost:8000/api/scenarios/generic-demo/run?start_year=2026&param.macroeconomics.growth_rates.equities=0.08"

# Export CSV
curl -o output.csv "http://localhost:8000/api/export/generic-demo"
```

## Creating Custom Scenarios

Add a new YAML file to `scenarios/` following the structure in `scenarios/generic-demo.yaml`. Key sections:

```yaml
version: "1.0"

.variables:        # YAML anchors for reuse (not passed to engine)
  - &retirement 2050
  - &inflation 0.025

meta:
  scenario_name: "My Custom Plan"
  start_year: 2026
  end_year: 2060
  tax_status: "MFJ"
  birth_year: 1990

macroeconomics:
  general_inflation_rate: *inflation
  growth_rates:
    equities: 0.07
    bonds: 0.04
  derisking_schedule:
    equities:
      start_age: 45
      end_age: 70
      transition_to: "bonds"

tax_rules:
  federal:
    standard_deduction: 29200
    brackets:
      - limit: 22000
        rate: 0.10
      # ... more brackets

accounts:
  - id: "checking"
    name: "Checking Account"
    type: "liquid"
    balance: 50000
    is_cash_reserve: true
    min_target_balance: 20000

waterfall_strategy:
  surplus_allocation:
    - account_id: "checking"
    - account_id: "brokerage"
  deficit_drawdown_order:
    - account_id: "checking"
    - account_id: "brokerage"

events:
  - id: "salary"
    name: "Salary"
    type: "cash_stream"
    category: "income"
    start_year: 2026
    end_year: 2050
    base_amount: 150000
    inflation_ref: "general_inflation_rate"
    is_taxable_income: true
    tags: ["Income"]
  # ... more events
```

## Development

### Project Structure

- **Backend**: `api.py` - FastAPI with endpoints for scenarios, parameters, simulation runs, CSV export
- **Frontend**: `static/` - Vanilla JS with Chart.js, no build step required
- **Engine**: `src/` - Pure Python simulation (no external dependencies beyond pandas/pyyaml/pydantic)

### Adding New Chart Types

1. Add canvas element to `static/index.html`
2. Add chart creation function in `static/app.js` (follow existing patterns)
3. Call from `renderAllCharts()`
4. Use the validated color palette from CSS variables (`--series-1` through `--series-8`)

### Color Palette

The dashboard uses the validated color palette from the dataviz skill:

| Slot | Light | Dark | Use Case |
|------|-------|------|----------|
| 1 | `#2a78d6` | `#3987e5` | Primary (Net Worth, Income) |
| 2 | `#eb6834` | `#d95926` | Secondary |
| 3 | `#1baf7a` | `#199e70` | Positive (Expenses, Savings) |
| 4 | `#eda100` | `#c98500` | Warning/Highlight |
| 5 | `#e87ba4` | `#d55181` | Accent |
| 6 | `#008300` | `#008300` | Good/Success |
| 7 | `#4a3aa7` | `#9085e9` | Tertiary |
| 8 | `#e34948` | `#e66767` | Negative (Debt, Taxes) |

## Troubleshooting

### Port Already in Use

```bash
# Find and kill existing process
lsof -ti:8000 | xargs kill -9
```

### Module Import Errors

```bash
# Ensure you're in the project root and venv is activated
cd personal-cashflow
source .venv/bin/activate
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

### Simulation Errors

Check the browser console or API response for error messages. Common issues:
- Invalid parameter values (out of min/max range)
- Missing required fields in scenario YAML
- Date range issues (end_year < start_year)

## License

Personal project - feel free to adapt for your own use.