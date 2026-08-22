import argparse
import json
import os
import sys
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from mcp_steamapi.cache import TTLCache
from mcp_steamapi.client import SteamClient
from mcp_steamapi.normalize import (
    is_empty_owned_games_response,
    is_valid_steamid64,
    minutes_to_hours,
    player_achievements_error,
    visibility_label,
)

app = MCPServer("mcp-steamapi")

CLIENT: SteamClient | None = None

_SCHEMA_CACHE = TTLCache(ttl_seconds=7 * 24 * 3600)


def _schema_cache_key(appid: int, language: str | None) -> str:
    return f"{appid}:{language or ''}"


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


@app.tool(description="Get all achievements available for a game (cached). Returns empty if the game has no achievements.")
async def get_game_achievements_schema(
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language for displayName/description, e.g. 'norwegian'")] = None,
) -> str:
    cache_key = _schema_cache_key(appid, language)
    data = _SCHEMA_CACHE.get(cache_key)
    if data is None:
        data = await _client().get_api("ISteamUserStats/GetSchemaForGame/v2", appid=appid, l=language)
        _SCHEMA_CACHE.set(cache_key, data)

    game = data.get("game", {})
    achievements = game.get("availableGameStats", {}).get("achievements", [])
    if not achievements:
        return f"No achievements found for appid {appid} (this game may not have achievements)."

    lines = [f"# {len(achievements)} achievement(s) for {game.get('gameName', appid)} (appid {appid})"]
    for ach in achievements:
        hidden = " (hidden)" if ach.get("hidden") else ""
        lines.append(f"- `{ach['name']}` — **{ach.get('displayName', ach['name'])}**{hidden}: {ach.get('description', '')}")
    return "\n".join(lines)


@app.tool(description="Get a player's unlocked/locked achievements for a game.")
async def get_player_achievements(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language for name/description, e.g. 'norwegian'")] = None,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUserStats/GetPlayerAchievements/v1", steamid=steamid, appid=appid, l=language)

    error = player_achievements_error(data)
    if error:
        return f"{error} (steamid {steamid}, appid {appid})"

    achievements = data.get("playerstats", {}).get("achievements", [])
    unlocked = [a for a in achievements if a.get("achieved") == 1]
    lines = [f"# {len(unlocked)}/{len(achievements)} achievement(s) unlocked for appid {appid}"]
    for ach in achievements:
        status = "unlocked" if ach.get("achieved") == 1 else "locked"
        unlock_note = f" (unlocked {ach['unlocktime']})" if ach.get("achieved") == 1 and ach.get("unlocktime") else ""
        lines.append(f"- [{status}] `{ach['apiname']}` — {ach.get('name', ach['apiname'])}{unlock_note}")
    return "\n".join(lines)


@app.tool(description="Get global unlock percentages (rarity) for a game's achievements. No API key needed.")
async def get_global_achievement_percentages(
    appid: Annotated[int, Field(description="Steam appid")],
) -> str:
    data = await _client().get_api(
        "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2", needs_key=False, gameid=appid
    )
    achievements = data.get("achievementpercentages", {}).get("achievements", [])
    if not achievements:
        return f"No global achievement percentages found for appid {appid}."

    lines = [f"# Global achievement rarity for appid {appid}"]
    for ach in achievements:
        lines.append(f"- `{ach['name']}` — {round(ach['percent'], 1)}%")
    return "\n".join(lines)


@app.tool(
    description=(
        "Get a player's numeric stats for a game (e.g. progression counters). Achievements here "
        "lack unlocktime — prefer get_player_achievements for achievement status."
    )
)
async def get_user_stats_for_game(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language, e.g. 'norwegian'")] = None,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUserStats/GetUserStatsForGame/v2", steamid=steamid, appid=appid, l=language)
    stats = data.get("playerstats", {}).get("stats", [])
    if not stats:
        return f"No stats found for steamid {steamid}, appid {appid}."

    lines = [f"# {len(stats)} stat(s) for appid {appid}"]
    for stat in stats:
        lines.append(f"- `{stat.get('name')}`: {stat.get('value')}")
    return "\n".join(lines)


@app.tool(description="Get a player's Steam level.")
async def get_steam_level(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetSteamLevel/v1", steamid=steamid)
    level = data.get("response", {}).get("player_level")
    if level is None:
        return f"No Steam level found for '{steamid}'."
    return f"Steam level for {steamid}: {level}"


@app.tool(description="Get a player's badges and XP progress.")
async def get_badges(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetBadges/v1", steamid=steamid)
    response = data.get("response", {})
    badges = response.get("badges", [])
    lines = [
        f"# Badges for {steamid}",
        f"**Level:** {response.get('player_level', '?')}, **XP:** {response.get('player_xp', '?')}",
        "",
    ]
    if not badges:
        lines.append("No badges found.")
    for badge in badges:
        appid_note = f", appid {badge['appid']}" if badge.get("appid") else ""
        lines.append(f"- Badge `{badge.get('badgeid')}` level {badge.get('level')}{appid_note}")
    return "\n".join(lines)


@app.tool(
    description=(
        "Get a player's friend list. Warning: comparing achievements across friends multiplies "
        "call volume by friends x games — this tool returns the raw list only, no batch comparison."
    )
)
async def get_friend_list(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetFriendList/v1", steamid=steamid, relationship="friend")
    friends = data.get("friendslist", {}).get("friends", [])
    if not friends:
        return f"No public friend list found for '{steamid}'."

    lines = [f"# {len(friends)} friend(s) for {steamid}"]
    for friend in friends:
        lines.append(f"- `{friend.get('steamid')}` — friends since {friend.get('friend_since')}")
    return "\n".join(lines)


@app.tool(description="Get a player's VAC/game/community ban status.")
async def get_player_bans(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetPlayerBans/v1", steamids=steamid)
    players = data.get("players", [])
    if not players:
        return f"No ban information found for '{steamid}'."

    player = players[0]
    lines = [
        f"# Ban status for {steamid}",
        f"**VAC banned:** {player.get('VACBanned')} ({player.get('NumberOfVACBans', 0)} bans)",
        f"**Game banned:** {player.get('NumberOfGameBans', 0)} ban(s)",
        f"**Community banned:** {player.get('CommunityBanned')}",
        f"**Economy ban:** {player.get('EconomyBan')}",
        f"**Days since last ban:** {player.get('DaysSinceLastBan', '?')}",
    ]
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
