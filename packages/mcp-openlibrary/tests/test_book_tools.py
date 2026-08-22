import asyncio

import mcp_openlibrary.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_json(self, path, **params):
        self.calls.append((path, params))
        return self.response


def test_search_books_formats_results(monkeypatch):
    fake = _FakeClient({
        "numFound": 2,
        "docs": [
            {"key": "/works/OL1W", "title": "The Hobbit", "author_name": ["J.R.R. Tolkien"], "first_publish_year": 1937},
        ],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_books(query="hobbit"))

    assert "The Hobbit" in result
    assert "J.R.R. Tolkien" in result
    assert "OL1W" in result
    assert fake.calls[0][1]["q"] == "hobbit"


def test_search_books_no_results(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_books(query="zzzznoexist"))

    assert "No books found" in result


def test_search_books_caps_limit_at_100(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.search_books(query="x", limit=500))

    assert fake.calls[0][1]["limit"] == 100


def test_get_work_returns_summary(monkeypatch):
    fake = _FakeClient({
        "key": "/works/OL45804W",
        "title": "Fantastic Mr. Fox",
        "description": "A fox story.",
        "authors": [{"type": {"key": "/type/author_role"}, "author": {"key": "/authors/OL34184A"}}],
        "subjects": ["Foxes"],
        "covers": [8739161, -1],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="OL45804W"))

    assert "Fantastic Mr. Fox" in result
    assert "OL34184A" in result
    assert "8739161" in result
    assert "-1" not in result


def test_get_work_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="not-an-olid"))

    assert "not a valid work OLID" in result
    assert fake.calls == []


def test_get_work_not_found(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="OL999999999W"))

    assert "No work found" in result


def test_get_edition_by_olid(monkeypatch):
    fake = _FakeClient({
        "key": "/books/OL7353617M",
        "title": "Fantastic Mr. Fox",
        "authors": [{"key": "/authors/OL34184A"}],
        "isbn_10": ["014032871X"],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_edition(identifier="OL7353617M"))

    assert "Fantastic Mr. Fox" in result
    assert fake.calls[0][0] == "/books/OL7353617M.json"


def test_get_edition_by_isbn(monkeypatch):
    fake = _FakeClient({"key": "/books/OL7353617M", "title": "Fantastic Mr. Fox"})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.get_edition(identifier="9780140328721"))

    assert fake.calls[0][0] == "/isbn/9780140328721.json"


def test_get_edition_rejects_garbage_identifier(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_edition(identifier="not-valid"))

    assert "not a valid edition OLID or ISBN" in result
    assert fake.calls == []


def test_get_cover_url_makes_no_http_call(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_cover_url(id_type="id", id_value="240727", size="S", kind="book"))

    assert result == "https://covers.openlibrary.org/b/id/240727-S.jpg?default=false"
    assert fake.calls == []


def test_get_cover_url_rejects_bad_size(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_cover_url(id_type="id", id_value="240727", size="XL", kind="book"))

    assert "must be" in result
