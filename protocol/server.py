"""
SAP AI Agent - MCP Server
Exposes all 30 SAP tools (FI/CO, MM, SD, HR, PP, ABAP) via the
Model Context Protocol so any MCP-compatible client or LLM host
(Claude Desktop, Cursor, etc.) can call them directly.

Run:
    python protocol/server.py
"""
import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env from project root so DB_USER, DB_PASSWORD etc. are available
# when launched as a subprocess (e.g. Claude Desktop MCP stdio)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from tools.tool_registry import TOOLS, execute_tool
from agent.auto_research import run_auto_research

# ─── Build MCP server ────────────────────────────────────────────────────────
server = Server("sap-ai-agent")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Expose all SAP tools plus sap_auto_research as MCP tools."""
    mcp_tools = []
    for tool in TOOLS:
        mcp_tools.append(
            types.Tool(
                name=tool["name"],
                description=f"[{tool['module']}] {tool['description']}",
                inputSchema=tool["parameters"],
            )
        )
    # Auto Research meta-tool
    mcp_tools.append(
        types.Tool(
            name="sap_auto_research",
            description=(
                "[ALL MODULES] Automatically gather comprehensive data on any SAP entity "
                "(vendor, material, customer, employee, cost center, production order) by "
                "chaining multiple tool calls and returning an aggregated markdown report "
                "with anomaly detection. Use trigger words like 'research', 'deep dive', "
                "'analyze', 'full report' in your query."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language query about a SAP entity. Include the entity ID "
                            "and a trigger word. Examples: 'research vendor V001', "
                            "'deep dive on material MAT002', 'full report on employee EMP001', "
                            "'analyze customer C001'."
                        ),
                    }
                },
                "required": ["query"],
            },
        )
    )
    return mcp_tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Route MCP tool call to the corresponding SAP module function."""
    if name == "sap_auto_research":
        query = (arguments or {}).get("query", "")
        result = run_auto_research(query, execute_tool)
        output = {
            "report": result["formatted_report"],
            "anomalies": result["anomalies"],
            "tools_used": result["tools_run"],
            "sap_sources": result["sources_used"],
            "entity_type": result["entity_type"],
            "entity_id": result["entity_id"],
        }
        return [types.TextContent(type="text", text=json.dumps(output, indent=2))]

    result = execute_tool(name, arguments or {})
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── Entry point ─────────────────────────────────────────────────────────────
async def main():
    print("SAP AI Agent MCP Server starting (stdio transport)...", file=sys.stderr)
    print(f"Exposing {len(TOOLS)} SAP tools across FI/CO, MM, SD, HR, PP, ABAP", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
