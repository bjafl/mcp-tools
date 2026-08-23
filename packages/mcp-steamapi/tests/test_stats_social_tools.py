import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_get_user_stats_for_game_lists_stats(monkeypatch):
    fake = _FakeClient({"playerstats": {"stats": [{"name": "PORTALS_PLACED", "value": 3812}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_user_stats_for_game(steamid="76561197960265728", appid=620))

    assert "PORTALS_PLACED" in result
    assert "3812" in result


def test_get_user_stats_for_game_no_stats(monkeypatch):
    fake = _FakeClient({"playerstats": {}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_user_stats_for_game(steamid="76561197960265728", appid=620))

    assert "No stats found" in result


def test_get_user_stats_for_game_private_profile(monkeypatch):
    fake = _FakeClient({"playerstats": {"error": "Profile is not public", "success": False}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_user_stats_for_game(steamid="76561197960265728", appid=620))

    assert "Profile is not public" in result
    assert "No stats found" not in result


def test_get_steam_level_returns_level(monkeypatch):
    fake = _FakeClient({"response": {"player_level": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_steam_level(steamid="76561197960265728"))

    assert "42" in result


def test_get_steam_level_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_steam_level(steamid="bad"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_badges_lists_badges(monkeypatch):
    fake = _FakeClient(
        {"response": {"badges": [{"badgeid": 1, "level": 2, "appid": 620}], "player_level": 10, "player_xp": 500}}
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_badges(steamid="76561197960265728"))

    assert "Badge `1`" in result
    assert "level 2" in result


def test_get_badges_no_badges(monkeypatch):
    fake = _FakeClient({"response": {"badges": [], "player_level": 0, "player_xp": 0}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_badges(steamid="76561197960265728"))

    assert "No badges found" in result


def test_get_friend_list_lists_friends(monkeypatch):
    fake = _FakeClient({"friendslist": {"friends": [{"steamid": "765611979", "friend_since": 1234567}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_friend_list(steamid="76561197960265728"))

    assert "765611979" in result
    assert fake.calls[0][1]["relationship"] == "friend"


def test_get_friend_list_empty(monkeypatch):
    fake = _FakeClient({"friendslist": {"friends": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_friend_list(steamid="76561197960265728"))

    assert "No public friend list found" in result


def test_get_player_bans_reports_status(monkeypatch):
    fake = _FakeClient(
        {
            "players": [
                {
                    "SteamId": "76561197960265728",
                    "VACBanned": False,
                    "NumberOfVACBans": 0,
                    "NumberOfGameBans": 0,
                    "CommunityBanned": False,
                    "EconomyBan": "none",
                    "DaysSinceLastBan": 0,
                }
            ]
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_bans(steamid="76561197960265728"))

    assert "VAC banned" in result
    assert fake.calls[0][1]["steamids"] == "76561197960265728"


def test_get_player_bans_not_found(monkeypatch):
    fake = _FakeClient({"players": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_bans(steamid="76561197960265728"))

    assert "No ban information found" in result
