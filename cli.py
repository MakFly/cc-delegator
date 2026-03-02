"""CLI argument parsing and logging setup for GLM Delegator."""

import argparse
import logging
import os
import sys

DEFAULT_MODEL = os.environ.get("GLM_MODEL", "glm-5")
FALLBACK_MODEL = "glm-4.7"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LLM Delegator MCP Server - Multi-provider expert subagents for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Anthropic Claude
  python3 glm_mcp_server.py -p anthropic-compatible -u https://api.anthropic.com/v1 -k $ANTHROPIC_API_KEY -m claude-sonnet-4-20250514

  # OpenAI
  python3 glm_mcp_server.py -p openai-compatible -u https://api.openai.com/v1 -k $OPENAI_API_KEY -m gpt-4o

  # GLM via Z.AI
  python3 glm_mcp_server.py -p anthropic-compatible -u https://api.z.ai/api/anthropic -k $GLM_API_KEY -m glm-5

  # Ollama local
  python3 glm_mcp_server.py -p openai-compatible -u http://localhost:11434/v1 -m llama3.1
        """
    )

    parser.add_argument(
        "-p", "--provider",
        choices=["openai-compatible", "anthropic-compatible"],
        default="anthropic-compatible",
        help="Provider type (default: anthropic-compatible)"
    )

    parser.add_argument(
        "-u", "--base-url",
        default="https://api.z.ai/api/anthropic",
        help="Base URL of the API (default: https://api.z.ai/api/anthropic)"
    )

    parser.add_argument(
        "-k", "--api-key",
        default=os.environ.get("GLM_API_KEY", os.environ.get("Z_AI_API_KEY", "")),
        help="API key (default: GLM_API_KEY or Z_AI_API_KEY env var)"
    )

    parser.add_argument(
        "-m", "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL}, fallback: {FALLBACK_MODEL})"
    )

    parser.add_argument(
        "--api-version",
        default="2023-06-01",
        help="API version for Anthropic-compatible providers (default: 2023-06-01)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Request timeout in seconds (default: 600)"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="Maximum tokens for responses (default: 8192)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()


def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr
    )
    return logging.getLogger("llm-delegator")
