import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_resolve_vanity_url_returns_steamid(monkeypatch):
    fake = _FakeClient({"response": {"success": 1, "steamid": "76561197960265728"}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.resolve_vanity_url(vanity_url="gaben"))

    assert "76561197960265728" in result


def test_resolve_vanity_url_no_match(monkeypatch):
    fake = _FakeClient({"response": {"success": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.resolve_vanity_url(vanity_url="zzznoexist"))

    assert "No SteamID64 match found" in result


def test_get_player_summary_returns_visibility(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "players": [
                    {
                        "steamid": "76561197960265728",
                        "personaname": "Gaben",
                        "communityvisibilitystate": 3,
                        "personastate": 1,
                        "profileurl": "https://x",
                    }
                ]
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "Gaben" in result
    assert "public" in result
    assert "**Status:** Online" in result


def test_get_player_summary_labels_persona_state(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "players": [
                    {
                        "steamid": "76561197960265728",
                        "personaname": "Away Guy",
                        "communityvisibilitystate": 3,
                        "personastate": 3,
                    }
                ]
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "**Status:** Away" in result


def test_get_player_summary_flags_private_visibility(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "players": [
                    {"steamid": "76561197960265728", "personaname": "Private Guy", "communityvisibilitystate": 1}
                ]
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "private/friends only" in result
    assert "will return empty or error" in result


def test_get_player_summary_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="not-a-steamid"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_player_summary_not_found(monkeypatch):
    fake = _FakeClient({"response": {"players": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "No player found" in result


def test_get_owned_games_lists_games(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "game_count": 1,
                "games": [
                    {
                        "appid": 620,
                        "name": "Portal 2",
                        "playtime_forever": 1843,
                        "has_community_visible_stats": True,
                        "img_icon_url": "abc123",
                    }
                ],
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="76561197960265728"))

    assert "Portal 2" in result
    assert "620" in result
    assert "has stats/achievements" in result
    assert "https://media.steampowered.com/steamcommunity/public/images/apps/620/abc123.jpg" in result
    assert fake.calls[0][1]["include_appinfo"] == 1


def test_get_owned_games_omits_icon_when_missing(monkeypatch):
    fake = _FakeClient(
        {"response": {"game_count": 1, "games": [{"appid": 620, "name": "Portal 2", "playtime_forever": 60}]}}
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="76561197960265728"))

    assert "Portal 2" in result
    assert "icon:" not in result


def test_get_owned_games_private_response(monkeypatch):
    fake = _FakeClient({"response": {}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="76561197960265728"))

    assert "not Public" in result


def test_get_owned_games_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="bad"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_recently_played_games_lists_games(monkeypatch):
    fake = _FakeClient({"response": {"total_count": 1, "games": [{"appid": 620, "name": "Portal 2", "playtime_2weeks": 120}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_recently_played_games(steamid="76561197960265728"))

    assert "Portal 2" in result
    assert "2.0h" in result


def test_get_recently_played_games_empty(monkeypatch):
    fake = _FakeClient({"response": {"total_count": 0, "games": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_recently_played_games(steamid="76561197960265728"))

    assert "No recently played games" in result
