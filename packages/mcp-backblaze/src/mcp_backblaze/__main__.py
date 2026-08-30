# packages/mcp-backblaze/src/mcp_backblaze/__main__.py
import argparse
import base64
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from mcp_backblaze.client import B2Client

app = MCPServer("mcp-backblaze")

CHARACTER_LIMIT = 25000

CLIENT: B2Client | None = None


def _resolve_credentials() -> tuple[str, str]:
    """Read B2_APPLICATION_KEY_ID/B2_APPLICATION_KEY from the environment. Exits if unset."""
    key_id = os.environ.get("B2_APPLICATION_KEY_ID")
    key = os.environ.get("B2_APPLICATION_KEY")
    if not key_id or not key:
        print(
            "B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY environment variables are required but not set.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key_id, key


def _client() -> B2Client:
    global CLIENT
    if CLIENT is None:
        key_id, key = _resolve_credentials()
        CLIENT = B2Client(key_id=key_id, application_key=key)
    return CLIENT


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


def _format_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(text: str) -> str:
    if len(text) <= CHARACTER_LIMIT:
        return text
    return f"{text[:CHARACTER_LIMIT]}\n...(truncated)"


@app.tool(description="List all Backblaze B2 buckets in the account.")
async def list_buckets() -> str:
    buckets = await _client().list_buckets()
    if not buckets:
        return "No buckets found in this account."

    lines = [f"# {len(buckets)} bucket(s)", ""]
    for bucket in buckets:
        lines.append(
            f"- **{bucket['bucketName']}** (`{bucket['bucketId']}`) — {bucket['bucketType']}"
        )
    return "\n".join(lines)


@app.tool(
    description=(
        "List files in a Backblaze B2 bucket with optional prefix filtering and pagination. "
        "Use prefix='folder/' to browse a virtual folder, and pass the previous response's "
        "next_file_name as start_file_name to fetch the next page."
    )
)
async def list_files(
    bucket_id: Annotated[str, Field(description="Bucket ID (from list_buckets)")],
    prefix: Annotated[str | None, Field(description="Filter by name prefix, e.g. 'photos/'")] = None,
    max_count: Annotated[int, Field(description="Max files to return, 1-1000", ge=1, le=1000)] = 100,
    start_file_name: Annotated[
        str | None, Field(description="Pagination cursor: next_file_name from a previous response")
    ] = None,
) -> str:
    result = await _client().list_files(
        bucket_id, prefix=prefix, max_file_count=max_count, start_file_name=start_file_name
    )
    files = result["files"]
    next_file_name = result.get("nextFileName")

    lines = [f"# {len(files)} file(s) in bucket `{bucket_id}`"]
    if prefix:
        lines.append(f"**Prefix:** `{prefix}`")
    lines.append("")
    for f in files:
        date = _format_timestamp(f["uploadTimestamp"])
        size = _format_bytes(f["contentLength"])
        lines.append(f"- **{f['fileName']}** — {size} · {f.get('contentType') or 'unknown'} · {date} · `{f['fileId']}`")
    if next_file_name:
        lines.append("")
        lines.append(f'*More results available — call again with start_file_name="{next_file_name}".*')

    return _truncate("\n".join(lines))


@app.tool(
    description="Upload a local file to a Backblaze B2 bucket. Max file size ~5 GB (no multipart upload).",
    annotations={"destructiveHint": False, "idempotentHint": False},
)
async def upload_file(
    bucket_id: Annotated[str, Field(description="Destination bucket ID (from list_buckets)")],
    local_path: Annotated[str, Field(description="Absolute path to the local file to upload")],
    remote_name: Annotated[
        str | None,
        Field(description="File name in B2. Defaults to the basename of local_path. Use '/' for virtual folders"),
    ] = None,
    content_type: Annotated[str | None, Field(description="MIME type (default: 'b2/x-auto' for auto-detection)")] = None,
) -> str:
    path = Path(local_path)
    data = path.read_bytes()
    file_name = remote_name or path.name
    result = await _client().upload_bytes(bucket_id, file_name, data, content_type or "b2/x-auto")
    return _format_upload_result(result)


@app.tool(
    description=(
        "Upload inline content (text or base64) to a Backblaze B2 bucket without needing a local file "
        "on the server's filesystem. Use this for generated content; use upload_file for existing files."
    ),
    annotations={"destructiveHint": False, "idempotentHint": False},
)
async def upload_content(
    bucket_id: Annotated[str, Field(description="Destination bucket ID (from list_buckets)")],
    remote_name: Annotated[str, Field(description="File name in B2. Use '/' for virtual folders")],
    content: Annotated[str, Field(description="File contents: UTF-8 text by default, or base64 when encoding='base64'")],
    encoding: Annotated[str, Field(description="'utf-8' or 'base64'")] = "utf-8",
    content_type: Annotated[str | None, Field(description="MIME type (default: 'b2/x-auto' for auto-detection)")] = None,
) -> str:
    data = base64.b64decode(content) if encoding == "base64" else content.encode("utf-8")
    result = await _client().upload_bytes(bucket_id, remote_name, data, content_type or "b2/x-auto")
    return _format_upload_result(result)


def _format_upload_result(result: dict) -> str:
    return "\n".join(
        [
            "# Upload successful",
            "",
            f"- **File**: {result['fileName']}",
            f"- **ID**: `{result['fileId']}`",
            f"- **Size**: {_format_bytes(result['contentLength'])}",
            f"- **SHA1**: `{result['contentSha1']}`",
            f"- **Uploaded**: {_format_timestamp(result['uploadTimestamp'])}",
        ]
    )


@app.tool(
    description=(
        "Get a one-time upload URL and authorization token for direct client-side uploads to a bucket. "
        "Use when the caller uploads directly instead of routing content through this server; "
        "for small files or generated content, use upload_content instead."
    ),
    annotations={"destructiveHint": False, "idempotentHint": False},
)
async def get_upload_url(
    bucket_id: Annotated[str, Field(description="Destination bucket ID (from list_buckets)")],
) -> str:
    result = await _client().get_upload_url(bucket_id)
    return "\n".join(
        [
            "# Upload URL",
            "",
            f"- **URL**: {result['uploadUrl']}",
            f"- **Authorization token**: `{result['authorizationToken']}`",
            f"- **Bucket ID**: `{result['bucketId']}`",
        ]
    )


@app.tool(
    description=(
        "Download a file from a Backblaze B2 bucket. If save_path is given, saves it to disk and "
        "returns a confirmation; otherwise returns the content as text (only suitable for text files)."
    )
)
async def download_file(
    bucket_name: Annotated[str, Field(description="Name of the source bucket (not the ID)")],
    file_name: Annotated[str, Field(description="File path in B2, e.g. 'photos/cat.jpg'")],
    save_path: Annotated[
        str | None, Field(description="Absolute local path to save the file. If omitted, returns content as text")
    ] = None,
) -> str:
    data = await _client().download_file(bucket_name, file_name)

    if save_path:
        Path(save_path).write_bytes(data)
        return f"Downloaded `{file_name}` to `{save_path}` ({_format_bytes(len(data))})"

    text = data.decode("utf-8", errors="replace")
    return _truncate(text)


@app.tool(
    description="Delete a specific file version from Backblaze B2. Permanent — use list_files to get the file_id first.",
    annotations={"destructiveHint": True, "idempotentHint": False},
)
async def delete_file(
    file_name: Annotated[str, Field(description="File name in B2 (from list_files)")],
    file_id: Annotated[str, Field(description="File version ID (from list_files or upload_file)")],
) -> str:
    result = await _client().delete_file(file_name, file_id)
    return f"Deleted `{result['fileName']}` (ID: `{result['fileId']}`)"


@app.tool(description="Get metadata for a specific file version in Backblaze B2.")
async def get_file_info(
    file_id: Annotated[str, Field(description="File version ID (from list_files or upload_file)")],
) -> str:
    info = await _client().get_file_info(file_id)
    lines = [
        "# File info",
        "",
        f"- **Name**: {info['fileName']}",
        f"- **ID**: `{info['fileId']}`",
        f"- **Type**: {info['contentType']}",
        f"- **Size**: {_format_bytes(info['contentLength'])}",
        f"- **SHA1**: `{info['contentSha1']}`",
        f"- **Uploaded**: {_format_timestamp(info['uploadTimestamp'])}",
        f"- **Action**: {info['action']}",
    ]
    custom = info.get("fileInfo") or {}
    if custom:
        lines.append("")
        lines.append("**Custom metadata:**")
        for k, v in custom.items():
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-backblaze")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    args = parser.parse_args()

    _client()  # fail fast if B2 credentials are missing, before serving any requests

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
