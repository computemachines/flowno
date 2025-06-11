"""
Exploratory type-checking tests for the HttpClient API.

This test focuses on narrowing behavior of ``streaming_response_is_ok``
and the basic attributes of ``Response`` objects.
"""

from collections.abc import AsyncIterator
from typing import Any
from typing_extensions import assert_type

from flowno.io import HttpClient
from flowno.io.http_client import (
    ErrStreamingResponse,
    OkStreamingResponse,
    Response,
    streaming_response_is_ok,
)


async def explore_stream(client: HttpClient) -> None:
    response = await client.stream_get("https://example.com")
    if streaming_response_is_ok(response):
        _ = assert_type(response, OkStreamingResponse[Any])
        body_iter = response.body
        _ = assert_type(body_iter, AsyncIterator[Any])
    else:
        _ = assert_type(response, ErrStreamingResponse)
        body_bytes = response.body
        _ = assert_type(body_bytes, bytes)


async def explore_get(client: HttpClient) -> None:
    resp = await client.get("https://example.com")
    _ = assert_type(resp, Response)
    code = resp.status_code
    _ = assert_type(code, int)
    body = resp.body
    _ = assert_type(body, bytes)
