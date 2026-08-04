import argparse
import asyncio
import json
import os
import sys
from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field
from recipe_scrapers import scrape_html

app = MCPServer("mcp-recipe-scraper")

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
                follow_redirects=True,
                timeout=httpx.Timeout(TIMEOUT, connect=PROXY_FALLBACK_TIMEOUT),
                proxy=PROXY,
            ) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, False
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
            print(f"proxy did not respond, falling back to a direct request for {url}", file=sys.stderr)
            async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, True

    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT, proxy=PROXY) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response, False


@app.tool(
    description=(
        "Scrape structured recipe data (title, ingredients, instructions, "
        "nutrients, yields) from a recipe URL."
    )
)
async def scrape_recipe(
    url: Annotated[str, Field(description="URL of the recipe page to scrape")],
    supported_only: Annotated[
        bool,
        Field(
            description=(
                "If true, only scrape sites with dedicated scrapers. "
                "If false, fall back to generic scraping for unknown sites."
            )
        ),
    ] = False,
) -> str:
    response, used_fallback = await _fetch(url)
    html = response.text

    scraper = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: scrape_html(html=html, org_url=url, supported_only=supported_only),
    )

    data = scraper.to_json()
    # to_json() may return a dict or a JSON string depending on version
    if isinstance(data, str):
        data = json.loads(data)

    # Build a readable text representation alongside the raw JSON
    lines: list[str] = [f"# {scraper.title()}", f"**URL:** {url}", ""]

    yields = _safe(scraper.yields)
    if yields:
        lines += [f"**Yields:** {yields}", ""]

    ingredients = _safe(scraper.ingredients)
    if ingredients:
        lines += ["## Ingredients", *[f"- {i}" for i in ingredients], ""]

    instructions = _safe(scraper.instructions)
    if instructions:
        lines += ["## Instructions", instructions, ""]

    nutrients = _safe(scraper.nutrients)
    if nutrients:
        lines += ["## Nutrients", *[f"- {k}: {v}" for k, v in nutrients.items()], ""]

    lines += ["## Raw JSON", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```"]

    if used_fallback:
        lines.insert(0, NOTE_PROXY_FALLBACK)
        lines.insert(1, "")

    return "\n".join(lines)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-recipe-scraper")
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
