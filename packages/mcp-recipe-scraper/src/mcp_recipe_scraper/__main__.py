import argparse
import asyncio
import json
import os
from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field
from recipe_scrapers import scrape_html

app = MCPServer("mcp-recipe-scraper")

HEADERS = {"User-Agent": "mcp-recipe-scraper/0.1"}
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
    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT, proxy=PROXY) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
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
    args = parser.parse_args()

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
