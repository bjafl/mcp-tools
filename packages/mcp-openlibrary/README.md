# mcp-openlibrary

MCP server for the [Open Library](https://openlibrary.org/developers/api) API: search books,
look up works/editions/authors, browse by subject, and build cover image URLs.

No API key required — all endpoints are open and unauthenticated.

## Tools

| Tool | Description |
|---|---|
| `search_books` | Search books by title/author/subject/Solr query |
| `get_work` | Get a work's details by OLID (e.g. `OL45804W`) |
| `get_edition` | Get an edition's details by OLID (e.g. `OL7353617M`) or ISBN-10/13 |
| `search_authors` | Search authors by name |
| `get_author` | Get an author's details by OLID (e.g. `OL23919A`) |
| `get_author_works` | List works by an author, paginated |
| `search_subjects` | Browse works by subject, e.g. "science fiction" |
| `get_cover_url` | Build a cover image URL — no network request |

## Scope notes

- `get_work`/`get_edition` return author references as OLIDs, not resolved names — call
  `get_author` if you need the name.
- No proxy support and no response caching in this version; see
  `docs/superpowers/specs/2026-08-22-mcp-openlibrary-design.md` for the reasoning.
- `--user-agent` / `OPENLIBRARY_USER_AGENT` let you set a custom User-Agent (e.g. to add contact
  info for Open Library's higher rate tier); the default identifies the tool without any personal
  contact info.

## Local development

```bash
uv --directory packages/mcp-openlibrary run mcp-openlibrary
uv --directory packages/mcp-openlibrary run pytest
```
