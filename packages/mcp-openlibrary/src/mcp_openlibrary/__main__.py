# packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py
import argparse
import json
import os
import re
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from mcp_openlibrary.client import OpenLibraryClient
from mcp_openlibrary.normalize import author_refs, cover_url, olid_kind, strip_missing_covers, subject_slug, unwrap

app = MCPServer("mcp-openlibrary")

DEFAULT_USER_AGENT = "mcp-openlibrary/0.1.0 (+https://github.com/bjafl/mcp-tools)"

CLIENT: OpenLibraryClient | None = None

DEFAULT_SEARCH_FIELDS = (
    "key,title,subtitle,author_key,author_name,first_publish_year,"
    "publish_year,publisher,language,edition_count,edition_key,isbn,"
    "cover_i,cover_edition_key,subject,ebook_access,has_fulltext,ia,"
    "ratings_average,ratings_count,number_of_pages_median,lcc,ddc"
)

_ISBN_RE = re.compile(r"^[0-9Xx-]{10,17}$")


def _not_found(kind: str, identifier: str) -> str:
    return f"No {kind} found for '{identifier}'."


def _is_isbn(identifier: str) -> bool:
    digits = identifier.replace("-", "")
    return bool(_ISBN_RE.match(identifier)) and len(digits) in (10, 13)


def _resolve_user_agent(cli_value: str | None) -> str:
    """CLI value wins; else OPENLIBRARY_USER_AGENT env var; else the default."""
    if cli_value is not None:
        return cli_value
    return os.environ.get("OPENLIBRARY_USER_AGENT", DEFAULT_USER_AGENT)


def _client() -> OpenLibraryClient:
    """Return the shared client, creating a default one if main() never ran.

    Entry points that import `app` without going through main() (e.g. `mcp dev` /
    `mcp run`) would otherwise leave CLIENT as None and crash every tool.
    """
    global CLIENT
    if CLIENT is None:
        CLIENT = OpenLibraryClient(user_agent=_resolve_user_agent(None))
    return CLIENT


@app.tool(description="Search Open Library for books by title, author, subject, or a Solr query.")
async def search_books(
    query: Annotated[str, Field(description="Search query, e.g. 'tolkien' or 'title:hobbit AND author_name:tolkien'")],
    fields: Annotated[
        str | None,
        Field(description="Comma-separated fields to return. Defaults to a curated set; avoid '*' (expensive)."),
    ] = None,
    sort: Annotated[str | None, Field(description="Sort order, e.g. 'rating desc', 'new'. Default: relevance")] = None,
    limit: Annotated[int, Field(description="Results per page, max 100")] = 10,
    page: Annotated[int, Field(description="1-indexed page number")] = 1,
) -> str:
    limit = min(limit, 100)
    data = await _client().get_json(
        "/search.json",
        q=query,
        fields=fields or DEFAULT_SEARCH_FIELDS,
        sort=sort,
        limit=limit,
        page=page,
    )
    docs = (data or {}).get("docs", [])
    if not docs:
        return f"No books found for query '{query}'."

    total = data.get("numFound", len(docs))
    lines = [f"# {total} result(s) for '{query}' (showing {len(docs)}, page {page})"]
    for doc in docs:
        title = doc.get("title", "(untitled)")
        authors = ", ".join(doc.get("author_name", []) or []) or "unknown author"
        year = doc.get("first_publish_year", "?")
        key = doc.get("key", "")
        lines.append(f"- **{title}** by {authors} ({year}) — `{key}`")
    return "\n".join(lines)


