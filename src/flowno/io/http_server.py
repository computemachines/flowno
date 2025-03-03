"""
Simple HTTP server implementation for Flowno applications.

This module provides a basic HTTP server that works with Flowno's event loop.
It's intended for testing, development, and simple use cases, not for production use.

Example:
    Basic HTTP server:
    
    >>> from flowno import EventLoop
    >>> from flowno.io import HttpServer
    >>> 
    >>> async def main():
    ...     server = HttpServer('localhost', 8080)
    ...     await server.serve()  # This will run forever, handling requests
    ... 
    >>> # Run in a separate thread or process since it blocks indefinitely
    >>> loop = EventLoop()
    >>> loop.run_until_complete(main())
"""

import logging
from flowno import socket, SocketHandle, spawn
from flowno.core.event_loop.tasks import TaskHandle
from flowno.io.headers import Headers

logger = logging.getLogger(__name__)


class HttpServer:
    """
    Simple HTTP server compatible with the Flowno event loop.
    
    This is a minimal HTTP server implementation for development and testing.
    For production scenarios, it's recommended to use a dedicated web server
    like Flask or FastAPI in a separate process.
    
    Attributes:
        host: The hostname or IP address to bind to
        port: The port number to listen on
    
    Example:
        >>> from flowno import EventLoop
        >>> from flowno.io import HttpServer
        >>> 
        >>> async def custom_server():
        ...     server = HttpServer('localhost', 8080)
        ...     await server.serve()
        ... 
        >>> loop = EventLoop()
        >>> loop.run_until_complete(custom_server())
    """

    def __init__(self, host: str, port: int):
        """
        Initialize a new HTTP server.
        
        Args:
            host: The hostname or IP address to bind to (e.g., 'localhost' or '0.0.0.0')
            port: The port number to listen on (e.g., 8080)
        """
        self.host = host
        self.port = port

    async def serve(self):
        """
        Start the HTTP server and begin accepting connections.
        
        This method binds to the specified host and port, then enters an infinite loop
        to accept and handle client connections. Each client connection is handled in
        a separate task.
        
        The current task will suspend and other tasks can run concurrently.
        """
        sock = socket()
        logger.info(f"Binding to {self.host}:{self.port}")
        sock.bind((self.host, self.port))
        sock.listen()
        logger.info(f"Server started on {self.host}:{self.port}")

        tasks: list[TaskHandle[None]] = []
        while True:
            client_sock, client_addr = await sock.accept()
            logger.debug(f"Accepted connection from {client_addr}")
            tasks.append(await spawn(self.handle_client(client_sock)))

    async def handle_client(self, client_sock: SocketHandle):
        """
        Handle an individual client connection.
        
        This method reads the client request, processes it, and sends a response.
        
        Args:
            client_sock: The socket connected to the client
        """
        logger.debug("Handling client connection")
        try:
            status, request_headers = await self._receive_headers(client_sock)
            logger.debug(f"Received request: {status}")
            logger.debug(f"Headers: {request_headers}")

            response_data = await self._generate_response(status)

            headers = Headers()
            headers.set("Content-Type", "text/plain")
            headers.set("Content-Length", str(len(response_data)))
            headers.set("Server", "Flowno/0.1")

            # Generate response
            status_line = "HTTP/1.1 200 OK"
            response = status_line + "\r\n" + headers.stringify() + "\r\n\r\n" + response_data.decode()

            await client_sock.sendAll(response.encode())
        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            client_sock.close()

    async def _receive_headers(self, sock: SocketHandle) -> tuple[str, Headers]:
        """
        Receive and parse HTTP headers from a client connection.
        
        This method reads from the socket until it encounters the end of headers marker
        (double CRLF), then parses the headers.
        
        Args:
            sock: The socket to read from
            
        Returns:
            Tuple of (request_line, headers)
        """
        headers = Headers()
        data = b""
        while True:
            chunk = await sock.recv(1024)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                break

        lines = data.decode().split("\r\n")
        status = lines[0]
        for line in lines[1:]:
            if not line:  # Skip empty lines
                continue
            logger.debug(f"Processing header: {line}")
            try:
                name, value = line.split(": ", 1)
                headers.set(name, value)
            except ValueError:
                logger.warning(f"Invalid header format: {line}")
                continue
        return status, headers

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
            logger.debug(f"Received chunk (len={len(chunk)})")
            if not chunk:
                break
            data += chunk
        return data

    async def _generate_response(self, request_data: str) -> bytes:
        """
        Generate a response based on the request.
        
        This is a simple implementation that returns a generic response.
        Override this method in a subclass to provide custom response logic.
        
        Args:
            request_data: The first line of the HTTP request (e.g., "GET / HTTP/1.1")
            
        Returns:
            Response body as bytes
        """
        return f"Hello, world!\nRequest: {request_data}".encode()


__all__ = ["HttpServer"]
