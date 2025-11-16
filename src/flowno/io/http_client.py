"""
HTTP Client for Flowno applications.

This module provides an HTTP client that works with Flowno's event loop. The client 
supports both blocking and streaming requests, with automatic handling of chunked 
transfer encoding, gzip/deflate compression, and JSON serialization/deserialization.

Example:
    Basic GET request:
    
    >>> from flowno import EventLoop
    >>> from flowno.io import HttpClient
    >>> 
    >>> async def main():
    ...     client = HttpClient()
    ...     response = await client.get("https://httpbin.org/get")
    ...     print(f"Status: {response.status_code}")
    ...     print(f"Body: {response.body[:50]}...")
    ... 
    >>> loop = EventLoop()
    >>> loop.run_until_complete(main(), join=True)
    Status: 200
    Body: b'{"args":{},"headers":{"Accept-Encoding":"gzip, deflate"...'

    Streaming response with JSON:
    
    >>> from flowno import EventLoop
    >>> from flowno.io import HttpClient
    >>> from flowno.io.http_client import streaming_response_is_ok
    >>> 
    >>> async def main():
    ...     client = HttpClient()
    ...     response = await client.stream_get("https://httpbin.org/stream/3")
    ...     
    ...     if streaming_response_is_ok(response):
    ...         print("Streaming response items:")
    ...         async for chunk in response.body:
    ...             print(f"  {chunk}")
    ... 
    >>> loop = EventLoop()
    >>> loop.run_until_complete(main(), join=True)
    Streaming response items:
      {'id': 0, 'url': 'https://httpbin.org/stream/3'}
      {'id': 1, 'url': 'https://httpbin.org/stream/3'}
      {'id': 2, 'url': 'https://httpbin.org/stream/3'}
"""

import gzip
import json
import logging
import re
import zlib

from collections.abc import AsyncGenerator, AsyncIterator, Generator
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlparse

from flowno import SocketHandle, socket
from flowno.io.headers import Headers
from typing_extensions import TypeIs

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass
class ResponseBase:
    """
    Base class for HTTP responses.
    
    This class contains common properties and methods shared by both regular
    and streaming responses.
    """
    client: "HttpClient"
    status: str  # e.g. "HTTP/1.1 200 OK"
    headers: Headers

    @property
    def status_code(self) -> int:
        """Get the numeric HTTP status code."""
        if not self.status:
            return 0  # Invalid/no response
        parts = self.status.split(" ")
        if len(parts) < 2:
            return 0  # Malformed status line
        try:
            return int(parts[1])
        except ValueError:
            return 0  # Invalid status code

    @property
    def is_ok(self) -> bool:
        """Returns True if the status code is in the 2xx range (successful responses)."""
        return 200 <= self.status_code < 300


@dataclass
class Response(ResponseBase):
    """
    Regular HTTP response with full body.
    
    This class is used for non-streaming responses where the entire body is
    available at once.
    """
    body: bytes

    def is_json(self) -> bool:
        """Check if the response has a JSON content type."""
        content_type = self.headers.get("content-type")
        return content_type == "application/json"

    def decode_json(self) -> Any:
        """Decode the response body as JSON."""
        return self.client.json_decoder.decode(self.body.decode("utf-8"))


@dataclass
class OkStreamingResponse(ResponseBase, Generic[T]):
    """
    Successful streaming HTTP response.
    
    This class is used for streaming responses where the body is available
    as an asynchronous iterator.
    """
    body: AsyncIterator[T]


@dataclass
class ErrStreamingResponse(ResponseBase):
    """
    Error streaming HTTP response.
    
    This class is used for streaming responses that resulted in an error.
    The body may be either complete (bytes) or streaming (AsyncIterator[bytes]),
    depending on whether the server used chunked transfer encoding.
    """
    body: bytes | AsyncIterator[bytes]

    def is_json(self) -> bool:
        """Check if the response has a JSON content type."""
        content_type = self.headers.get("content-type")
        return content_type == "application/json"

    async def decode_json(self) -> Any:
        """
        Decode the response body as JSON.
        
        Note: This method is async because it may need to collect streaming bodies.
        For non-streaming bodies (bytes), it will return immediately.
        """
        if isinstance(self.body, bytes):
            return self.client.json_decoder.decode(self.body.decode("utf-8"))
        else:
            # Collect streaming body
            chunks = []
            async for chunk in self.body:
                chunks.append(chunk)
            body_bytes = b''.join(chunks)
            return self.client.json_decoder.decode(body_bytes.decode("utf-8"))


