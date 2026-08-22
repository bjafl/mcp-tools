# mcp-steamapi

MCP server for the [Steam Web API](https://steamcommunity.com/dev): achievement mapping,
library/playtime, profile and social lookups, and store metadata.

## Requirements

- A Steam Web API key from https://steamcommunity.com/dev/apikey (requires a Steam account that
  has spent at least $5 USD), set as the `STEAM_API_KEY` environment variable. No CLI flag exists
  for the key, to avoid it ever landing in a process table or client config JSON.

## Tools

| Tool | Description |
|---|---|
| `resolve_vanity_url` | Resolve a vanity URL name to a SteamID64 |
| `get_player_summary` | Profile summary, including public visibility state (preflight check) |
| `get_owned_games` | All games a player owns, with playtime |
| `get_recently_played_games` | Games played in the last 2 weeks |
| `get_game_achievements_schema` | All achievements available for a game (cached) |
| `get_player_achievements` | A player's unlocked/locked achievements for a game |
| `get_global_achievement_percentages` | Global unlock rarity for a game's achievements |
| `get_user_stats_for_game` | Numeric stats (progression counters) |
| `get_steam_level` | A player's Steam level |
| `get_badges` | A player's badges and XP |
| `get_friend_list` | A player's friend list |
| `get_player_bans` | VAC/game/community ban status |
| `search_app_by_name` | Search the Steam catalog by name (cached) |
| `get_current_player_count` | Current in-game player count for an app |
| `get_app_details` | Store metadata: price, genres, description |
| `get_app_reviews` | Review score summary |

## Scope notes

- Achievement mapping requires a **Public** profile and **Public** "Game details" privacy
  setting (two separate Steam settings) — `get_player_summary` surfaces visibility explicitly,
  and `get_owned_games`/`get_player_achievements` give a clear message instead of a silent empty
  result when either is private.
- `get_player_summary`/`get_player_bans` accept a single SteamID64 per call — no batch lookups in
  this version.
- `get_game_achievements_schema` and `search_app_by_name` cache their (large, slow-changing)
  responses in memory for 7 days; nothing else is cached. See
  `docs/superpowers/specs/2026-08-22-mcp-steamapi-design.md` for the reasoning.
- No proxy support in this version.

## Local development

```bash
STEAM_API_KEY=your_key_here uv --directory packages/mcp-steamapi run mcp-steamapi
uv --directory packages/mcp-steamapi run pytest
```
