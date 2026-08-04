import argparse
import os
from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from mcp.server.mcpserver import MCPServer
from pydantic import Field

app = MCPServer("mcp-fetch-select")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
TIMEOUT = 20.0


def _proxy_url() -> str | None:
    """Build a proxy URL for outbound requests from MCP_PROXY_* env vars.

    MCP_PROXY_URL is the proxy endpoint (e.g. a tinyproxy instance), and
    MCP_PROXY_USERNAME/MCP_PROXY_PASSWORD supply Basic auth for it if needed.
    """
    url = os.environ.get("MCP_PROXY_URL")
    if not url:
        return None
    username = os.environ.get("MCP_PROXY_USERNAME")
    if not username:
        return url

    password = os.environ.get("MCP_PROXY_PASSWORD", "")
    userinfo = quote(username, safe="")
    if password:
        userinfo += f":{quote(password, safe='')}"

    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, f"{userinfo}@{netloc}", parts.path, parts.query, parts.fragment))


PROXY = _proxy_url()


@app.tool(description="Fetch a URL and return elements matching a CSS selector")
async def fetch_select(
    url: Annotated[str, Field(description="URL to fetch")],
    selector: Annotated[str, Field(description="CSS selector, e.g. .article-body, #main, h2.title")],
    raw_html: Annotated[bool, Field(description="Return raw HTML instead of extracted text")] = False,
    multiple: Annotated[bool, Field(description="If false, return only the first match")] = True,
) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT, proxy=PROXY) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    if multiple:
        matches = soup.select(selector)
    else:
        match = soup.select_one(selector)
        matches = [match] if match else []

    if not matches:
        return f"No matches found for selector '{selector}' on {url}"

    parts = [f"# {len(matches)} match(es) for '{selector}' on {url}"]
    for el in matches:
        if raw_html:
            parts.append(str(el))
        else:
            parts.append(el.get_text(separator="\n", strip=True))

    return "\n\n---\n\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-fetch-select")
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

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
