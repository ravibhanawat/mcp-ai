"""
DeepResearch AI - Entry Point
Run: python main.py [--model <model-id>]

The model is chosen by the administrator in AI Configuration. --model is an
explicit override for a single run and must name a model that is registered
and marked user-selectable; it is not a way to reach an unconfigured backend.
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli.main import run_cli
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DeepResearch AI - Natural language interface to all SAP modules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Use the configured default model
  python main.py --model <model-id>       # Override for this session

Supported SAP Modules:
  FI/CO  - Finance & Controlling
  MM     - Materials Management
  SD     - Sales & Distribution
  HR/HCM - Human Resources
  PP     - Production Planning
        """
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this session (must be user-selectable)"
    )

    args = parser.parse_args()
    run_cli()
