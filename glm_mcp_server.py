#!/usr/bin/env python3
"""
LLM Delegator MCP Server

MCP JSON-RPC protocol handler (stdin/stdout). Delegates to server.py for
business logic and cli.py for argument parsing.

Usage:
    python3 glm_mcp_server.py --provider anthropic-compatible --base-url https://api.anthropic.com/v1 --api-key $ANTHROPIC_API_KEY --model claude-sonnet-4-20250514
"""

import asyncio
import json
import sys
from typing import Optional

from cli import parse_args, setup_logging
from server import DelegatorServer, LLMDelegatorMCPServer, EXPERT_PROMPTS  # noqa: F401 — backward compat

# =============================================================================
# MCP Protocol Handlers
# =============================================================================

# Global variables for server and logger
server: Optional[DelegatorServer] = None
logger = None


async def handle_message(message: dict):
    """Handle incoming MCP message."""
    if logger:
        logger.debug(f"Received message: {message.get('method')}")

    if message.get("method") == "initialize":
        return {
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "llm-delegator",
                    "version": "3.0.0"
                },
                "capabilities": {
                    "tools": {}
                }
            }
        }

    elif message.get("method") == "notifications/initialized":
        return None

    elif message.get("method") == "tools/list":
        if not server:
            return {"error": {"code": -32603, "message": "Server not initialized"}}
        await server.start()
        return {"result": await server.list_tools()}

    elif message.get("method") == "tools/call":
        if not server:
            return {"error": {"code": -32603, "message": "Server not initialized"}}
        params = message.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        return {"result": await server.call_tool(name, arguments)}

    else:
        return {
            "error": {
                "code": -32601,
                "message": f"Method not found: {message.get('method')}"
            }
        }


async def main():
    """Main MCP server loop."""
    global server, logger

    args = parse_args()
    logger = setup_logging(args.debug)

    server = DelegatorServer(args, logger)

    if logger:
        logger.info("LLM Delegator MCP Server starting...")

    try:
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                message = json.loads(line.strip())
                response = await handle_message(message)

                if "id" in message and response is not None:
                    response["id"] = message["id"]
                    response["jsonrpc"] = "2.0"
                    send_jsonrpc(response)

            except json.JSONDecodeError as e:
                if logger:
                    logger.error(f"JSON decode error: {e}")
            except Exception as e:
                if logger:
                    logger.error(f"Error processing message: {e}")
    finally:
        if server:
            await server.stop()


def send_jsonrpc(data: dict):
    """Send JSON-RPC message to stdout."""
    json.dump(data, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if logger:
            logger.info("Shutting down...")
