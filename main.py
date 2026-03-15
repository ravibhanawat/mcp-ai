"""
SAP AI Agent - Entry Point
Run: python main.py [--model llama3.2] [--ollama-url http://localhost:11434]
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli.main import run_cli
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SAP AI Agent - Natural language interface to all SAP modules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                           # Use default llama3.2
  python main.py --model mistral           # Use Mistral model
  python main.py --model llama3.1:8b      # Use specific model version
  python main.py --model codellama        # Use CodeLlama

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
        default="llama3.2",
        help="Ollama model name (default: llama3.2). Other options: mistral, llama3.1, gemma2"
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API URL (default: http://localhost:11434)"
    )

    args = parser.parse_args()
    run_cli(model=args.model)
