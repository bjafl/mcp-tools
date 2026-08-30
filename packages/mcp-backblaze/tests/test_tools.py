import asyncio

import mcp_backblaze.__main__ as main_mod


class _FakeClient:
    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    async def list_buckets(self):
        self.calls.append(("list_buckets", {}))
        return self.responses["list_buckets"]

    async def list_files(self, bucket_id, prefix=None, max_file_count=100, start_file_name=None):
        self.calls.append(
            ("list_files", {"bucket_id": bucket_id, "prefix": prefix, "max_file_count": max_file_count, "start_file_name": start_file_name})
        )
        return self.responses["list_files"]

    async def get_upload_url(self, bucket_id):
        self.calls.append(("get_upload_url", {"bucket_id": bucket_id}))
        return self.responses["get_upload_url"]

    async def upload_bytes(self, bucket_id, file_name, data, content_type="b2/x-auto"):
        self.calls.append(
            ("upload_bytes", {"bucket_id": bucket_id, "file_name": file_name, "data": data, "content_type": content_type})
        )
        return self.responses["upload_bytes"]

    async def download_file(self, bucket_name, file_name):
        self.calls.append(("download_file", {"bucket_name": bucket_name, "file_name": file_name}))
        return self.responses["download_file"]

    async def delete_file(self, file_name, file_id):
        self.calls.append(("delete_file", {"file_name": file_name, "file_id": file_id}))
        return self.responses["delete_file"]

    async def get_file_info(self, file_id):
        self.calls.append(("get_file_info", {"file_id": file_id}))
        return self.responses["get_file_info"]


def test_list_buckets_formats_names_ids_and_types(monkeypatch):
    fake = _FakeClient(
        list_buckets=[
            {"bucketId": "b1", "bucketName": "photos", "bucketType": "allPrivate"},
            {"bucketId": "b2", "bucketName": "public-assets", "bucketType": "allPublic"},
        ]
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.list_buckets())

    assert "photos" in result
    assert "`b1`" in result
    assert "allPrivate" in result
    assert "public-assets" in result


def test_list_buckets_empty(monkeypatch):
    fake = _FakeClient(list_buckets=[])
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.list_buckets())

    assert "No buckets" in result


def test_list_files_formats_entries_with_size_and_id(monkeypatch):
    fake = _FakeClient(
        list_files={
            "files": [
                {
                    "fileName": "photos/cat.jpg",
                    "fileId": "f1",
                    "contentLength": 2048,
                    "contentType": "image/jpeg",
                    "uploadTimestamp": 1700000000000,
                    "action": "upload",
                }
            ],
            "nextFileName": None,
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.list_files(bucket_id="b1"))

    assert "photos/cat.jpg" in result
    assert "2.0 KB" in result
    assert "`f1`" in result
    assert "start_file_name" not in result


def test_list_files_passes_prefix_and_pagination_cursor(monkeypatch):
    fake = _FakeClient(list_files={"files": [], "nextFileName": None})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.list_files(bucket_id="b1", prefix="photos/", start_file_name="cat.jpg"))

    call = fake.calls[0][1]
    assert call["prefix"] == "photos/"
    assert call["start_file_name"] == "cat.jpg"


def test_list_files_shows_pagination_hint_when_more_available(monkeypatch):
    fake = _FakeClient(list_files={"files": [], "nextFileName": "dog.jpg"})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.list_files(bucket_id="b1"))

    assert "dog.jpg" in result
    assert "start_file_name" in result


