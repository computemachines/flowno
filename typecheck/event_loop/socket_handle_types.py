"""
Exploratory type-checking for event_loop.socket return types.
Confirm correct handle classes based on use_tls flag.
"""

from typing_extensions import assert_type

from flowno import socket
from flowno.core.event_loop.selectors import SocketHandle


def check_socket_handles() -> None:
    default_handle = socket()
    _ = assert_type(default_handle, SocketHandle)

    tls_handle = socket(use_tls=True)
    _ = assert_type(tls_handle, SocketHandle)
