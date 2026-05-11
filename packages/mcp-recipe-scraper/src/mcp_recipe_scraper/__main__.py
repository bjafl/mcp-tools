import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from recipe_scrapers import scrape_html, scrape_me

app = Server("mcp-recipe-scraper")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="scrape_recipe",
            description=(
                "Scrape structured recipe data (title, ingredients, instructions, "
                "nutrients, yields) from a recipe URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the recipe page to scrape",
                    },
                    "supported_only": {
                        "type": "boolean",
                        "description": (
                            "If true, only scrape sites with dedicated scrapers. "
                            "If false, fall back to generic scraping for unknown sites."
                        ),
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "scrape_recipe":
        raise ValueError(f"Unknown tool: {name}")

    url: str = arguments["url"]
    supported_only: bool = arguments.get("supported_only", False)

    scraper = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: scrape_html(
            html=None,
            org_url=url,
            online=True,
            supported_only=supported_only,
        ),
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

    return [TextContent(type="text", text="\n".join(lines))]


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
