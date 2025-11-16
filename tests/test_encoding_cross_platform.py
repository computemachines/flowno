"""
Test encoding handling to ensure cross-platform compatibility.

These tests verify that HTTP headers and bodies are correctly decoded
using UTF-8 explicitly, which prevents issues on Windows where the
default system encoding might be cp1252 or similar.
"""

import pytest
from flowno.io.headers import Headers
from flowno.io.http_client import HttpClient


def test_headers_with_utf8_characters():
    """Test that headers can contain UTF-8 characters."""
    headers = Headers()
    # Test with UTF-8 characters (e.g., café, naïve)
    headers.set("X-Custom-Header", "café")
    headers.set("X-Another-Header", "naïve")
    
    stringified = headers.stringify()
    assert "café" in stringified
    assert "naïve" in stringified
    
    # Ensure encoding to bytes works
    encoded = stringified.encode("utf-8")
    assert b"caf\xc3\xa9" in encoded  # café in UTF-8
    assert b"na\xc3\xafve" in encoded  # naïve in UTF-8


def test_response_decode_json_uses_utf8():
    """Test that Response.decode_json() explicitly uses UTF-8."""
    from flowno.io.http_client import Response
    
    client = HttpClient()
    headers = Headers()
    headers.set("content-type", "application/json")
    
    # Create a response with UTF-8 JSON content
    json_content = '{"message": "café", "status": "naïve"}'
    response = Response(
        client=client,
        status="HTTP/1.1 200 OK",
        headers=headers,
        body=json_content.encode("utf-8")
    )
    
    # This should work correctly even on Windows
    decoded = response.decode_json()
    assert decoded["message"] == "café"
    assert decoded["status"] == "naïve"


def test_err_streaming_response_decode_json_uses_utf8():
    """Test that ErrStreamingResponse.decode_json() explicitly uses UTF-8."""
    from flowno.core.event_loop.event_loop import EventLoop
    from flowno.io.http_client import ErrStreamingResponse
    
    async def main():
        client = HttpClient()
        headers = Headers()
        headers.set("content-type", "application/json")
        
        # Create an error response with UTF-8 JSON content
        json_content = '{"error": "échec", "reason": "système"}'
        response = ErrStreamingResponse(
            client=client,
            status="HTTP/1.1 500 Internal Server Error",
            headers=headers,
            body=json_content.encode("utf-8")
        )
        
        # This should work correctly even on Windows
        decoded = await response.decode_json()
        assert decoded["error"] == "échec"
        assert decoded["reason"] == "système"
        return decoded
    
    loop = EventLoop()
    result = loop.run_until_complete(main(), join=True)
    assert result["error"] == "échec"


def test_header_parsing_with_special_chars():
    """
    Test that header parsing handles UTF-8 correctly.
    
    This simulates what would happen when receiving headers from a server
    that includes UTF-8 characters in header values.
    """
    # Simulate raw header data as it would come from the network
    header_data = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"X-Server-Name: Caf\xc3\xa9-Server\r\n"  # Café-Server in UTF-8
        b"X-Location: Z\xc3\xbcrich\r\n"  # Zürich in UTF-8
        b"\r\n"
    )
    
    # Decode headers (this is what _receive_headers does)
    lines = header_data.decode("utf-8").split("\r\n")
    
    headers = Headers()
    status = lines[0]
    
    for line in lines[1:]:
        if not line:
            continue
        try:
            name, value = line.split(": ", 1)
            headers.set(name, value)
        except ValueError:
            continue
    
    assert status == "HTTP/1.1 200 OK"
    assert headers.get("X-Server-Name") == "Café-Server"
    assert headers.get("X-Location") == "Zürich"


def test_sse_event_parsing_with_utf8():
    """Test that SSE event parsing uses UTF-8 explicitly."""
    # This tests the _split_chunks_to_message_json method behavior
    client = HttpClient()
    
    # Simulate SSE data with UTF-8 characters
    sse_data = b'data: {"message": "Caf\xc3\xa9 ouvert"}\r\n\r\n'
    
    # Parse it
    chunks = list(client._split_chunks_to_message_json(sse_data))
    
    assert len(chunks) == 1
    assert chunks[0]["message"] == "Café ouvert"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