@app.tool(description="Get details for a single Open Library work by its OLID (e.g. 'OL45804W').")
async def get_work(
    olid: Annotated[str, Field(description="Work OLID, e.g. 'OL45804W'")],
) -> str:
    if olid_kind(olid) != "work":
        return f"'{olid}' is not a valid work OLID (expected a pattern like 'OL45804W')."

    data = await _client().get_json(f"/works/{olid}.json")
    if data is None:
        return _not_found("work", olid)

    summary = {
        "olid": olid,
        "title": data.get("title"),
        "description": unwrap(data.get("description")),
        "authors": author_refs(data.get("authors", [])),
        "subjects": data.get("subjects", []),
        "subject_people": data.get("subject_people", []),
        "subject_places": data.get("subject_places", []),
        "subject_times": data.get("subject_times", []),
        "covers": strip_missing_covers(data.get("covers", [])),
    }
    lines = [f"# {summary['title'] or '(untitled)'}", f"**OLID:** {olid}"]
    if summary["authors"]:
        lines.append(f"**Authors:** {', '.join(summary['authors'])}")
    if summary["description"]:
        lines += ["", summary["description"]]
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="Get details for a book edition by its OLID (e.g. 'OL7353617M') or ISBN-10/13.")
async def get_edition(
    identifier: Annotated[str, Field(description="Edition OLID (e.g. 'OL7353617M') or ISBN-10/13")],
) -> str:
    kind = olid_kind(identifier)
    if kind == "edition":
        path = f"/books/{identifier}.json"
    elif kind is None and _is_isbn(identifier):
        path = f"/isbn/{identifier}.json"
    else:
        return f"'{identifier}' is not a valid edition OLID or ISBN."

    data = await _client().get_json(path)
    if data is None:
        return _not_found("edition", identifier)

    summary = {
        "key": data.get("key"),
        "title": data.get("title"),
        "authors": author_refs(data.get("authors", [])),
        "isbn_10": data.get("isbn_10", []),
        "isbn_13": data.get("isbn_13", []),
        "publishers": data.get("publishers", []),
        "publish_date": data.get("publish_date"),
        "number_of_pages": data.get("number_of_pages"),
        "languages": [lang.get("key", "").rsplit("/", 1)[-1] for lang in data.get("languages", [])],
        "first_sentence": unwrap(data.get("first_sentence")),
        "covers": strip_missing_covers(data.get("covers", [])),
        "works": [w.get("key") for w in data.get("works", [])],
    }
    lines = [f"# {summary['title'] or '(untitled)'}", f"**Key:** {summary['key']}"]
    if summary["authors"]:
        lines.append(f"**Authors:** {', '.join(summary['authors'])}")
    if summary["publish_date"]:
        lines.append(f"**Published:** {summary['publish_date']}")
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(
    description=(
        "Build a cover image URL from a cover ID/OLID/ISBN/OCLC/LCCN identifier. "
        "Makes no network request."
    )
)
async def get_cover_url(
    id_type: Annotated[str, Field(description="One of: id, olid, isbn, oclc, lccn (book) or id, olid (author)")],
    id_value: Annotated[str, Field(description="The identifier value, e.g. a cover ID, OLID, or ISBN")],
    size: Annotated[str, Field(description="S, M, or L")] = "M",
    kind: Annotated[str, Field(description="'book' or 'author'")] = "book",
) -> str:
    try:
        return cover_url(id_type, id_value, size, kind=kind)
    except ValueError as exc:
        return str(exc)


@app.tool(description="Search Open Library for authors by name.")
async def search_authors(
    query: Annotated[str, Field(description="Author name or query")],
    limit: Annotated[int, Field(description="Results to return, max 100")] = 10,
) -> str:
    limit = min(limit, 100)
    data = await _client().get_json("/search/authors.json", q=query, limit=limit)
    docs = (data or {}).get("docs", [])
    if not docs:
        return f"No authors found for query '{query}'."

    total = data.get("numFound", len(docs))
    lines = [f"# {total} author(s) for '{query}' (showing {len(docs)})"]
    for doc in docs:
        name = doc.get("name", "(unnamed)")
        key = doc.get("key", "")
        work_count = doc.get("work_count", "?")
        lines.append(f"- **{name}** — {work_count} work(s) — `{key}`")
    return "\n".join(lines)


