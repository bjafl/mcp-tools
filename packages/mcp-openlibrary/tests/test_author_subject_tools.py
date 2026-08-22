# packages/mcp-openlibrary/tests/test_author_subject_tools.py
import asyncio

import mcp_openlibrary.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_json(self, path, **params):
        self.calls.append((path, params))
        return self.response


def test_search_authors_formats_results(monkeypatch):
    fake = _FakeClient({"numFound": 1, "docs": [{"key": "OL23919A", "name": "J. K. Rowling", "work_count": 55}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_authors(query="rowling"))

    assert "J. K. Rowling" in result
    assert "OL23919A" in result


def test_search_authors_no_results(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_authors(query="zzzznoexist"))

    assert "No authors found" in result


def test_get_author_returns_summary(monkeypatch):
    fake = _FakeClient({
        "key": "/authors/OL23919A",
        "name": "J. K. Rowling",
        "bio": {"type": "/type/text", "value": "British author."},
        "birth_date": "31 July 1965",
        "photos": [12345, -1],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL23919A"))

    assert "J. K. Rowling" in result
    assert "British author." in result
    assert "12345" in result
    assert "-1" not in result


def test_get_author_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL123W"))

    assert "not a valid author OLID" in result
    assert fake.calls == []


def test_get_author_not_found(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL999999999A"))

    assert "No author found" in result


def test_get_author_works_lists_entries_and_pagination(monkeypatch):
    fake = _FakeClient({
        "size": 418,
        "links": {"next": "/authors/OL23919A/works.json?limit=1&offset=1"},
        "entries": [{"key": "/works/OL45860018W", "title": "Harry Potter"}],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="OL23919A", limit=1, offset=0))

    assert "Harry Potter" in result
    assert "418" in result
    assert "More results available" in result
    assert "offset=1" in result


def test_get_author_works_no_more_when_next_missing(monkeypatch):
    fake = _FakeClient({"size": 1, "links": {}, "entries": [{"key": "/works/OL1W", "title": "Only Book"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="OL23919A"))

    assert "More results available" not in result


def test_get_author_works_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="not-an-olid"))

    assert "not a valid author OLID" in result
    assert fake.calls == []


def test_search_subjects_slugifies_and_lists_works(monkeypatch):
    fake = _FakeClient({"work_count": 18969, "works": [{"key": "/works/OL262759W", "title": "Wuthering Heights"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_subjects(subject="Science Fiction"))

    assert "Wuthering Heights" in result
    assert fake.calls[0][0] == "/subjects/science_fiction.json"


def test_search_subjects_passes_details_flag(monkeypatch):
    fake = _FakeClient({"work_count": 1, "works": [{"key": "/works/OL1W", "title": "X"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.search_subjects(subject="love", details=True))

    assert fake.calls[0][1]["details"] == "true"


def test_search_subjects_no_results(monkeypatch):
    fake = _FakeClient({"work_count": 0, "works": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_subjects(subject="nonexistent"))

    assert "No works found" in result