def test_upload_file_reads_local_file_and_reports_result(monkeypatch, tmp_path):
    local_file = tmp_path / "cat.jpg"
    local_file.write_bytes(b"fake-image-bytes")
    fake = _FakeClient(
        upload_bytes={
            "fileId": "f1",
            "fileName": "cat.jpg",
            "contentLength": 16,
            "contentSha1": "abc123",
            "uploadTimestamp": 1700000000000,
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.upload_file(bucket_id="b1", local_path=str(local_file)))

    call = fake.calls[0][1]
    assert call["file_name"] == "cat.jpg"
    assert call["data"] == b"fake-image-bytes"
    assert "abc123" in result
    assert "f1" in result


def test_upload_file_uses_custom_remote_name(monkeypatch, tmp_path):
    local_file = tmp_path / "cat.jpg"
    local_file.write_bytes(b"data")
    fake = _FakeClient(upload_bytes={"fileId": "f1", "fileName": "photos/cat.jpg", "contentLength": 4, "contentSha1": "x", "uploadTimestamp": 0})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.upload_file(bucket_id="b1", local_path=str(local_file), remote_name="photos/cat.jpg"))

    assert fake.calls[0][1]["file_name"] == "photos/cat.jpg"


def test_upload_content_utf8_encodes_text(monkeypatch):
    fake = _FakeClient(upload_bytes={"fileId": "f1", "fileName": "note.md", "contentLength": 5, "contentSha1": "x", "uploadTimestamp": 0})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.upload_content(bucket_id="b1", remote_name="note.md", content="hello"))

    assert fake.calls[0][1]["data"] == b"hello"


def test_upload_content_base64_decodes_binary(monkeypatch):
    import base64

    fake = _FakeClient(upload_bytes={"fileId": "f1", "fileName": "img.png", "contentLength": 3, "contentSha1": "x", "uploadTimestamp": 0})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    encoded = base64.b64encode(b"\x89PNG").decode()
    asyncio.run(main_mod.upload_content(bucket_id="b1", remote_name="img.png", content=encoded, encoding="base64"))

    assert fake.calls[0][1]["data"] == b"\x89PNG"


def test_get_upload_url_returns_url_and_token(monkeypatch):
    fake = _FakeClient(get_upload_url={"uploadUrl": "https://up.example.com", "authorizationToken": "tok-1", "bucketId": "b1"})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_upload_url(bucket_id="b1"))

    assert "https://up.example.com" in result
    assert "tok-1" in result


def test_download_file_without_save_path_returns_text(monkeypatch):
    fake = _FakeClient(download_file=b"hello world")
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.download_file(bucket_name="my-bucket", file_name="note.txt"))

    assert result == "hello world"


def test_download_file_with_save_path_writes_file(monkeypatch, tmp_path):
    fake = _FakeClient(download_file=b"binary-data")
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    out_path = tmp_path / "out.bin"

    result = asyncio.run(main_mod.download_file(bucket_name="my-bucket", file_name="cat.jpg", save_path=str(out_path)))

    assert out_path.read_bytes() == b"binary-data"
    assert str(out_path) in result


def test_delete_file_confirms_deletion(monkeypatch):
    fake = _FakeClient(delete_file={"fileId": "f1", "fileName": "cat.jpg"})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.delete_file(file_name="cat.jpg", file_id="f1"))

    assert "cat.jpg" in result
    assert "f1" in result


def test_get_file_info_formats_metadata(monkeypatch):
    fake = _FakeClient(
        get_file_info={
            "fileName": "cat.jpg",
            "fileId": "f1",
            "contentType": "image/jpeg",
            "contentLength": 1024,
            "contentSha1": "abc123",
            "uploadTimestamp": 1700000000000,
            "action": "upload",
            "fileInfo": {},
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_file_info(file_id="f1"))

    assert "cat.jpg" in result
    assert "1.0 KB" in result
    assert "abc123" in result


def test_get_file_info_includes_custom_metadata(monkeypatch):
    fake = _FakeClient(
        get_file_info={
            "fileName": "cat.jpg",
            "fileId": "f1",
            "contentType": "image/jpeg",
            "contentLength": 1024,
            "contentSha1": "abc123",
            "uploadTimestamp": 1700000000000,
            "action": "upload",
            "fileInfo": {"author": "bjarte"},
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_file_info(file_id="f1"))

    assert "author" in result
    assert "bjarte" in result