@app.tool(description="Get details for a single Open Library author by OLID (e.g. 'OL23919A').")
async def get_author(
    olid: Annotated[str, Field(description="Author OLID, e.g. 'OL23919A'")],
) -> str:
    if olid_kind(olid) != "author":
        return f"'{olid}' is not a valid author OLID (expected a pattern like 'OL23919A')."

    data = await _client().get_json(f"/authors/{olid}.json")
    if data is None:
        return _not_found("author", olid)

    summary = {
        "olid": olid,
        "name": data.get("name"),
        "alternate_names": data.get("alternate_names", []),
        "bio": unwrap(data.get("bio")),
        "birth_date": data.get("birth_date"),
        "death_date": data.get("death_date"),
        "remote_ids": data.get("remote_ids", {}),
        "photos": strip_missing_covers(data.get("photos", [])),
    }
    lines = [f"# {summary['name'] or '(unnamed)'}", f"**OLID:** {olid}"]
    if summary["birth_date"]:
        lines.append(f"**Born:** {summary['birth_date']}")
    if summary["bio"]:
        lines += ["", summary["bio"]]
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="List works by an author, paginated.")
async def get_author_works(
    olid: Annotated[str, Field(description="Author OLID, e.g. 'OL23919A'")],
    limit: Annotated[int, Field(description="Results per page, max 100")] = 50,
    offset: Annotated[int, Field(description="Pagination offset")] = 0,
) -> str:
    if olid_kind(olid) != "author":
        return f"'{olid}' is not a valid author OLID (expected a pattern like 'OL23919A')."

    limit = min(limit, 100)
    data = await _client().get_json(f"/authors/{olid}/works.json", limit=limit, offset=offset)
    if data is None:
        return _not_found("author", olid)

    entries = data.get("entries", [])
    if not entries:
        return f"No works found for author '{olid}'."

    total = data.get("size", len(entries))
    has_more = bool(data.get("links", {}).get("next"))
    lines = [f"# {total} work(s) by {olid} (showing {len(entries)} from offset {offset})"]
    for entry in entries:
        title = entry.get("title", "(untitled)")
        key = entry.get("key", "")
        lines.append(f"- **{title}** — `{key}`")
    if has_more:
        lines.append(f"\n_More results available — call again with offset={offset + limit}._")
    return "\n".join(lines)


@app.tool(description="Search/browse Open Library by subject, e.g. 'science fiction' or 'love'.")
async def search_subjects(
    subject: Annotated[str, Field(description="Subject name, e.g. 'science fiction' (auto-slugified)")],
    details: Annotated[
        bool,
        Field(
            description=(
                "Request extra facet data from the API (authors, publishers, publishing_history) — "
                "currently fetched but not included in this tool's summary output; reserved for future use."
            )
        ),
    ] = False,
    limit: Annotated[int, Field(description="Works to return, max 100")] = 10,
    offset: Annotated[int, Field(description="Pagination offset")] = 0,
) -> str:
    limit = min(limit, 100)
    slug = subject_slug(subject)
    data = await _client().get_json(
        f"/subjects/{slug}.json",
        details="true" if details else None,
        limit=limit,
        offset=offset,
    )
    if data is None:
        return _not_found("subject", slug)

    works = data.get("works", [])
    if not works:
        return f"No works found for subject '{slug}'."

    total = data.get("work_count", len(works))
    lines = [f"# {total} work(s) for subject '{slug}' (showing {len(works)} from offset {offset})"]
    for work in works:
        title = work.get("title", "(untitled)")
        key = work.get("key", "")
        lines.append(f"- **{title}** — `{key}`")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-openlibrary")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    parser.add_argument(
        "--user-agent",
        default=None,
        help="User-Agent header for Open Library requests (overrides OPENLIBRARY_USER_AGENT)",
    )
    args = parser.parse_args()

    global CLIENT
    CLIENT = OpenLibraryClient(user_agent=_resolve_user_agent(args.user_agent))

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