def _status_ok(status: str) -> bool:
    """
    Check if an HTTP status indicates success (2xx).
    
    Args:
        status: HTTP status line (e.g., "HTTP/1.1 200 OK")
        
    Returns:
        True if status code is in the 2xx range
    """
    try:
        parts = status.split(" ")
        if len(parts) < 2:
            logger.error(f"Malformed status line: {status!r} (expected at least 2 parts)", extra={"tag": "http"})
            return False
        status_code = int(parts[1])
        return 200 <= status_code < 300
    except (ValueError, IndexError) as e:
        logger.error(f"Failed to parse status code from {status!r}: {e}", extra={"tag": "http"})
        return False


def streaming_response_is_ok(
    response: OkStreamingResponse[T] | ErrStreamingResponse,
) -> TypeIs[OkStreamingResponse[T]]:
    """
    Type guard for checking if a streaming response is successful.
    
    This function serves as a type guard in Python's type system, narrowing
    the type of `response` to `OkStreamingResponse[T]` when it returns True.
    
    Example:
        >>> async def main():
        ...     client = HttpClient()
        ...     response = await client.stream_get("https://httpbin.org/stream/1")
        ...     if streaming_response_is_ok(response):
        ...         # Here response is known to be OkStreamingResponse[T]
        ...         async for item in response.body:
        ...             print(item)
        ...     else:
        ...         # Here response is known to be ErrStreamingResponse
        ...         print(f"Error: {response.status}")
    
    Args:
        response: The streaming response to check
        
    Returns:
        True if the response is successful (i.e., an OkStreamingResponse)
    """
    return _status_ok(response.status)


class HTTPException(Exception):
    """
    Exception raised for HTTP errors.
    
    This exception includes the HTTP status and body for detailed error reporting.
    """
    def __init__(self, status: str, message: str | bytes):
        super().__init__(self, f"Status: {status}\nBody: {message}")


