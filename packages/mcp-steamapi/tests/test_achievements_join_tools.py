import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_get_game_achievements_schema_lists_achievements(monkeypatch):
    fake = _FakeClient(
        {
            "game": {
                "gameName": "Portal 2",
                "availableGameStats": {
                    "achievements": [
                        {"name": "ACH_1", "displayName": "Wake Up Call", "description": "Survive.", "hidden": 0}
                    ]
                },
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    result = asyncio.run(main_mod.get_game_achievements_schema(appid=620))

    assert "Wake Up Call" in result
    assert "ACH_1" in result
    assert fake.calls[0][0] == "ISteamUserStats/GetSchemaForGame/v2"


def test_get_game_achievements_schema_no_achievements(monkeypatch):
    fake = _FakeClient({"game": {"gameName": "Tool App"}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    result = asyncio.run(main_mod.get_game_achievements_schema(appid=1))

    assert "No achievements found" in result


def test_get_game_achievements_schema_caches_second_call(monkeypatch):
    fake = _FakeClient(
        {"game": {"gameName": "Portal 2", "availableGameStats": {"achievements": [{"name": "A", "displayName": "A"}]}}}
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    asyncio.run(main_mod.get_game_achievements_schema(appid=620))
    asyncio.run(main_mod.get_game_achievements_schema(appid=620))

    assert len(fake.calls) == 1


def test_get_player_achievements_lists_status(monkeypatch):
    fake = _FakeClient(
        {
            "playerstats": {
                "success": True,
                "achievements": [
                    {"apiname": "ACH_1", "achieved": 1, "unlocktime": 1421070000, "name": "Wake Up Call"},
                    {"apiname": "ACH_2", "achieved": 0, "unlocktime": 0, "name": "Locked One"},
                ],
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="76561197960265728", appid=620))

    assert "1/2" in result
    assert "[unlocked]" in result
    assert "[locked]" in result


def test_get_player_achievements_private_profile(monkeypatch):
    fake = _FakeClient({"playerstats": {"error": "Profile is not public", "success": False}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="76561197960265728", appid=620))

    assert "Profile is not public" in result


def test_get_player_achievements_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="bad", appid=620))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_global_achievement_percentages_lists_rarity(monkeypatch):
    fake = _FakeClient({"achievementpercentages": {"achievements": [{"name": "ACH_1", "percent": 96.4000015258789}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_global_achievement_percentages(appid=620))

    assert "96.4%" in result
    assert fake.calls[0][1]["gameid"] == 620
    assert fake.calls[0][1]["needs_key"] is False


def test_get_global_achievement_percentages_empty(monkeypatch):
    fake = _FakeClient({"achievementpercentages": {"achievements": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_global_achievement_percentages(appid=1))

    assert "No global achievement percentages" in result
