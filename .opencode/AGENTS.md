# AGENTS.md

Deterministic personal cashflow simulation engine with a FastAPI dashboard. YAML scenario files in, pandas DataFrame / JSON out. Python 3.10.

## Commands

- Python toolchain is `uv` (pyproject.toml + uv.lock are the source of truth). Setup: `uv sync`. Everything runs via `uv run ...`.
- Tests: `uv run pytest tests/` (272 pass). One test: `uv run pytest tests/test_api_integration.py::TestDataQuality::test_summary_fields`
- Dashboard: `uv run uvicorn api:app --host 0.0.0.0 --port 8000` (serves API + `static/` frontend)
- CLI run (writes `artifacts/<name>-output.csv`): `uv run python main.py <scenario>`
- JS toolchain is `bun` (not npm) — `bun install`, `bunx playwright test` (see e2e below). The frontend has no build step; syntax check: `node --check static/app.js`
- No linter/typecheck configured.
- `.venv` is uv-managed (Python 3.10.12; `.python-version` and `pyproject.toml` require >=3.10 — don't drift above it)

## Tests

- `tests/conftest.py` sets `SCENARIOS_DIR=tests/fixtures/scenarios/`, so pytest never reads user `scenarios/`. API/engine tests must also target the fixture scenarios, never `scenarios/`.
- `test_api_integration.py` pins the five fixture scenario names (`baseline`, `baseline_test`, `comprehensive-baseline`, `comprehensive-baseline-custom`, `generic-family`) — don't prune those fixtures without updating it.
- Playwright e2e (`tests/e2e/*.spec.mjs`) is NOT part of `pytest`:
  - Specs and config must stay `.mjs` — `package.json` is `"type": "commonjs"`, so ESM imports in `.js` files fail to load as "No tests found".
  - Prereqs: `bun install` (`node_modules/` is gitignored) and a server already running on `http://localhost:8000`.
  - Run: `bunx playwright test` or `bunx playwright test test-params`.
  - Parameter categories start collapsed in the sidebar; `test-params.spec.mjs` expands them only after `networkidle` — a re-render during expansion collapses them again (race fixed by retry loop, don't "simplify" it away).

## Architecture

- `api.py` is the FastAPI app at repo root; import as `api:app`. `main.py` is the headless CLI runner.
- Engine in `src/`: `loader.py` (`load_scenario_from_yaml`, validation), `schema.py` (pydantic models), `engine.py` (`SimulationRunner.run()` → DataFrame), plus `tax_engine.py`, `waterfall.py`, `events.py`, `domain_models.py`.
- Data flow: YAML → loader → runner → DataFrame → `dataframe_to_response()` in api.py. The DataFrame index name ("Year") is emitted as `columns[0]` and as a key in every row — the frontend renders `columns` directly and must NOT add its own Year header/cell (caused a duplicate-Column bug).
- Summary `total_expenses` = `-sum(negative "Tag: *" columns)` (includes taxes & investments).
- Frontend is vanilla JS + Chart.js, no build step.

## Conventions & gotchas

- Scenario schema is `extra="forbid"`; unknown fields fail validation. Dot-prefixed keys (`.variables`, `.variable_meta`) are authoring helpers stripped before validation; life-decision toggles come from `.variable_meta`.
- Privacy: `scenarios/marcoux*.yaml`, `scenarios/private/`, `planning/`, `backlog.md` are gitignored personal data. Never commit personal financial data.
- CORS is deliberately restricted to `http://localhost:8000` / `http://127.0.0.1:8000` — do not re-add `allow_origins=["*"]` with `allow_credentials=True`.
- Frontend: interpolate any scenario/API-provided string through `escapeHtml()`; CSV export must go through `csvCell()` (formula-injection protection). No build step or bundler.
- `*.csv` and `artifacts/*` are gitignored (runner output, not tracked).
