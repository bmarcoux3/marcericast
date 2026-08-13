"""Shared pytest configuration.

Points the API's scenario lookup at the scenario fixtures shipped with the
test suite so that tests never depend on the user-editable ``scenarios/``
folder (which users are free to add to or prune).
"""
import os
from pathlib import Path

os.environ["SCENARIOS_DIR"] = str(Path(__file__).parent / "fixtures" / "scenarios")
