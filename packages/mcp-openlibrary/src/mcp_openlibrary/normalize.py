import re
from typing import Literal

OlidKind = Literal["work", "edition", "author", "list"]

_OLID_RE = re.compile(r"^OL(\d+)([WMAL])$")
_KIND_BY_SUFFIX: dict[str, OlidKind] = {
    "W": "work",
    "M": "edition",
    "A": "author",
    "L": "list",
}

_BOOK_ID_TYPES = {"id", "olid", "isbn", "oclc", "lccn"}
_AUTHOR_ID_TYPES = {"id", "olid"}
_SIZES = {"S", "M", "L"}


def unwrap(value):
    """Unwrap Open Library's {"type": ..., "value": ...} scalar wrapper, if present."""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def olid_kind(olid: str) -> OlidKind | None:
    """Classify an OLID string (e.g. "OL45804W") into its kind, or None if malformed."""
    match = _OLID_RE.match(olid)
    if not match:
        return None
    return _KIND_BY_SUFFIX[match.group(2)]


def strip_missing_covers(cover_ids: list[int]) -> list[int]:
    """Filter out the -1 sentinel Open Library uses for "no cover"."""
    return [c for c in cover_ids if c != -1]


def cover_url(id_type: str, id_value: str, size: str = "M", kind: str = "book") -> str:
    """Build a covers.openlibrary.org URL. kind is "book" or "author"."""
    if kind not in ("book", "author"):
        raise ValueError(f"kind must be 'book' or 'author', got {kind!r}")
    if size not in _SIZES:
        raise ValueError(f"size must be one of {sorted(_SIZES)}, got {size!r}")
    valid_id_types = _BOOK_ID_TYPES if kind == "book" else _AUTHOR_ID_TYPES
    if id_type not in valid_id_types:
        raise ValueError(f"id_type for kind={kind!r} must be one of {sorted(valid_id_types)}, got {id_type!r}")
    prefix = "b" if kind == "book" else "a"
    return f"https://covers.openlibrary.org/{prefix}/{id_type}/{id_value}-{size}.jpg?default=false"


def subject_slug(subject: str) -> str:
    """Normalize free-text subject input into Open Library's slug form."""
    return re.sub(r"\s+", "_", subject.strip().lower())


def author_refs(authors: list[dict]) -> list[str]:
    """Normalize a Work-shape or Edition-shape authors list into a flat list of author OLIDs.

    Work shape:    [{"author": {"key": "/authors/OL..A"}, "type": {...}}, ...]
    Edition shape: [{"key": "/authors/OL..A"}, ...]
    """
    refs = []
    for entry in authors:
        key = entry.get("author", {}).get("key") if "author" in entry else entry.get("key")
        if key:
            refs.append(key.rsplit("/", 1)[-1])
    return refs
