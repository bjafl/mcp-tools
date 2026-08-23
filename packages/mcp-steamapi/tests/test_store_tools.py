import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.api_calls = []
        self.store_calls = []

    async def get_api(self, interface_path, **params):
        self.api_calls.append((interface_path, params))
        return self.response

    async def get_store(self, path, **params):
        self.store_calls.append((path, params))
        return self.response


def test_search_app_by_name_finds_matches(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}, {"appid": 400, "name": "Portal"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    result = asyncio.run(main_mod.search_app_by_name(query="portal"))

    assert "Portal 2" in result
    assert "620" in result
    assert fake.api_calls[0][0] == "ISteamApps/GetAppList/v2"
    assert fake.store_calls == []


def test_search_app_by_name_caches_second_call(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    asyncio.run(main_mod.search_app_by_name(query="portal"))
    asyncio.run(main_mod.search_app_by_name(query="portal"))

    assert len(fake.api_calls) == 1
    assert fake.store_calls == []


def test_search_app_by_name_no_matches(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    result = asyncio.run(main_mod.search_app_by_name(query="zzznoexist"))

    assert "No apps found" in result


def test_get_current_player_count_returns_count(monkeypatch):
    fake = _FakeClient({"response": {"result": 1, "player_count": 12345}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_current_player_count(appid=620))

    assert "12345" in result
    assert fake.api_calls[0][0] == "ISteamUserStats/GetNumberOfCurrentPlayers/v1"
    assert fake.api_calls[0][1]["appid"] == 620
    assert fake.store_calls == []


def test_get_current_player_count_not_found(monkeypatch):
    fake = _FakeClient({"response": {"result": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_current_player_count(appid=999999))

    assert "No current player count" in result


def test_get_app_details_formats_summary(monkeypatch):
    fake = _FakeClient(
        {
            "620": {
                "success": True,
                "data": {
                    "name": "Portal 2",
                    "type": "game",
                    "is_free": False,
                    "price_overview": {"final": 1999, "currency": "NOK", "discount_percent": 50},
                    "genres": [{"id": "1", "description": "Action"}],
                    "categories": [{"id": 2, "description": "Single-player"}],
                    "short_description": "A puzzle game.",
                    "developers": ["Valve"],
                    "publishers": ["Valve"],
                    "release_date": {"coming_soon": False, "date": "18 Apr, 2011"},
                    "metacritic": {"score": 95},
                    "detailed_description": "<h1>HUGE HTML BLOB</h1>",
                    "about_the_game": "<h1>ANOTHER HUGE BLOB</h1>",
                    "screenshots": [{"path_full": "https://example.invalid/shot.jpg"}],
                    "movies": [{"name": "Trailer"}],
                    "pc_requirements": {"minimum": "<strong>OS</strong>"},
                },
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_details(appid=620))

    assert "Portal 2" in result
    assert "19.99" in result
    assert "Action" in result
    # curated fields are included in the JSON details block
    assert "Single-player" in result
    assert "A puzzle game." in result
    assert "Valve" in result
    assert "18 Apr, 2011" in result
    assert "95" in result
    # the bulky raw store fields are NOT dumped into agent context
    assert "HUGE HTML BLOB" not in result
    assert "ANOTHER HUGE BLOB" not in result
    assert "screenshots" not in result
    assert "movies" not in result
    assert "pc_requirements" not in result
    assert fake.store_calls[0][0] == "/api/appdetails"
    assert fake.store_calls[0][1]["appids"] == 620
    assert fake.api_calls == []


def test_get_app_details_not_found(monkeypatch):
    fake = _FakeClient({"620": {"success": False}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_details(appid=620))

    assert "No store details found" in result


def test_get_app_reviews_formats_summary(monkeypatch):
    fake = _FakeClient(
        {
            "query_summary": {
                "review_score_desc": "Overwhelmingly Positive",
                "total_positive": 1000,
                "total_negative": 10,
                "total_reviews": 1010,
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_reviews(appid=620))

    assert "Overwhelmingly Positive" in result
    assert "1010" in result
    assert fake.store_calls[0][0] == "/appreviews/620"
    assert fake.api_calls == []


def test_get_app_reviews_not_found(monkeypatch):
    fake = _FakeClient({})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_reviews(appid=620))

    assert "No review summary found" in result
