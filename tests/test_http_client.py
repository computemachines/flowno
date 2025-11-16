from typing import Any, TypeVar

import pytest
from flowno import spawn
from flowno.core.event_loop.event_loop import EventLoop
from flowno.io.http_client import (
    ErrStreamingResponse,
    HttpClient,
    OkStreamingResponse,
    streaming_response_is_ok,
)

T = TypeVar("T")


@pytest.mark.network
def test_get_status():
    async def main():
        client = HttpClient()
        response = await client.get("http://httpstat.us/201")
        return response

    loop = EventLoop()
    response = loop.run_until_complete(main(), join=True)

    assert response.is_ok
    assert response.body == b"201 Created"


@pytest.mark.network
def test_get_stream():
    async def main():
        client = HttpClient()
        response = await client.stream_post(url="http://postman-echo.com/server-events/3", json={"hello": True})

        if streaming_response_is_ok(response):
            async for data in response.body:
                print(f"Received data: {data}")
                assert data["hello"] == True
        return response

    loop = EventLoop()
    response = loop.run_until_complete(main(), join=True)

    assert response.is_ok
    assert isinstance(response, OkStreamingResponse)


@pytest.mark.network
def test_multiple_concurrent_streams():
    client = HttpClient()

    async def stream_task(url: str, expected_data: dict[str, int]):
        response = await client.stream_post(url=url, json=expected_data)

        if streaming_response_is_ok(response):
            async for data in response.body:
                assert data == expected_data
        return response

    async def main():
        # Using postman-echo server that supports multiple concurrent streams
        base_url = "http://postman-echo.com/server-events/3"

        # Spawn multiple concurrent tasks using Flowno's spawn
        task1 = await spawn(stream_task(f"{base_url}?id=1", {"stream": 1}))
        task2 = await spawn(stream_task(f"{base_url}?id=2", {"stream": 2}))
        task3 = await spawn(stream_task(f"{base_url}?id=3", {"stream": 3}))

        # Wait for all tasks to complete
        response1 = await task1.join()
        response2 = await task2.join()
        response3 = await task3.join()

        return [response1, response2, response3]

    loop = EventLoop()
    responses = loop.run_until_complete(main(), join=True)

    for response in responses:
        assert response.is_ok
        assert isinstance(response, OkStreamingResponse)


def test_parse_url():
    client = HttpClient()

    # Test default ports
    host, port, path, use_tls = client._parse_url("http://example.com")
    assert host == "example.com"
    assert port == 80
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://example.com")
    assert host == "example.com"
    assert port == 443
    assert path == "/"
    assert use_tls == True

    # Test non-default ports
    host, port, path, use_tls = client._parse_url("http://example.com:8080")
    assert host == "example.com"
    assert port == 8080
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://example.com:8443")
    assert host == "example.com"
    assert port == 8443
    assert path == "/"
    assert use_tls == True

    # Test paths
    host, port, path, use_tls = client._parse_url("http://example.com/path/to/resource")
    assert host == "example.com"
    assert port == 80
    assert path == "/path/to/resource"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://example.com/path/to/resource")
    assert host == "example.com"
    assert port == 443
    assert path == "/path/to/resource"
    assert use_tls == True

    # Test paths with non-default ports
    host, port, path, use_tls = client._parse_url("http://example.com:8080/path/to/resource")
    assert host == "example.com"
    assert port == 8080
    assert path == "/path/to/resource"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://example.com:8443/path/to/resource")
    assert host == "example.com"
    assert port == 8443
    assert path == "/path/to/resource"
    assert use_tls == True

    # Test localhost, 127.0.0.1, and 0.0.0.0
    host, port, path, use_tls = client._parse_url("http://localhost")
    assert host == "localhost"
    assert port == 80
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://localhost")
    assert host == "localhost"
    assert port == 443
    assert path == "/"
    assert use_tls == True

    host, port, path, use_tls = client._parse_url("http://127.0.0.1")
    assert host == "127.0.0.1"
    assert port == 80
    assert path == "/"
    host, port, path, use_tls = client._parse_url("https://127.0.0.1")
    assert host == "127.0.0.1"
    assert port == 443
    assert path == "/"
    assert use_tls == True

    host, port, path, use_tls = client._parse_url("http://0.0.0.0")
    assert host == "0.0.0.0"
    assert port == 80
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://0.0.0.0")
    assert host == "0.0.0.0"
    assert port == 443
    assert path == "/"
    assert use_tls == True

    # Test localhost, 127.0.0.1, and 0.0.0.0 with non-default ports
    host, port, path, use_tls = client._parse_url("http://localhost:8080")
    assert host == "localhost"
    assert port == 8080
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://localhost:8443")
    assert host == "localhost"
    assert port == 8443
    assert path == "/"
    assert use_tls == True

    host, port, path, use_tls = client._parse_url("http://127.0.0.1:8080")
    assert host == "127.0.0.1"
    assert port == 8080
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://127.0.0.1:8443")
    assert host == "127.0.0.1"
    assert port == 8443
    assert path == "/"
    assert use_tls == True

    host, port, path, use_tls = client._parse_url("http://0.0.0.0:8080")
    assert host == "0.0.0.0"
    assert port == 8080
    assert path == "/"
    assert use_tls == False

    host, port, path, use_tls = client._parse_url("https://0.0.0.0:8443")
    assert host == "0.0.0.0"
    assert port == 8443
    assert path == "/"
    assert use_tls == True