class HttpClient:
    """
    HTTP client compatible with Flowno's event loop.
    
    This client allows making both regular and streaming HTTP requests.
    It supports custom headers, JSON serialization, and automatic handling
    of compressed responses.
    
    Example:
        >>> async def main():
        ...     # Create client with custom headers
        ...     headers = Headers()
        ...     headers.set("Authorization", "Bearer my_token")
        ...     client = HttpClient(headers=headers)
        ...     
        ...     # Make a POST request with JSON data
        ...     response = await client.post(
        ...         "https://httpbin.org/post",
        ...         json={"name": "test", "value": 123}
        ...     )
        ...     print(f"Status: {response.status_code}")
    """
    def __init__(self, headers: Headers | None = None):
        """
        Initialize a new HTTP client.
        
        Args:
            headers: Default headers to include in all requests
        """
        self.override_headers: Headers = headers or Headers()
        self.json_decoder: json.JSONDecoder = json.JSONDecoder()
        self.json_encoder: json.JSONEncoder = json.JSONEncoder()
        self._sse_buffer: bytes = b""
        self._json_buffer: str = ""

    async def get(self, url: str) -> Response:
        """
        Make a GET request to the given URL, blocking the current task.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     response = await client.get("https://httpbin.org/get")
            ...     print(f"Status: {response.status_code}")
            ...     print(f"Body: {response.body}")
        
        Args:
            url: The URL to make the request to
        
        Returns:
            Response object containing status, headers, and body
        """
        return await self.request("GET", url)

    async def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
        data: bytes | None = None,
    ) -> Response:
        """
        Make a POST request to the given URL.
        
        If `json` is provided, it will be serialized with the client's JSON encoder
        and sent as the request body with the appropriate Content-Type header.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     response = await client.post(
            ...         "https://httpbin.org/post",
            ...         json={"name": "test", "value": 123}
            ...     )
            ...     print(f"Status: {response.status_code}")
        
        Args:
            url: The URL to make the request to
            json: JSON data to send (will be encoded using the client's JSON encoder)
            data: Raw data to send (used only if json is None)
        
        Returns:
            Response object containing status, headers, and body
        """
        headers = Headers()
        if json is not None:
            data = self.json_encoder.encode(json).encode(encoding="utf-8")
            headers.set("Content-Type", "application/json")
        return await self.request("POST", url, data, headers)

    async def stream_get(
        self, url: str
    ) -> OkStreamingResponse[Any] | ErrStreamingResponse:  # pyright: ignore[reportExplicitAny]
        """
        Make a streaming GET request to the given URL.
        
        This method returns a response with a body that is an asynchronous iterator,
        allowing for processing of response data as it arrives.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     response = await client.stream_get("https://httpbin.org/stream/3")
            ...     
            ...     if streaming_response_is_ok(response):
            ...         async for chunk in response.body:
            ...             print(chunk)
        
        Args:
            url: The URL to make the request to
        
        Returns:
            A streaming response object that may be either successful or an error
        """
        return await self.stream_request("GET", url)

    async def stream_post(
        self,
        url: str,
        json: dict[str, Any] | Any | None = None,  # pyright: ignore[reportExplicitAny]
        data: bytes | None = None,
    ) -> OkStreamingResponse[Any] | ErrStreamingResponse:  # pyright: ignore[reportExplicitAny]
        """
        Make a streaming POST request to the given URL.
        
        If `json` is provided, it will be serialized with the client's JSON encoder
        and sent as the request body with the appropriate Content-Type header.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     response = await client.stream_post(
            ...         "https://httpbin.org/stream/3",
            ...         json={"key": "value"}
            ...     )
            ...     
            ...     if streaming_response_is_ok(response):
            ...         async for chunk in response.body:
            ...             print(chunk)
        
        Args:
            url: The URL to make the request to
            json: JSON data to send (will be encoded using the client's JSON encoder)
            data: Raw data to send (used only if json is None)
        
        Returns:
            A streaming response object that may be either successful or an error
        """
        headers = Headers()
        if json is not None:
            data = self.json_encoder.encode(json).encode(encoding="utf-8")
            headers.set("Content-Type", "application/json")
        return await self.stream_request("POST", url, data, headers)

    def _parse_url(self, url: str) -> tuple[str, int, str, bool]:
        """
        Parse a URL into components needed for making a request.
        
        Args:
            url: The URL to parse
            
        Returns:
            Tuple of (host, port, path, use_tls)
        """
        parsed_url = urlparse(url)
        host = parsed_url.hostname or "localhost"
        if parsed_url.scheme == "https":
            port = 443
            use_tls = True
        else:
            port = 80
            use_tls = False
        port = parsed_url.port or port
        path = parsed_url.path or "/"

        return host, port, path, use_tls

    async def _receive_headers(self, sock: SocketHandle) -> tuple[str, Headers, bytes]:
        """
        Receive HTTP headers from a socket.
        
        This method reads from the socket until it encounters the end of headers marker
        (double CRLF), then parses the headers and returns them along with any body data
        that may have been included in the same read.
        
        Args:
            sock: The socket to read from
            
        Returns:
            Tuple of (status_line, headers, initial_body_data)
        """
        headers = Headers()
        data = b""
        while True:
            chunk = await sock.recv(1024)
            logger.debug(f"Received chunk: {chunk!r}", extra={"tag": "http"})
            if not chunk:
                logger.warning("Socket closed before headers received", extra={"tag": "http"})
                break
            data += chunk
            if b"\r\n\r\n" in data:
                break
        
        logger.debug(f"Total data received: {len(data)} bytes", extra={"tag": "http"})
        
        split_data = data.split(b"\r\n\r\n", 1)
        if len(split_data) == 2:
            headers_data, initial_body = split_data
        else:
            headers_data = split_data[0]
            initial_body = b""
        
        try:
            lines = headers_data.decode("utf-8").split("\r\n")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode headers data: {e}", extra={"tag": "http"})
            logger.error(f"Raw headers data: {headers_data!r}", extra={"tag": "http"})
            raise
        
        if not lines:
            logger.error("No lines in headers data", extra={"tag": "http"})
            return "", headers, initial_body
        
        status = lines[0]
        logger.debug(f"Parsed status line: {status!r}", extra={"tag": "http"})
        
        for line in lines[1:]:
            try:
                name, value = line.split(": ", 1)
                headers.set(name, value)
            except ValueError:
                continue
        
        logger.debug(f"Parsed {len(headers._headers)} headers", extra={"tag": "http"})
        return status, headers, initial_body

    async def request(
        self,
        method: Literal["GET", "POST"],
        url: str,
        data: bytes | None = None,
        extra_headers: Headers | None = None,
    ) -> Response:
        """
        Make a request to the given URL.
        
        This is the core method that handles both GET and POST requests.
        It handles the entire request-response cycle, including connecting,
        sending the request, receiving the response, and decompressing the body.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     headers = Headers()
            ...     headers.set("Accept", "application/json")
            ...     response = await client.request(
            ...         "GET", 
            ...         "https://httpbin.org/get",
            ...         extra_headers=headers
            ...     )
            ...     print(f"Status: {response.status}")
        
        Args:
            method: The HTTP method to use ("GET" or "POST")
            url: The URL to make the request to
            data: The data to send in the request body
            extra_headers: Additional headers to include in the request
            
        Returns:
            Response object containing status, headers, and body
        """
        # Parse the URL
        host, port, path, use_tls = self._parse_url(url)

        # Create a socket
        sock = socket(use_tls=use_tls, server_hostname=host)
        sock.connect((host, port))

        request = f"{method} {path} HTTP/1.1\r\n"
        request = request.encode("utf-8")

        headers = Headers()
        if data is not None:
            headers.set("Content-Length", str(len(data)))

        headers.set("Host", host)
        headers.set("User-Agent", "Flowno/0.1")
        headers.set("Accept-Encoding", ["gzip", "deflate"])
        headers.set("Connection", "close")
        if extra_headers is not None:
            headers.merge(extra_headers)
        headers.merge(self.override_headers)
        request += headers.stringify().encode("utf-8") + b"\r\n\r\n" + (data or b"")

        sent = await sock.send(request)
        assert sent == len(request), f"Sent {sent} bytes, expected {len(request)}"

        status, response_headers, initial_body = await self._receive_headers(sock)
        body = await self._receive_remainder(sock, initial_body, response_headers)
        assert isinstance(body, bytes), f"Expected bytes, got {type(body)}"

        logger.debug(f"Request complete with status: {status!r}", extra={"tag": "http"})
        decompressed_body = self._decompress_body(body, response_headers)
        return Response(self, status, response_headers, decompressed_body)

    async def stream_request(
        self,
        method: Literal["GET", "POST"],
        url: str,
        data: bytes | None = None,
        extra_headers: Headers | None = None,
    ) -> OkStreamingResponse[Any] | ErrStreamingResponse:  # pyright: ignore[reportExplicitAny]
        """
        Make a streaming request to the given URL.
        
        This method is similar to `request()` but returns a streaming response.
        For successful responses, the body is an asynchronous iterator that yields
        either parsed JSON objects (for SSE streams) or raw bytes.
        
        Example:
            >>> async def main():
            ...     client = HttpClient()
            ...     response = await client.stream_request(
            ...         "GET", 
            ...         "https://httpbin.org/stream/3"
            ...     )
            ...     
            ...     if streaming_response_is_ok(response):
            ...         async for chunk in response.body:
            ...             print(f"Received chunk: {chunk}")
        
        Args:
            method: The HTTP method to use ("GET" or "POST")
            url: The URL to make the request to
            data: The data to send in the request body
            extra_headers: Additional headers to include in the request
            
        Returns:
            A streaming response object that may be either successful or an error
        """
        host, port, path, use_tls = self._parse_url(url)
        sock = socket(use_tls=use_tls, server_hostname=host)
        sock.connect((host, port))

        request = f"{method} {path} HTTP/1.1\r\n"
        request = request.encode("utf-8")

        headers = Headers()
        if data is not None:
            headers.set("Content-Length", str(len(data)))

        headers.set("Host", host)
        headers.set("User-Agent", "Flowno/0.1")
        headers.set("Accept-Encoding", ["gzip", "deflate"])
        headers.set("Connection", "close")
        if extra_headers is not None:
            headers.merge(extra_headers)
        headers.merge(self.override_headers)
        request += headers.stringify().encode("utf-8") + b"\r\n\r\n" + (data or b"")

        sent = await sock.send(request)
        assert sent == len(request), f"Sent {sent} bytes, expected {len(request)}"

        status, response_headers, initial_body = await self._receive_headers(sock)

        async def body_generator():
            body = self._stream_read(sock, initial_body)

            # each chunk yielded by _stream_read is a contains one or more `message lines`
            # message lines are separated by `\r\ndata: ` and are grouped into messages by `\n\n` or `\r\n` depending on the implementation
            # chunks may contain multiple messages, and messages may be split across chunks
            # I'm going to assume messages are json, except for '[DONE]' which is a pointless signal to close the connection
            # I can't split chunks into lines with `\r\ndata: ` because the json content may contain that string
            # Instead I will json raw_decode messages then yield them until I receive a message that is just '[DONE]' or chunk size 0

            async for chunk in body:
                decompressed_chunk = self._decompress_chunk(chunk, response_headers)
                content_type = response_headers.get("Content-Type")
                if isinstance(content_type, str) and content_type.startswith("text/event-stream"):
                    for message in self._split_chunks_to_message_json(decompressed_chunk):
                        yield message
                else:
                    yield decompressed_chunk

        logger.debug(f"Checking status for streaming response: {status!r}", extra={"tag": "http"})
        if _status_ok(status):
            logger.debug("Status OK, returning OkStreamingResponse", extra={"tag": "http"})
            return OkStreamingResponse(
                self,
                status=status,
                headers=response_headers,
                body=body_generator(),
            )
        else:
            logger.warning(f"Status not OK: {status!r}", extra={"tag": "http"})
            body_result = await self._receive_remainder(sock, initial_body, response_headers)

            if isinstance(body_result, AsyncGenerator):
                # Chunked error response - return streaming body with decompression
                async def error_body_generator():
                    async for chunk in body_result:
                        decompressed = self._decompress_chunk(chunk, response_headers)
                        yield decompressed

                return ErrStreamingResponse(
                    self,
                    status=status,
                    headers=response_headers,
                    body=error_body_generator(),
                )
            else:
                # Complete error response - return bytes
                decompressed_body = self._decompress_body(body_result, response_headers)
                return ErrStreamingResponse(
                    self,
                    status=status,
                    headers=response_headers,
                    body=decompressed_body,
                )

    def _split_chunks_to_message_json(self, chunk: bytes) -> Generator[Any, None, None]:
        """
        Split SSE chunks into JSON objects.
        
        This method processes Server-Sent Events (SSE) data, extracting and parsing
        JSON objects from the data fields.
        
        Args:
            chunk: Raw bytes from the SSE stream
            
        Yields:
            Parsed JSON objects from the SSE stream
        """
        self._sse_buffer += chunk

        # Match both \r\n\r\n and \n\n as delimiters
        pattern = re.compile(rb"(\r\n\r\n|\n\n)")

        while True:
            match = pattern.search(self._sse_buffer)
            if not match:
                break  # Exit if no complete message is found

            event_bytes, self._sse_buffer = self._sse_buffer.split(match.group(0), 1)
            event = event_bytes.decode("utf-8", errors="replace")

            if not event.startswith("data: "):
                continue

            json_str = event[len("data: "):].strip()
            if json_str == "[DONE]":
                break

            # Buffering for incomplete JSON
            self._json_buffer += json_str

            while self._json_buffer:
                try:
                    message, idx = self.json_decoder.raw_decode(self._json_buffer)
                    yield message
                    self._json_buffer = self._json_buffer[idx:].lstrip()
                except json.JSONDecodeError as e:
                    if e.pos == len(self._json_buffer):
                        # Incomplete JSON, keep accumulating
                        break
                    logger.error(f"Error decoding JSON: {repr(self._json_buffer)}")
                    raise

    def _decompress_chunk(self, chunk: bytes, headers: Headers) -> bytes:
        """
        Decompress a chunk of data based on Content-Encoding header.
        
        Args:
            chunk: The data to decompress
            headers: Response headers containing Content-Encoding
            
        Returns:
            Decompressed data or the original chunk if no compression was used
        """
        encoding = headers.get("Content-Encoding")
        if encoding == "gzip":
            return gzip.decompress(chunk)
        elif encoding == "deflate":
            return zlib.decompress(chunk)
        return chunk

    def _decompress_body(self, body: bytes, headers: Headers) -> bytes:
        """
        Decompress an entire response body based on Content-Encoding header.
        
        Args:
            body: The data to decompress
            headers: Response headers containing Content-Encoding
            
        Returns:
            Decompressed body or the original body if no compression was used
        """
        encoding = headers.get("Content-Encoding")
        if encoding == "gzip":
            return zlib.decompress(body, 16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            return zlib.decompress(body)
        return body

    async def _receive_remainder(
        self, sock: SocketHandle, initial_body: bytes, headers: Headers
    ) -> bytes | AsyncGenerator[bytes, None]:
        """
        Receive the remaining response body after headers.

        This method handles both fixed-length and chunked responses.

        Args:
            sock: The socket to read from
            initial_body: Any body data that was read with the headers
            headers: Response headers

        Returns:
            Complete response body for fixed-length responses,
            or a generator for chunked responses
        """
        body = initial_body
        content_length = headers.get("Content-Length")
        is_chunked = headers.get("Transfer-Encoding") == "chunked"

        if is_chunked:
            return self._stream_read(sock, initial_body)
        elif content_length:
            # Handle Content-Length specified responses
            assert isinstance(content_length, str), "Content-length header is not a string"
            content_length = int(content_length)
            body_length = len(body)
            while body_length < content_length:
                remaining_chunk = await sock.recv(1024)
                if not remaining_chunk:
                    break
                body += remaining_chunk
                body_length += len(remaining_chunk)
            return body
        else:
            # Handle responses without Content-Length header
            # According to HTTP/1.1, we should read until connection closes
            while True:
                remaining_chunk = await sock.recv(1024)
                if not remaining_chunk:
                    break
                body += remaining_chunk
            return body

    async def _stream_read(self, sock: SocketHandle, initial_body: bytes) -> AsyncGenerator[bytes, None]:
        # content-length is ignored if transfer-encoding is chunked
        # we need to start reading chunks from initial body then continuing to read from socket
        # the initial may be empty and may or may not contain a complete number of chunks.
        # if the header size is just unlucky the first chunk may be split or even the size of the chunk may be split
        # none of this considers intentional bad or weird responses from the server
        # TODO: adversarial testing
        # run in a loop, yielding chunks until the server closes the connection

        head = initial_body
        self._sse_buffer = b""

        while True:
            trailing = await sock.recv(1024)
            if trailing == b"":  # server closed connection
                break
            head += trailing

            # head must now contain at least one byte
            while b"\r\n" not in head:
                # the first time \r\n is found, it must be immediately after the chunk size
                trailing = await sock.recv(1024)
                if trailing == b"":
                    raise Exception("Server closed connection before sending chunk size")
                head += trailing
                
            chunk_size_hex, body = head.split(b"\r\n", 1)
            if chunk_size_hex == b"":
                break
            chunk_size = int(chunk_size_hex, 16)

            while chunk_size > len(body):
                remaining_chunk = await sock.recv(chunk_size - len(body))
                if remaining_chunk == b"":
                    raise Exception("Server closed connection before sending full chunk")
                body += remaining_chunk

            complete_chunk = body[:chunk_size]
            yield complete_chunk
            head = body[chunk_size:]

            while not head.startswith(b"\r\n"):
                trailing = await sock.recv(1024)
                if trailing == b"":
                    raise Exception("Server closed connection before sending chunk terminator")
                head += trailing
            head = head[2:]  # remove the terminator
            # now head should be empty or contain the start of the next chunk

    async def _receive_all(self, sock: SocketHandle) -> bytes:
        """
        Receive all data from a socket until connection closes.
        
        Args:
            sock: The socket to read from
            
        Returns:
            All data received from the socket
        """
        data = b""
        while True:
            chunk = await sock.recv(1024)
            if not chunk:
                break
            data += chunk
        return data