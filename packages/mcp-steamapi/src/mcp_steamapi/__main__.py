import argparse
import json
import os
import sys
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from mcp_steamapi.client import SteamClient
from mcp_steamapi.normalize import is_empty_owned_games_response, is_valid_steamid64, minutes_to_hours, visibility_label

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


@app.tool(description="Resolve a Steam vanity URL name (steamcommunity.com/id/<name>) to a SteamID64.")
async def resolve_vanity_url(
    vanity_url: Annotated[str, Field(description="The name portion of steamcommunity.com/id/<name>")],
) -> str:
    data = await _client().get_api("ISteamUser/ResolveVanityURL/v1", vanityurl=vanity_url)
    response = data.get("response", {})
    if response.get("success") != 1:
        return f"No SteamID64 match found for vanity URL '{vanity_url}'."
    return f"SteamID64: {response['steamid']}"


@app.tool(description="Get a player's profile summary, including public visibility state (preflight check for other tools).")
async def get_player_summary(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetPlayerSummaries/v2", steamids=steamid)
    players = data.get("response", {}).get("players", [])
    if not players:
        return f"No player found for SteamID64 '{steamid}'."

    player = players[0]
    visibility = visibility_label(player.get("communityvisibilitystate", 0))
    lines = [
        f"# {player.get('personaname', '(unknown)')}",
        f"**SteamID64:** {steamid}",
        f"**Profile visibility:** {visibility}",
        f"**Profile URL:** {player.get('profileurl', '')}",
    ]
    if visibility != "public":
        lines.append("")
        lines.append(
            "Note: game/achievement tools will return empty or error results for this player "
            "until their profile is set to Public."
        )
    lines += ["", "## Details", "```json", json.dumps(player, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="Get all games a player owns, with playtime. Requires 'Game details' to be Public.")
async def get_owned_games(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    include_played_free_games: Annotated[
        bool, Field(description="Include free-to-play games the player has played")
    ] = False,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api(
        "IPlayerService/GetOwnedGames/v1",
        steamid=steamid,
        include_appinfo=1,
        include_played_free_games=1 if include_played_free_games else None,
    )
    if is_empty_owned_games_response(data):
        return f"No owned games returned for '{steamid}' — profile or 'Game details' privacy setting is likely not Public."

    games = data.get("response", {}).get("games", [])
    lines = [f"# {len(games)} owned game(s) for {steamid}"]
    for game in games:
        hours = minutes_to_hours(game.get("playtime_forever", 0))
        stats_hint = " (has stats/achievements)" if game.get("has_community_visible_stats") else ""
        lines.append(f"- **{game.get('name', '(unknown)')}** — appid `{game.get('appid')}`, {hours}h played{stats_hint}")
    return "\n".join(lines)


@app.tool(description="Get a player's recently played games (last 2 weeks).")
async def get_recently_played_games(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    count: Annotated[int, Field(description="Max games to return, 0 = all")] = 0,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetRecentlyPlayedGames/v1", steamid=steamid, count=count)
    games = data.get("response", {}).get("games", [])
    if not games:
        return f"No recently played games for '{steamid}'."

    lines = [f"# {len(games)} recently played game(s) for {steamid}"]
    for game in games:
        hours_2w = minutes_to_hours(game.get("playtime_2weeks", 0))
        lines.append(f"- **{game.get('name', '(unknown)')}** — appid `{game.get('appid')}`, {hours_2w}h in last 2 weeks")
    return "\n".join(lines)


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