def test_err_streaming_response_with_bytes():
    """Test that ErrStreamingResponse works correctly with non-streaming (bytes) body."""
    from flowno.io.headers import Headers
    
    client = HttpClient()
    headers = Headers()
    headers.set("Content-Type", "application/json")
    
    error_body = b'{"error": "Not found"}'
    response = ErrStreamingResponse(
        client=client,
        status="HTTP/1.1 404 Not Found",
        headers=headers,
        body=error_body
    )
    
    assert response.status_code == 404
    assert not response.is_ok
    assert isinstance(response.body, bytes)
    assert response.body == error_body


def test_err_streaming_response_with_async_iterator():
    """Test that ErrStreamingResponse works correctly with streaming (AsyncIterator) body."""
    from flowno.io.headers import Headers
    
    async def main():
        client = HttpClient()
        headers = Headers()
        headers.set("Content-Type", "application/json")
        
        # Create a streaming body
        async def error_body_generator():
            yield b'{"error": '
            yield b'"Not found"}'
        
        response = ErrStreamingResponse(
            client=client,
            status="HTTP/1.1 404 Not Found",
            headers=headers,
            body=error_body_generator()
        )
        
        assert response.status_code == 404
        assert not response.is_ok
        
        # Collect chunks from streaming body
        chunks = []
        async for chunk in response.body:
            chunks.append(chunk)
        body_data = b''.join(chunks)
        
        assert body_data == b'{"error": "Not found"}'
        return response
    
    loop = EventLoop()
    response = loop.run_until_complete(main(), join=True)
    assert response.status_code == 404


def test_err_streaming_response_decode_json_with_bytes():
    """Test decode_json() with non-streaming body."""
    from flowno.io.headers import Headers
    
    async def main():
        client = HttpClient()
        headers = Headers()
        headers.set("Content-Type", "application/json")
        
        error_body = b'{"error": "Not found", "code": 404}'
        response = ErrStreamingResponse(
            client=client,
            status="HTTP/1.1 404 Not Found",
            headers=headers,
            body=error_body
        )
        
        json_data = await response.decode_json()
        assert json_data["error"] == "Not found"
        assert json_data["code"] == 404
        return json_data
    
    loop = EventLoop()
    result = loop.run_until_complete(main(), join=True)
    assert result["error"] == "Not found"


def test_err_streaming_response_decode_json_with_async_iterator():
    """Test decode_json() with streaming body."""
    from flowno.io.headers import Headers
    
    async def main():
        client = HttpClient()
        headers = Headers()
        headers.set("Content-Type", "application/json")
        
        # Create a streaming body
        async def error_body_generator():
            yield b'{"error": '
            yield b'"Server error", '
            yield b'"code": 500}'
        
        response = ErrStreamingResponse(
            client=client,
            status="HTTP/1.1 500 Internal Server Error",
            headers=headers,
            body=error_body_generator()
        )
        
        json_data = await response.decode_json()
        assert json_data["error"] == "Server error"
        assert json_data["code"] == 500
        return json_data
    
    loop = EventLoop()
    result = loop.run_until_complete(main(), join=True)
    assert result["code"] == 500
