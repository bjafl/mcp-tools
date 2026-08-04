import argparse
import os
import sys
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


PROXY: str | None = None
PROXY_FALLBACK = False
PROXY_FALLBACK_TIMEOUT = 10.0
NOTE_PROXY_FALLBACK = "> Note: the proxy did not respond; this request was sent directly (no proxy)."


def _resolve_proxy_config(
    cli_url: str | None, cli_username: str | None, cli_password: str | None
) -> str | None:
    """Merge CLI proxy args with MCP_PROXY_* env vars, CLI winning per field."""
    url = cli_url if cli_url is not None else os.environ.get("MCP_PROXY_URL")
    if not url:
        return None
    username = cli_username if cli_username is not None else os.environ.get("MCP_PROXY_USERNAME")
    password = cli_password if cli_password is not None else os.environ.get("MCP_PROXY_PASSWORD")
    return _build_proxy_url(url, username, password)


def _build_proxy_url(url: str, username: str | None, password: str | None) -> str:
    """Embed Basic auth userinfo into a proxy URL, if a username is given."""
    if not username:
        return url

    userinfo = quote(username, safe="")
    if password:
        userinfo += f":{quote(password, safe='')}"

    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, f"{userinfo}@{netloc}", parts.path, parts.query, parts.fragment))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _fetch(url: str) -> tuple[httpx.Response, bool]:
    """GET url, honoring PROXY/PROXY_FALLBACK. Returns (response, used_fallback)."""
    if PROXY and PROXY_FALLBACK:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=PROXY_FALLBACK_TIMEOUT, proxy=PROXY
            ) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, False
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ProxyError):
            print(f"proxy did not respond, falling back to a direct request for {url}", file=sys.stderr)
            async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, True

    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT, proxy=PROXY) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response, False


@app.tool(description="Fetch a URL and return elements matching a CSS selector")
async def fetch_select(
    url: Annotated[str, Field(description="URL to fetch")],
    selector: Annotated[str, Field(description="CSS selector, e.g. .article-body, #main, h2.title")],
    raw_html: Annotated[bool, Field(description="Return raw HTML instead of extracted text")] = False,
    multiple: Annotated[bool, Field(description="If false, return only the first match")] = True,
) -> str:
    response, used_fallback = await _fetch(url)
    prefix = f"{NOTE_PROXY_FALLBACK}\n\n" if used_fallback else ""

    soup = BeautifulSoup(response.text, "lxml")

    if multiple:
        matches = soup.select(selector)
    else:
        match = soup.select_one(selector)
        matches = [match] if match else []

    if not matches:
        return f"{prefix}No matches found for selector '{selector}' on {url}"

    parts = [f"# {len(matches)} match(es) for '{selector}' on {url}"]
    for el in matches:
        if raw_html:
            parts.append(str(el))
        else:
            parts.append(el.get_text(separator="\n", strip=True))

    return prefix + "\n\n---\n\n".join(parts)


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
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Proxy endpoint for outbound requests, e.g. http://tinyproxy-host:8888 (overrides MCP_PROXY_URL)",
    )
    parser.add_argument(
        "--proxy-username",
        default=None,
        help="Basic auth username for the proxy (overrides MCP_PROXY_USERNAME)",
    )
    parser.add_argument(
        "--proxy-password",
        default=None,
        help="Basic auth password for the proxy (overrides MCP_PROXY_PASSWORD)",
    )
    parser.add_argument(
        "--proxy-fallback",
        action="store_true",
        help="Fall back to a direct request if the proxy doesn't respond (or set MCP_PROXY_FALLBACK)",
    )
    args = parser.parse_args()

    global PROXY, PROXY_FALLBACK
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)
    PROXY_FALLBACK = args.proxy_fallback or _env_flag("MCP_PROXY_FALLBACK")

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
