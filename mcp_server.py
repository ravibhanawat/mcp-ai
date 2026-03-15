"""
SAP AI Agent - MCP Server
Exposes all 30 SAP tools (FI/CO, MM, SD, HR, PP, ABAP) via the
Model Context Protocol so any MCP-compatible client or LLM host
(Claude Desktop, Cursor, etc.) can call them directly.

Run:
    python mcp_server.py
"""
import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from tools.tool_registry import TOOLS, execute_tool

# ─── Build MCP server ────────────────────────────────────────────────────────
server = Server("sap-ai-agent")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Expose all SAP tools as MCP tools."""
    mcp_tools = []
    for tool in TOOLS:
        mcp_tools.append(
            types.Tool(
                name=tool["name"],
                description=f"[{tool['module']}] {tool['description']}",
                inputSchema=tool["parameters"],
            )
        )
    return mcp_tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Route MCP tool call to the corresponding SAP module function."""
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
