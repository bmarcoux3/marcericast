import sys
from src.loader import load_scenario_from_yaml
from src.engine import SimulationRunner
from pathlib import Path


def main():
    scenario_path = "scenarios/generic-demo.yaml"
    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if not candidate.endswith(".yaml"):
            candidate += ".yaml"
        if "/" not in candidate:
            candidate = f"scenarios/{candidate}"
        scenario_path = candidate

    print(f"Loading scenario from: {scenario_path}")
    config = load_scenario_from_yaml(scenario_path)

    runner = SimulationRunner(config)
    df = runner.run()

    print("\n--- Simulation Summary (First 10 Years) ---")
    summary_cols = [
        col for col in ["Gross Taxable Income", "Federal Tax", "Net Cash Flow", "Total Assets", "Total Liabilities", "Net Worth"]
        if col in df.columns
    ]
    print(df[summary_cols].head(10))

    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(exist_ok=True)

    file_name = artifacts_dir / f"{Path(scenario_path).stem}-output.csv"
    df.to_csv(file_name)
    print(f"\nFull output exported to {file_name}")


if __name__ == "__main__":
    main()
