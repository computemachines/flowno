"""
Socket abstraction for the Flowno event loop.

This module provides socket wrappers that integrate with Flowno's event loop system,
enabling non-blocking socket operations through coroutines. The wrappers allow socket
operations to be suspended and resumed by yielding command objects that the event loop
processes.

Key features:
    - Non-blocking socket operations through coroutines
    - Support for both plain and TLS/SSL sockets
    - Integration with Flowno's instrumentation system
    - Compatible with Flowno's event loop commands

Example usage:
    >>> from flowno import socket, spawn, sleep, EventLoop
    >>>
    >>> # Server coroutine
    >>> async def echo_server():
    ...     # Create a server socket
    ...     server_sock = socket()
    ...     server_sock.bind(('localhost', 8888))
    ...     server_sock.listen(1)
    ...     print("Server: Listening on port 8888")
    ...     
    ...     # Accept client connection (non-blocking)
    ...     client_sock, addr = await server_sock.accept()
    ...     print(f"Server: Client connected from {addr}")
    ...     
    ...     # Receive data from client (non-blocking)
    ...     data = await client_sock.recv(1024)
    ...     print(f"Server: Received: {data.decode()}")
    ...     
    ...     # Send response (non-blocking)
    ...     await client_sock.sendAll(b"Echo: " + data)
    ...     print("Server: Response sent")
    >>>
    >>> # Client coroutine
    >>> async def echo_client():
    ...     # Give the server time to start
    ...     await sleep(0.1)
    ...     
    ...     # Create a client socket
    ...     client_sock = socket()
    ...     
    ...     # Connect to server (non-blocking)
    ...     client_sock.connect(('localhost', 8888))
    ...     print("Client: Connected to server")
    ...     
    ...     # Send data (non-blocking)
    ...     message = b"Hello, world!"
    ...     await client_sock.sendAll(message)
    ...     print(f"Client: Sent: {message.decode()}")
    ...     
    ...     # Receive response (non-blocking)
    ...     response = await client_sock.recv(1024)
    ...     print(f"Client: Received: {response.decode()}")
    >>>
    >>> # Main coroutine that coordinates server and client
    >>> async def main():
    ...     # Start the server
    ...     server_task = await spawn(echo_server())
    ...     
    ...     # Start the client
    ...     client_task = await spawn(echo_client())
    ...     
    ...     # Wait for both tasks to complete
    ...     await server_task.join()
    ...     await client_task.join()
    ...     
    ...     print("Main: All tasks completed")
    >>>
    >>> # Run the example
    >>> event_loop = EventLoop()
    >>> event_loop.run_until_complete(main(), join=True)
    Server: Listening on port 8888
    Client: Connected to server
    Client: Sent: Hello, world!
    Server: Client connected from ('127.0.0.1', ...)
    Server: Received: Hello, world!
    Server: Response sent
    Client: Received: Echo: Hello, world!
    Main: All tasks completed
"""

import errno
import os
import selectors
import socket as _socket
import ssl
from collections.abc import Generator
from types import coroutine
from typing import cast

from flowno.core.event_loop.instrumentation import (
    SocketConnectReadyMetadata,
    SocketConnectStartMetadata,
    SocketRecvDataMetadata,
    get_current_instrument,
)
from typing_extensions import override

from .commands import SocketAcceptCommand, SocketRecvCommand, SocketSendCommand
from .types import _Address

#: Default selector used by the event loop for socket operations.
#: This selector efficiently monitors multiple socket objects for I/O events.
sel = selectors.DefaultSelector()


