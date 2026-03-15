"""
SAP AI Agent - MCP Client
Connects to the MCP server (mcp_server.py) and lets you call any SAP tool
interactively or programmatically.

Usage (interactive CLI):
    python mcp_client.py

Usage (programmatic):
    from mcp_client import SAPMCPClient
    import asyncio

    async def main():
        async with SAPMCPClient() as client:
            tools = await client.list_tools()
            result = await client.call_tool("get_vendor_info", {"vendor_id": "V001"})
            print(result)

    asyncio.run(main())
"""
import asyncio
import json
import sys
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")


class SAPMCPClient:
    """Async context-manager client for the SAP AI Agent MCP server."""

    def __init__(self, server_script: str = SERVER_SCRIPT):
        self.server_script = server_script
        self._client_ctx = None
        self._session_ctx = None
        self.session: ClientSession | None = None

    async def __aenter__(self):
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[self.server_script],
            env=None,
        )
        self._client_ctx = stdio_client(server_params)
        read, write = await self._client_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self.session = await self._session_ctx.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, *args):
        if self._session_ctx:
            await self._session_ctx.__aexit__(*args)
        if self._client_ctx:
            await self._client_ctx.__aexit__(*args)

    async def list_tools(self) -> list[dict]:
        """Return all available SAP tools."""
        response = await self.session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
            }
            for t in response.tools
        ]

    async def call_tool(self, tool_name: str, parameters: dict) -> dict:
        """Call a SAP tool by name and return parsed JSON result."""
        result = await self.session.call_tool(tool_name, parameters)
        if result.content:
            raw = result.content[0].text
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"status": "OK", "raw": raw}
        return {"status": "ERROR", "message": "No content returned"}


# ─── Interactive CLI ──────────────────────────────────────────────────────────
EXAMPLES = {
    "1":  ("get_vendor_info",           {"vendor_id": "V001"}),
    "2":  ("get_invoice_status",        {"invoice_id": "INV1000"}),
    "3":  ("get_stock_level",           {"material_id": "MAT001", "plant": "1000"}),
    "4":  ("get_customer_info",         {"customer_id": "C001"}),
    "5":  ("get_employee_info",         {"emp_id": "EMP001"}),
    "6":  ("get_leave_balance",         {"emp_id": "EMP002"}),
    "7":  ("get_production_order",      {"order_id": "PRD7001"}),
    "8":  ("get_abap_program",          {"program_name": "ZREP_VENDOR_LIST"}),
    "9":  ("get_function_module",       {"fm_name": "Z_GET_VENDOR_MASTER"}),
    "10": ("get_transport_request",     {"tr_id": "DEVK900123"}),
    "11": ("list_abap_programs",        {"package": "ZFICO"}),
    "12": ("analyze_abap_syntax",       {"code_snippet": "SELECT * FROM MARA INTO TABLE lt_mat.\nLOOP AT lt_mat.\n  WRITE: / wa_mat-matnr.\nENDLOOP."}),
    "13": ("list_open_purchase_orders", {}),
    "14": ("check_reorder_needed",      {}),
    "15": ("get_capacity_utilization",  {}),
}


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


async def interactive_cli():
    print(_color("\n╔══════════════════════════════════════╗", "36"))
    print(_color("║   SAP AI Agent — MCP Client CLI      ║", "36"))
    print(_color("╚══════════════════════════════════════╝\n", "36"))

    async with SAPMCPClient() as client:
        tools = await client.list_tools()
        print(_color(f"Connected to MCP server — {len(tools)} tools available\n", "32"))

        while True:
            print(_color("─── Quick Examples ───────────────────────────────────", "90"))
            for k, (name, _) in EXAMPLES.items():
                print(f"  {_color(k.rjust(2), '33')}. {name}")
            print()
            print("  Enter example number, or type:")
            print("  'list'  — show all tools")
            print("  'call'  — call a tool manually (JSON params)")
            print("  'quit'  — exit\n")

            choice = input(_color("Choice > ", "36")).strip()

            if choice.lower() in ("quit", "q", "exit"):
                print("Goodbye!")
                break

            elif choice.lower() == "list":
                print()
                for t in tools:
                    print(f"  {_color(t['name'], '33')} — {t['description']}")
                print()

            elif choice.lower() == "call":
                tool_name = input("Tool name: ").strip()
                params_raw = input("Parameters (JSON, or press Enter for {}): ").strip()
                try:
                    params = json.loads(params_raw) if params_raw else {}
                except json.JSONDecodeError:
                    print(_color("Invalid JSON. Use format: {\"key\": \"value\"}", "31"))
                    continue
                print(_color(f"\nCalling {tool_name}...", "90"))
                result = await client.call_tool(tool_name, params)
                print(_color("Result:", "32"))
                print(json.dumps(result, indent=2))
                print()

            elif choice in EXAMPLES:
                tool_name, params = EXAMPLES[choice]
                print(_color(f"\nCalling {tool_name}({json.dumps(params)})...", "90"))
                result = await client.call_tool(tool_name, params)
                print(_color("Result:", "32"))
                print(json.dumps(result, indent=2))
                print()

            else:
                print(_color("Unknown option. Try a number, 'list', 'call', or 'quit'.\n", "31"))


if __name__ == "__main__":
    asyncio.run(interactive_cli())
