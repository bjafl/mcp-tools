import pytest

from mcp_steamapi.normalize import (
    is_valid_steamid64,
    steam_icon_url,
    minutes_to_hours,
    visibility_label,
    persona_state_label,
    is_empty_owned_games_response,
    player_achievements_error,
)


@pytest.mark.parametrize(
    "steamid,expected",
    [
        ("76561197960265728", True),
        ("7656119796026572", False),
        ("765611979602657289", False),
        ("abc", False),
        ("", False),
    ],
)
def test_is_valid_steamid64(steamid, expected):
    assert is_valid_steamid64(steamid) == expected


def test_steam_icon_url_builds_url():
    assert (
        steam_icon_url(620, "abc123hash")
        == "https://media.steampowered.com/steamcommunity/public/images/apps/620/abc123hash.jpg"
    )


@pytest.mark.parametrize("minutes,expected", [(60, 1.0), (90, 1.5), (0, 0.0), (1843, 30.7)])
def test_minutes_to_hours(minutes, expected):
    assert minutes_to_hours(minutes) == expected


@pytest.mark.parametrize("state,expected", [(1, "private/friends only"), (3, "public"), (99, "unknown")])
def test_visibility_label(state, expected):
    assert visibility_label(state) == expected


@pytest.mark.parametrize(
    "state,expected",
    [
        (0, "Offline"),
        (1, "Online"),
        (2, "Busy"),
        (3, "Away"),
        (4, "Snooze"),
        (5, "Looking to trade"),
        (6, "Looking to play"),
        (99, "Unknown"),
    ],
)
def test_persona_state_label(state, expected):
    assert persona_state_label(state) == expected


def test_is_empty_owned_games_response_true_when_no_games_key():
    assert is_empty_owned_games_response({"response": {}}) is True


def test_is_empty_owned_games_response_false_when_games_present():
    assert is_empty_owned_games_response({"response": {"game_count": 0, "games": []}}) is False


def test_player_achievements_error_returns_message_on_failure():
    data = {"playerstats": {"error": "Profile is not public", "success": False}}
    assert player_achievements_error(data) == "Profile is not public"


def test_player_achievements_error_returns_default_message_when_error_missing():
    data = {"playerstats": {"success": False}}
    assert player_achievements_error(data) == "Steam reported an error for this request."


def test_player_achievements_error_none_on_success():
    data = {"playerstats": {"success": True, "achievements": []}}
    assert player_achievements_error(data) is None