# TODO: change this to subclass of _socket.socket
class SocketHandle:
    """
    Wrapper around the built-in socket object.
    
    This class provides methods that integrate with Flowno's event loop,
    allowing socket operations to be performed asynchronously.
    """

    def __init__(self, socket: _socket.socket):
        """
        Initialize a socket handle.
        
        Args:
            socket: The underlying Python socket object to wrap.
        """
        self.socket = socket

    def connect(self, address: _Address, /) -> None:
        """
        Connect to a remote socket at the specified address.
        
        This is a blocking operation. For non-blocking connections, use the socket
        primitives from the flowno module.
        
        Args:
            address: The address to connect to (host, port).
        """
        metadata = SocketConnectStartMetadata(socket_handle=self, immediate=True, target_address=address)
        get_current_instrument().on_socket_connect_start(metadata)
        self.socket.connect(address)
        get_current_instrument().on_socket_connect_ready(
            SocketConnectReadyMetadata.from_instrumentation_metadata(metadata)
        )

    def bind(self, address: _Address, /) -> None:
        """
        Bind the socket to the specified address.
        
        Args:
            address: The address (host, port) to bind to.
        """
        self.socket.bind(address)

    def listen(self, backlog: int | None = None, /) -> None:
        """
        Enable a server socket to accept connections.
        
        Args:
            backlog: The number of unaccepted connections the system will allow 
                    before refusing new connections.
        """
        if backlog is None:
            self.socket.listen()
        else:
            self.socket.listen(backlog)

    @coroutine
    def accept(
        self,
    ) -> Generator[SocketAcceptCommand, None, tuple["SocketHandle", _Address]]:
        """
        Accept a connection on a listening socket.
        
        This coroutine yields a SocketAcceptCommand for the event loop to process.
        When the event loop detects an incoming connection, it resumes this coroutine.
        
        Returns:
            A tuple containing a new SocketHandle for the client connection and 
            the client's address.
        """
        yield SocketAcceptCommand(self)
        # reenter when the socket is ready to accept a connection
        conn, address = self.socket.accept()  # pyright: ignore[reportAny]
        address = cast(_Address, address)
        conn.setblocking(False)
        return SocketHandle(conn), address

    @coroutine
    def sendAll(self, data: bytes) -> Generator[SocketSendCommand, None, None]:
        """
        Send all data to the socket.
        
        This coroutine continues yielding SocketSendCommand until all data is sent.
        
        Args:
            data: The bytes to send.
        """
        while data:
            yield SocketSendCommand(self)
            sent = self.socket.send(data)
            data = data[sent:]

    @coroutine
    def send(self, data: bytes) -> Generator[SocketSendCommand, None, int]:
        """
        Send data to the socket.
        
        Unlike sendAll, this sends data once and returns the number of bytes sent.
        
        Args:
            data: The bytes to send.
            
        Returns:
            The number of bytes sent.
        """
        yield SocketSendCommand(self)
        return self.socket.send(data)

    @coroutine
    def recv(self, bufsize: int) -> Generator[SocketRecvCommand, None, bytes]:
        """
        Receive data from the socket.
        
        This coroutine yields a SocketRecvCommand for the event loop to process.
        When data is available to read, the event loop resumes this coroutine.
        
        Args:
            bufsize: The maximum number of bytes to receive.
            
        Returns:
            The bytes received from the socket.
        """
        import platform
        
        # On Windows, os.fstat() doesn't work reliably with socket file descriptors
        # (they are not regular file descriptors), so we skip the validity check
        if platform.system() != "Windows":
            try:
                _ = os.fstat(self.socket.fileno())
            except OSError as e:
                if e.errno == errno.EBADF:
                    return b""
                else:
                    raise
        
        yield SocketRecvCommand(self)
        data = self.socket.recv(bufsize)

        get_current_instrument().on_socket_recv_data(SocketRecvDataMetadata(socket_handle=self, data=data))
        return data


class TLSSocketHandle(SocketHandle):
    """
    Wrapper around the built-in ssl socket object.
    
    This class extends SocketHandle to provide TLS/SSL support.
    """

    def __init__(self, socket: _socket.socket, ssl_context: ssl.SSLContext, server_hostname: str | None):
        """
        Initialize a TLS socket handle.
        
        Args:
            socket: The underlying Python socket object to wrap.
            ssl_context: The SSL context to use for the connection.
            server_hostname: The server hostname for SNI (Server Name Indication).
        """
        super().__init__(socket)
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname

    @override
    def connect(self, address: _Address, /) -> None:
        """
        Connect to a remote socket and establish TLS/SSL connection.
        
        Args:
            address: The address to connect to (host, port).
        """
        self.socket.connect(address)
        self.socket = self.ssl_context.wrap_socket(self.socket, server_hostname=self.server_hostname)
        
        
__all__ = [
    "SocketHandle",
    "TLSSocketHandle",
    "sel"
]
