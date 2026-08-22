def is_valid_steamid64(steamid: str) -> bool:
    """SteamID64 is a 17-digit decimal string."""
    return steamid.isdigit() and len(steamid) == 17


def steam_icon_url(appid: int, img_icon_url: str) -> str:
    return f"https://media.steampowered.com/steamcommunity/public/images/apps/{appid}/{img_icon_url}.jpg"


def minutes_to_hours(minutes: int) -> float:
    return round(minutes / 60, 1)


_VISIBILITY_LABELS = {1: "private/friends only", 3: "public"}


def visibility_label(state: int) -> str:
    return _VISIBILITY_LABELS.get(state, "unknown")


_PERSONA_STATE_LABELS = {
    0: "Offline",
    1: "Online",
    2: "Busy",
    3: "Away",
    4: "Snooze",
    5: "Looking to trade",
    6: "Looking to play",
}


def persona_state_label(state: int) -> str:
    return _PERSONA_STATE_LABELS.get(state, "Unknown")


def is_empty_owned_games_response(data: dict) -> bool:
    """Detect GetOwnedGames' silent-private shape: {"response": {}} with no "games" key."""
    return "games" not in data.get("response", {})


def player_achievements_error(data: dict) -> str | None:
    """Given a GetPlayerAchievements response, return a human error message if the API
    reported failure (private profile, no stats for this app), else None on genuine success."""
    playerstats = data.get("playerstats", {})
    if playerstats.get("success") is False:
        return playerstats.get("error", "Steam reported an error for this request.")
    return None
