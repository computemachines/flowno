"""
HTTP traffic logging for diagnosing server issues.

Provides HttpLoggingInstrument that plugs into flowno's instrumentation system
to log socket-level I/O alongside HTTP protocol events. This enables diagnosis
of issues with non-compliant HTTP servers, such as:

- Chunk size mismatches in chunked transfer encoding
- Missing or malformed SSE events
- JSON parse failures in streaming responses
- Premature connection closes
- Latency anomalies

Usage:
    Set FLOWNO_HTTP_LOG environment variable to a file path to enable logging:

        export FLOWNO_HTTP_LOG=/tmp/http-traffic.log

    Then use the instrument:

        from flowno.io.http_logging import get_http_logging_instrument

        instrument = get_http_logging_instrument()
        if instrument:
            with instrument:
                # HTTP operations will be logged
                ...
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from time import time
from types import TracebackType
from typing import TYPE_CHECKING

from typing_extensions import Self, override

from flowno.core.event_loop.instrumentation import (
    EventLoopInstrument,
    ReadySocketInstrumentationMetadata,
    SocketConnectReadyMetadata,
    SocketConnectStartMetadata,
    SocketRecvDataMetadata,
    SocketSendDataMetadata,
    TLSHandshakeMetadata,
)

if TYPE_CHECKING:
    from flowno.core.event_loop.selectors import SocketHandle

# Dedicated context var for HttpLoggingInstrument lookup
_current_http_logger: ContextVar["HttpLoggingInstrument | None"] = ContextVar(
    "_current_http_logger", default=None
)


@dataclass
class ConnectionState:
    """Tracks state for a single HTTP connection."""

    conn_id: str
    host: str
    port: int
    tls: bool = False
    start_time: float = field(default_factory=time)
    total_bytes_recv: int = 0
    total_bytes_sent: int = 0
    recv_count: int = 0
    send_count: int = 0
    last_recv_time: float = field(default_factory=time)
    last_send_time: float = field(default_factory=time)


class HttpLoggingInstrument(EventLoopInstrument):
    """
    Instrument that logs socket I/O for HTTP traffic analysis.

    Tracks connections by socket file descriptor and logs:
    - Connection establishment (with TLS details if applicable)
    - Every send/recv with byte counts and timing
    - Cumulative statistics per connection

    Log format:
        [timestamp] [conn_id] EVENT key=value ...

    Example:
        [2026-01-08T10:58:26.548] [conn-0001] CONNECT host=api.openai.com port=443
        [2026-01-08T10:58:26.549] [conn-0001] TLS version=TLSv1.3 cipher=...
        [2026-01-08T10:58:26.550] [conn-0001] SEND bytes=1234
        [2026-01-08T10:58:26.712] [conn-0001] RECV bytes=128 total=128 latency_ms=162
    """

    _http_token: Token["HttpLoggingInstrument | None"] | None = None

    def __init__(self, logger: logging.Logger | None = None):
        """
        Initialize the HTTP logging instrument.

        Args:
            logger: Logger to use. If None, creates one named "flowno.http_traffic"
                with propagate=False to avoid duplicating logs to parent handlers.
        """
        if logger is None:
            logger = logging.getLogger("flowno.http_traffic")
            logger.propagate = False
        self._logger = logger
        self._connections: dict[int, ConnectionState] = {}  # fd -> state
        self._pending_connects: dict[int, SocketConnectStartMetadata] = {}  # fd -> start metadata
        self._conn_counter = 0

    def __enter__(self: Self) -> Self:
        # Register in the instrument stack (for socket-level events)
        super().__enter__()
        # Also set our dedicated context var (for HttpClient lookup)
        self._http_token = _current_http_logger.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if self._http_token is not None:
            _current_http_logger.reset(self._http_token)
        return super().__exit__(exc_type, exc_val, exc_tb)

    def _get_fd(self, sock_handle: SocketHandle) -> int:
        """Get file descriptor from socket handle."""
        return sock_handle.socket.fileno()

    def _get_conn(self, sock_handle: SocketHandle) -> ConnectionState | None:
        """Get connection state for a socket."""
        fd = self._get_fd(sock_handle)
        return self._connections.get(fd)

    def _generate_conn_id(self) -> str:
        """Generate a unique connection ID."""
        self._conn_counter += 1
        return f"conn-{self._conn_counter:04d}"

    def _log(self, conn_id: str, event: str, **kwargs: object) -> None:
        """Log an event with structured key=value pairs."""
        parts = [f"{k}={v}" for k, v in kwargs.items()]
        self._logger.info(f"[{conn_id}] {event} {' '.join(parts)}")

    # === Socket-level instrumentation hooks ===

    @override
    def on_socket_connect_start(self, metadata: SocketConnectStartMetadata) -> None:
        """Record when a connection attempt starts."""
        fd = self._get_fd(metadata.socket_handle)
        self._pending_connects[fd] = metadata

    @override
    def on_socket_connect_ready(self, metadata: SocketConnectReadyMetadata) -> None:
        """Log successful connection establishment."""
        fd = self._get_fd(metadata.socket_handle)
        host, port = metadata.target_address

        conn_id = self._generate_conn_id()
        state = ConnectionState(
            conn_id=conn_id,
            host=str(host),
            port=int(port),
            start_time=metadata.start_time,
        )
        self._connections[fd] = state

        latency_ms = (metadata.finish_time - metadata.start_time) * 1000
        self._log(conn_id, "CONNECT", host=host, port=port, latency_ms=f"{latency_ms:.1f}")

        # Clean up pending
        self._pending_connects.pop(fd, None)

    @override
    def on_tls_handshake_complete(self, metadata: TLSHandshakeMetadata) -> None:
        """Log TLS handshake completion with cipher details."""
        conn = self._get_conn(metadata.socket_handle)
        if not conn:
            return

        conn.tls = True
        latency_ms = (metadata.finish_time - metadata.start_time) * 1000

        cipher_name = metadata.cipher[0] if metadata.cipher else "unknown"
        self._log(
            conn.conn_id,
            "TLS",
            version=metadata.version or "unknown",
            cipher=cipher_name,
            hostname=metadata.server_hostname or "none",
            latency_ms=f"{latency_ms:.1f}",
        )

    @override
    def on_socket_recv_data(self, metadata: SocketRecvDataMetadata) -> None:
        """Log received data with byte count and timing."""
        conn = self._get_conn(metadata.socket_handle)
        if not conn:
            return

        now = time()
        bytes_recv = len(metadata.data)
        conn.recv_count += 1
        conn.total_bytes_recv += bytes_recv

        latency_ms = (now - conn.last_recv_time) * 1000
        conn.last_recv_time = now

        self._log(
            conn.conn_id,
            "RECV",
            seq=conn.recv_count,
            bytes=bytes_recv,
            total=conn.total_bytes_recv,
            latency_ms=f"{latency_ms:.1f}",
        )

    @override
    def on_socket_send_data(self, metadata: SocketSendDataMetadata) -> None:
        """Log sent data with byte count."""
        conn = self._get_conn(metadata.socket_handle)
        if not conn:
            return

        now = time()
        conn.send_count += 1
        conn.total_bytes_sent += metadata.bytes_sent

        latency_ms = (now - conn.last_send_time) * 1000
        conn.last_send_time = now

        self._log(
            conn.conn_id,
            "SEND",
            seq=conn.send_count,
            bytes=metadata.bytes_sent,
            total=conn.total_bytes_sent,
            latency_ms=f"{latency_ms:.1f}",
        )

    @override
    def on_socket_recv_ready(self, metadata: ReadySocketInstrumentationMetadata) -> None:
        """Log when socket becomes ready to receive (selector wakeup)."""
        conn = self._get_conn(metadata.socket_handle)
        if not conn:
            return

        wait_ms = (metadata.finish_time - metadata.start_time) * 1000
        if wait_ms > 100:  # Only log significant waits
            self._log(conn.conn_id, "RECV_READY", wait_ms=f"{wait_ms:.1f}")

    # === HTTP protocol-level logging methods ===
    # These are called directly from http_client.py

    def log_request(self, conn_id: str, method: str, url: str, body_len: int) -> None:
        """Log an HTTP request being sent."""
        self._log(conn_id, "REQUEST", method=method, url=url, body_len=body_len)

    def log_response_headers(
        self,
        conn_id: str,
        status: int,
        content_type: str | None,
        transfer_encoding: str | None,
        content_length: int | None,
    ) -> None:
        """Log HTTP response headers received."""
        kwargs: dict[str, object] = {"status": status}
        if content_type:
            kwargs["content_type"] = content_type
        if transfer_encoding:
            kwargs["transfer_encoding"] = transfer_encoding
        if content_length is not None:
            kwargs["content_length"] = content_length
        self._log(conn_id, "HEADERS", **kwargs)

    def log_chunk(self, conn_id: str, seq: int, declared: int, actual: int) -> None:
        """Log a chunked transfer encoding chunk."""
        kwargs: dict[str, object] = {"seq": seq, "declared": declared, "actual": actual}
        if declared != actual:
            kwargs["MISMATCH"] = True
        self._log(conn_id, "CHUNK", **kwargs)

    def log_sse_event(
        self, conn_id: str, seq: int, data_len: int, parse_ok: bool, done: bool = False
    ) -> None:
        """Log an SSE event parsed from the stream."""
        kwargs: dict[str, object] = {"seq": seq, "len": data_len, "parse": "ok" if parse_ok else "FAIL"}
        if done:
            kwargs["done"] = True
        self._log(conn_id, "SSE", **kwargs)

    def log_json_parse(
        self, conn_id: str, seq: int, json_len: int, ok: bool, error: str | None = None
    ) -> None:
        """Log a JSON parse attempt from SSE data."""
        kwargs: dict[str, object] = {"seq": seq, "len": json_len, "ok": ok}
        if error:
            kwargs["error"] = error
        self._log(conn_id, "JSON", **kwargs)

    def log_stream_end(
        self,
        conn_id: str,
        total_bytes: int,
        chunks: int,
        sse_events: int,
        duration_ms: float,
        done_received: bool,
    ) -> None:
        """Log the end of a streaming response."""
        self._log(
            conn_id,
            "END",
            total_bytes=total_bytes,
            chunks=chunks,
            sse=sse_events,
            duration_ms=f"{duration_ms:.1f}",
            done=done_received,
        )

    def get_conn_id(self, sock_handle: SocketHandle) -> str | None:
        """Get the connection ID for a socket handle."""
        conn = self._get_conn(sock_handle)
        return conn.conn_id if conn else None

    def get_connection_state(self, sock_handle: SocketHandle) -> ConnectionState | None:
        """Get full connection state for a socket handle."""
        return self._get_conn(sock_handle)


def configure_file_logger(log_path: str) -> logging.Logger:
    """
    Configure a file logger for HTTP traffic.

    Args:
        log_path: Path to the log file.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("flowno.http_traffic")
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers
    if not logger.handlers:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "[%(asctime)s.%(msecs)03d] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_http_logging_instrument() -> HttpLoggingInstrument | None:
    """
    Get an HTTP logging instrument if enabled via environment variable.

    Set FLOWNO_HTTP_LOG to a file path to enable HTTP traffic logging.

    Returns:
        HttpLoggingInstrument if FLOWNO_HTTP_LOG is set, None otherwise.
    """
    log_path = os.environ.get("FLOWNO_HTTP_LOG")
    if log_path:
        logger = configure_file_logger(log_path)
        return HttpLoggingInstrument(logger)
    return None


def get_current_http_logger() -> HttpLoggingInstrument | None:
    """
    Get the current HTTP logging instrument from context, if any.

    This is used by HttpClient to find the active HttpLoggingInstrument
    without requiring it to be passed as a constructor argument.

    Returns:
        The currently active HttpLoggingInstrument, or None if none is active.
    """
    return _current_http_logger.get()


__all__ = [
    "ConnectionState",
    "HttpLoggingInstrument",
    "configure_file_logger",
    "get_current_http_logger",
    "get_http_logging_instrument",
]
