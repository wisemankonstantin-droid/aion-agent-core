import asyncio

import pytest

from app.main import MAX_MACHINE_REQUEST_BYTES, _BoundMachineRequestBody


MACHINE_PATHS = ("/utility/query", "/actions/verify-callability", "/mcp", "/a2a/v1")


def _request(path, chunks, *, content_length=None):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    receive_calls = 0
    downstream_body = None
    response_status = None

    async def receive():
        nonlocal receive_calls
        message = messages[receive_calls]
        receive_calls += 1
        return message

    async def downstream(scope, downstream_receive, send):
        nonlocal downstream_body
        downstream_chunks = []
        while True:
            message = await downstream_receive()
            downstream_chunks.append(message["body"])
            if not message.get("more_body", False):
                break
        downstream_body = b"".join(downstream_chunks)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = message["status"]

    headers = []
    if content_length is not None:
        headers.append((b"content-length", content_length.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(_BoundMachineRequestBody(downstream)(scope, receive, send))
    return response_status, receive_calls, downstream_body


@pytest.mark.parametrize("path", MACHINE_PATHS)
def test_declared_oversized_machine_body_is_rejected_without_reading(path):
    status, receive_calls, downstream_body = _request(
        path,
        [b"unread"],
        content_length=str(MAX_MACHINE_REQUEST_BYTES + 1),
    )
    assert status == 413
    assert receive_calls == 0
    assert downstream_body is None


@pytest.mark.parametrize("path", MACHINE_PATHS)
@pytest.mark.parametrize("content_length", ["", "invalid", "-1", "1, 2"])
def test_malformed_content_length_is_rejected_without_reading(path, content_length):
    status, receive_calls, downstream_body = _request(
        path,
        [b"unread"],
        content_length=content_length,
    )
    assert status == 400
    assert receive_calls == 0
    assert downstream_body is None


@pytest.mark.parametrize("path", MACHINE_PATHS)
def test_valid_content_length_at_limit_preserves_body_for_downstream(path):
    body = b"x" * MAX_MACHINE_REQUEST_BYTES
    status, receive_calls, downstream_body = _request(
        path,
        [body],
        content_length=str(len(body)),
    )
    assert status == 204
    assert receive_calls == 1
    assert downstream_body == body


@pytest.mark.parametrize("path", MACHINE_PATHS)
def test_missing_content_length_stream_at_limit_is_replayed_downstream(path):
    chunks = [b"a" * 32768, b"b" * 32768]
    status, receive_calls, downstream_body = _request(path, chunks)
    assert status == 204
    assert receive_calls == 2
    assert downstream_body == b"".join(chunks)


@pytest.mark.parametrize("path", MACHINE_PATHS)
def test_understated_content_length_does_not_bypass_stream_limit(path):
    chunks = [b"a" * MAX_MACHINE_REQUEST_BYTES, b"b", b"unread"]
    status, receive_calls, downstream_body = _request(
        path,
        chunks,
        content_length="1",
    )
    assert status == 413
    assert receive_calls == 2
    assert downstream_body is None


@pytest.mark.parametrize("path", MACHINE_PATHS)
def test_oversized_stream_stops_on_first_chunk_over_limit(path):
    chunks = [
        b"a" * 32768,
        b"b" * 32768,
        b"c",
        b"must-not-be-consumed",
    ]
    status, receive_calls, downstream_body = _request(path, chunks)
    assert status == 413
    assert receive_calls == 3
    assert downstream_body is None
