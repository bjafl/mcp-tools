import pytest

from mcp_openlibrary.normalize import (
    unwrap,
    olid_kind,
    strip_missing_covers,
    cover_url,
    subject_slug,
    author_refs,
)


def test_unwrap_passes_through_plain_string():
    assert unwrap("hello") == "hello"


def test_unwrap_extracts_value_from_wrapper():
    assert unwrap({"type": "/type/text", "value": "hello"}) == "hello"


def test_unwrap_passes_through_none():
    assert unwrap(None) is None


@pytest.mark.parametrize(
    "olid,expected",
    [
        ("OL45804W", "work"),
        ("OL7353617M", "edition"),
        ("OL23919A", "author"),
        ("OL123L", "list"),
    ],
)
def test_olid_kind_classifies_valid_olids(olid, expected):
    assert olid_kind(olid) == expected


@pytest.mark.parametrize("bad", ["", "45804W", "OL45804", "OL45804X", "works/OL45804W"])
def test_olid_kind_returns_none_for_invalid(bad):
    assert olid_kind(bad) is None


def test_strip_missing_covers_filters_negative_one():
    assert strip_missing_covers([15152634, 8739161, -1]) == [15152634, 8739161]


def test_strip_missing_covers_keeps_empty_list():
    assert strip_missing_covers([]) == []


def test_cover_url_book_by_id():
    assert (
        cover_url("id", "240727", "S", kind="book")
        == "https://covers.openlibrary.org/b/id/240727-S.jpg?default=false"
    )


def test_cover_url_book_by_isbn():
    assert (
        cover_url("isbn", "9780385472579", "M", kind="book")
        == "https://covers.openlibrary.org/b/isbn/9780385472579-M.jpg?default=false"
    )


def test_cover_url_author_by_olid():
    assert (
        cover_url("olid", "OL229501A", "L", kind="author")
        == "https://covers.openlibrary.org/a/olid/OL229501A-L.jpg?default=false"
    )


def test_cover_url_rejects_bad_size():
    with pytest.raises(ValueError):
        cover_url("id", "240727", "XL", kind="book")


def test_cover_url_rejects_bad_kind():
    with pytest.raises(ValueError):
        cover_url("id", "240727", "M", kind="magazine")


def test_cover_url_rejects_id_type_not_valid_for_kind():
    with pytest.raises(ValueError):
        cover_url("isbn", "9780385472579", "M", kind="author")


def test_subject_slug_lowercases_and_replaces_spaces():
    assert subject_slug("Science Fiction") == "science_fiction"


def test_subject_slug_strips_and_collapses_whitespace():
    assert subject_slug("  world   war  ") == "world_war"


def test_author_refs_from_work_shape():
    authors = [{"type": {"key": "/type/author_role"}, "author": {"key": "/authors/OL34184A"}}]
    assert author_refs(authors) == ["OL34184A"]


def test_author_refs_from_edition_shape():
    authors = [{"key": "/authors/OL34184A"}]
    assert author_refs(authors) == ["OL34184A"]


def test_author_refs_empty_list():
    assert author_refs([]) == []
