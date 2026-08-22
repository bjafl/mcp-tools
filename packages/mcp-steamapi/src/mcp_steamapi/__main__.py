import argparse
import os
import sys

from mcp.server.mcpserver import MCPServer

from mcp_steamapi.client import SteamClient

app = MCPServer("mcp-steamapi")

CLIENT: SteamClient | None = None


def _resolve_api_key() -> str:
    """Read STEAM_API_KEY from the environment. Exits with a clear error if unset."""
    key = os.environ.get("STEAM_API_KEY")
    if not key:
        print("STEAM_API_KEY environment variable is required but not set.", file=sys.stderr)
        sys.exit(1)
    return key


def _client() -> SteamClient:
    global CLIENT
    if CLIENT is None:
        CLIENT = SteamClient(api_key=_resolve_api_key())
    return CLIENT


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-steamapi")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    args = parser.parse_args()

    _client()  # fail fast if STEAM_API_KEY is missing, before serving any requests

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
