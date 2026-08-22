# packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py
import argparse
import os

from mcp.server.mcpserver import MCPServer

from mcp_openlibrary.client import OpenLibraryClient

app = MCPServer("mcp-openlibrary")

DEFAULT_USER_AGENT = "mcp-openlibrary/0.1.0 (+https://github.com/bjafl/mcp-tools)"

CLIENT: OpenLibraryClient | None = None


def _resolve_user_agent(cli_value: str | None) -> str:
    """CLI value wins; else OPENLIBRARY_USER_AGENT env var; else the default."""
    if cli_value is not None:
        return cli_value
    return os.environ.get("OPENLIBRARY_USER_AGENT", DEFAULT_USER_AGENT)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-openlibrary")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    parser.add_argument(
        "--user-agent",
        default=None,
        help="User-Agent header for Open Library requests (overrides OPENLIBRARY_USER_AGENT)",
    )
    args = parser.parse_args()

    global CLIENT
    CLIENT = OpenLibraryClient(user_agent=_resolve_user_agent(args.user_agent))

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
