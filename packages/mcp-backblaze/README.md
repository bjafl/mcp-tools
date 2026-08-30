# mcp-backblaze

MCP server for [Backblaze B2 Cloud Storage](https://www.backblaze.com/docs/cloud-storage): list
buckets, browse/upload/download files, and manage file versions.

## Setup

Requires a B2 application key. Create one in the Backblaze web console under
**Account → App Keys**.

```bash
export B2_APPLICATION_KEY_ID=your_key_id
export B2_APPLICATION_KEY=your_application_key
```

## Tools

| Tool | Description |
|---|---|
| `list_buckets` | List all buckets in the account |
| `list_files` | List files in a bucket, with prefix filtering and pagination |
| `upload_file` | Upload a local file to a bucket |
| `upload_content` | Upload inline text/base64 content to a bucket (no local file needed) |
| `get_upload_url` | Get a one-time upload URL/token for direct client-side uploads |
| `download_file` | Download a file (save to disk or return as text) |
| `delete_file` | Delete a specific file version |
| `get_file_info` | Get metadata for a file version |

## Required capabilities

The application key must have the capabilities matching the tools you use:

- `listBuckets` — `list_buckets`
- `listFiles` — `list_files`
- `readFiles` — `download_file`
- `writeFiles` — `upload_file`, `upload_content`, `get_upload_url`
- `deleteFiles` — `delete_file`

## Scope notes

- Uploads go through the server (no multipart support), so file size is limited to B2's single-part
  max (~5 GB). Use `get_upload_url` if the caller should upload directly instead.
- `upload_file`/`download_file` read/write the local filesystem the MCP server runs on.
- No rate limiting: B2 doesn't document request-rate limits for these operations, unlike the public
  APIs the other packages in this repo talk to.

## Local development

```bash
uv --directory packages/mcp-backblaze run mcp-backblaze
uv --directory packages/mcp-backblaze run pytest
```
