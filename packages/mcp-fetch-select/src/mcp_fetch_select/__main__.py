import asyncio
from typing import Any

import httpx
from bs4 import BeautifulSoup
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("mcp-fetch-select")

HEADERS = {"User-Agent": "mcp-fetch-select/0.1"}
TIMEOUT = 20.0


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch_select",
            description="Fetch a URL and return elements matching a CSS selector",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector, e.g. .article-body, #main, h2.title",
                    },
                    "raw_html": {
                        "type": "boolean",
                        "description": "Return raw HTML instead of extracted text",
                        "default": False,
                    },
                    "multiple": {
                        "type": "boolean",
                        "description": "If false, return only the first match",
                        "default": True,
                    },
                },
                "required": ["url", "selector"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "fetch_select":
        raise ValueError(f"Unknown tool: {name}")

    url: str = arguments["url"]
    selector: str = arguments["selector"]
    raw_html: bool = arguments.get("raw_html", False)
    multiple: bool = arguments.get("multiple", True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    if multiple:
        matches = soup.select(selector)
    else:
        match = soup.select_one(selector)
        matches = [match] if match else []

    if not matches:
        return [TextContent(type="text", text=f"No matches found for selector '{selector}' on {url}")]

    parts = [f"# {len(matches)} match(es) for '{selector}' on {url}"]
    for el in matches:
        if raw_html:
            parts.append(str(el))
        else:
            parts.append(el.get_text(separator="\n", strip=True))

    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
