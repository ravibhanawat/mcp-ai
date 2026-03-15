"""
SAP AI Agent - Interactive CLI
Beautiful terminal interface for interacting with SAP modules via AI
"""
import sys
import os
import json
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.sap_agent import SAPAgent

# ─────────────────────────────────────────
# ANSI Colors
# ─────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"


def print_banner():
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║    ███████╗ █████╗ ██████╗      █████╗ ██╗                       ║
║    ██╔════╝██╔══██╗██╔══██╗    ██╔══██╗██║                       ║
║    ███████╗███████║██████╔╝    ███████║██║                       ║
║    ╚════██║██╔══██║██╔═══╝     ██╔══██║██║                       ║
║    ███████║██║  ██║██║         ██║  ██║██║                       ║
║    ╚══════╝╚═╝  ╚═╝╚═╝         ╚═╝  ╚═╝╚═╝  Agent v1.0          ║
║                                                                  ║
║    Powered by Ollama  |  All SAP Modules  |  Python              ║
╚══════════════════════════════════════════════════════════════════╝
{Colors.RESET}"""
    print(banner)


def print_module_info():
    modules = [
        ("FI/CO", "Finance & Controlling", "📊"),
        ("MM", "Materials Management", "📦"),
        ("SD", "Sales & Distribution", "🛒"),
        ("HR/HCM", "Human Resources", "👥"),
        ("PP", "Production Planning", "🏭"),
    ]
    print(f"{Colors.BOLD}{Colors.WHITE}  Supported SAP Modules:{Colors.RESET}")
    for code, name, icon in modules:
        print(f"    {icon} {Colors.CYAN}{code:<8}{Colors.RESET} {name}")
    print()


def print_sample_queries():
    queries = [
        ("FI", "What is the status of invoice INV1000?"),
        ("FI", "Show me budget utilization for cost center CC100"),
        ("MM", "Check stock level for MAT001"),
        ("MM", "Which materials need reordering?"),
        ("SD", "Create a sales order for customer C001, material MAT001, qty 5"),
        ("SD", "Show all open sales orders"),
        ("HR", "What is the leave balance for employee EMP001?"),
        ("HR", "Show me Ravi Sharma's payslip"),
        ("PP", "Show production order PRD7001 details"),
        ("PP", "What is the BOM for MAT002?"),
    ]
    print(f"{Colors.BOLD}{Colors.WHITE}  Sample Queries:{Colors.RESET}")
    for module, query in queries[:5]:
        print(f"    {Colors.DIM}[{module}]{Colors.RESET} {query}")
    print(f"    {Colors.DIM}... and more! Type naturally in English{Colors.RESET}")
    print()


def print_separator(char="─", width=68):
    print(f"{Colors.DIM}{char * width}{Colors.RESET}")


def print_tool_call(tool_name: str, result: dict):
    """Display tool call info in a box"""
    print(f"\n  {Colors.DIM}┌─ SAP Tool Called ─────────────────────────┐{Colors.RESET}")
    print(f"  {Colors.DIM}│{Colors.RESET} {Colors.YELLOW}⚙  {tool_name}{Colors.RESET}")

    # Show key result info
    if result.get("status") == "OK":
        print(f"  {Colors.DIM}│{Colors.RESET} {Colors.GREEN}✓  Status: OK{Colors.RESET}")
    else:
        print(f"  {Colors.DIM}│{Colors.RESET} {Colors.RED}✗  Status: {result.get('status', 'UNKNOWN')}{Colors.RESET}")
    print(f"  {Colors.DIM}└────────────────────────────────────────────{Colors.RESET}")


def spinner(message: str, duration: float = 0.5):
    """Show a simple spinner"""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        print(f"\r  {Colors.CYAN}{frames[i % len(frames)]}{Colors.RESET}  {message}...", end="", flush=True)
        time.sleep(0.08)
        i += 1
    print("\r" + " " * 60 + "\r", end="", flush=True)


def run_cli(model: str = "llama3.2"):
    """Main CLI loop"""
    print_banner()

    # Initialize agent
    print(f"  {Colors.CYAN}⟳{Colors.RESET}  Initializing SAP Agent with Ollama model: {Colors.BOLD}{model}{Colors.RESET}")

    agent = SAPAgent(model=model)

    # Check Ollama connection
    print(f"  {Colors.CYAN}⟳{Colors.RESET}  Checking Ollama connection...")
    if agent.check_ollama_connection():
        print(f"  {Colors.GREEN}✓{Colors.RESET}  Ollama connected! Model '{model}' is ready.\n")
    else:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET}  Ollama not detected or model '{model}' not found.")
        print(f"\n  {Colors.BOLD}To set up Ollama:{Colors.RESET}")
        print(f"  1. Install: {Colors.CYAN}curl -fsSL https://ollama.ai/install.sh | sh{Colors.RESET}")
        print(f"  2. Pull model: {Colors.CYAN}ollama pull {model}{Colors.RESET}")
        print(f"  3. Run: {Colors.CYAN}ollama serve{Colors.RESET}")
        print(f"\n  {Colors.DIM}You can still explore the interface. Real queries require Ollama running.{Colors.RESET}\n")

    print_module_info()
    print_separator()
    print_sample_queries()
    print_separator()
    print(f"\n  {Colors.DIM}Type your question in English | 'help' for commands | 'quit' to exit{Colors.RESET}\n")

    while True:
        try:
            # User input
            print(f"{Colors.BOLD}{Colors.BLUE}  You ❯{Colors.RESET} ", end="")
            user_input = input().strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() in ("quit", "exit", "q"):
                print(f"\n  {Colors.CYAN}Goodbye! Closing SAP Agent.{Colors.RESET}\n")
                break

            elif user_input.lower() == "help":
                print(f"\n  {Colors.BOLD}Commands:{Colors.RESET}")
                print(f"  {Colors.CYAN}help{Colors.RESET}     - Show this help")
                print(f"  {Colors.CYAN}reset{Colors.RESET}    - Clear conversation history")
                print(f"  {Colors.CYAN}modules{Colors.RESET}  - Show SAP modules")
                print(f"  {Colors.CYAN}examples{Colors.RESET} - Show example queries")
                print(f"  {Colors.CYAN}quit{Colors.RESET}     - Exit the agent\n")
                continue

            elif user_input.lower() == "reset":
                agent.reset_conversation()
                print(f"  {Colors.GREEN}✓{Colors.RESET}  Conversation history cleared.\n")
                continue

            elif user_input.lower() == "modules":
                print()
                print_module_info()
                continue

            elif user_input.lower() == "examples":
                print()
                print_sample_queries()
                continue

            # Process query
            print()
            spinner("Thinking", 0.3)
            print(f"  {Colors.CYAN}⟳{Colors.RESET}  Processing with Ollama ({model})...", flush=True)

            start_time = time.time()
            response, tool_name, tool_result = agent.chat(user_input)
            elapsed = time.time() - start_time

            # Clear processing line
            print("\r" + " " * 60 + "\r", end="")

            # Show tool call info if applicable
            if tool_name and tool_result:
                print_tool_call(tool_name, tool_result)

            # Show response
            print(f"\n  {Colors.GREEN}{Colors.BOLD}SAP Agent ❯{Colors.RESET}")
            print_separator("·", 68)

            # Format and print response
            for line in response.split("\n"):
                if line.strip():
                    print(f"  {line}")
                else:
                    print()

            print()
            print_separator("·", 68)
            print(f"  {Colors.DIM}Response time: {elapsed:.1f}s{Colors.RESET}\n")

        except KeyboardInterrupt:
            print(f"\n\n  {Colors.CYAN}Interrupted. Type 'quit' to exit.{Colors.RESET}\n")
            continue
        except ConnectionError as e:
            print(f"\n  {Colors.RED}✗  Connection Error: {e}{Colors.RESET}")
            print(f"  {Colors.DIM}Make sure Ollama is running: ollama serve{Colors.RESET}\n")
        except Exception as e:
            print(f"\n  {Colors.RED}✗  Error: {e}{Colors.RESET}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SAP AI Agent with Ollama")
    parser.add_argument("--model", default="llama3.2", help="Ollama model to use (default: llama3.2)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    args = parser.parse_args()

    run_cli(model=args.model)
