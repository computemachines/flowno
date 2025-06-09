import socket as _socket
import timeit

import pytest
from flowno import Flow, node, sleep, socket, spawn
from flowno.core.event_loop.selectors import SocketHandle
from flowno.io.http_client import HttpClient
from flowno.utilities.logging import log_async


@pytest.fixture
def available_port():
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def test_braindead():
    log: list[str] = []

    @node
    @log_async
    async def main():
        log.append("main start")
        log.append("main end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "main end"]


def test_spawn():
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        _ = await spawn(task1())
        log.append("main end")

    async def task1():
        log.append("task1 start")
        _ = await spawn(task2())
        log.append("task1 end")

    async def task2():
        log.append("task2 start")
        log.append("task2 end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "task1 start", "main end", "task2 start", "task2 end", "task1 end"]


def test_join():
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        t = await spawn(task1())
        await t.join()
        log.append("main end")

    async def task1():
        log.append("task1 start")
        _ = await spawn(task2())
        log.append("task1 end")

    async def task2():
        log.append("task2 start")
        log.append("task2 end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "task1 start", "task2 start", "task2 end", "task1 end", "main end"]


def test_join_return():
    @node
    async def main():
        t = await spawn(foo())
        result = await t.join()
        assert result == 42

    async def foo():
        return 42

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete()


# Demonstrate the use of event_loop.sleep and the event_loop.spawn/join awaitables
def test_sleep():
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        t = await spawn(foo())
        actual = await sleep(0.1)
        assert 0.1 <= actual <= 0.16
        await t.join()
        log.append("main end")

    async def foo():
        log.append("foo start")
        actual = await sleep(0.05)
        assert 0.05 <= actual <= 0.08
        log.append("foo end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []

    duration = timeit.timeit(lambda: flow.run_until_complete(), number=1)
    assert 0.1 <= duration <= 0.16
    print(f"Execution time: {duration} seconds")
    assert log == ["main start", "foo start", "foo end", "main end"]


def test_socket():
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        t1 = await spawn(server())
        t2 = await spawn(client())

        await t1.join()
        await t2.join()
        log.append("main end")

    async def server():
        log.append("server start")
        sock: SocketHandle = socket()
        sock.bind(("localhost", 12345))
        sock.listen()
        conn, _ = await sock.accept()
        log.append("server end")

    async def client():
        log.append("client start")
        sock = socket()
        sock.connect(("localhost", 12345))
        log.append("client end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "server start", "client start", "client end", "server end", "main end"]


def test_read_recv(available_port):
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        t1 = await spawn(server())
        await sleep(0.1)
        t2 = await spawn(client())

        await t1.join()
        await t2.join()
        log.append("main end")

    async def server():
        sock = socket()
        sock.bind(("localhost", available_port))
        sock.listen()
        log.append("server start")
        conn, _ = await sock.accept()
        data = await conn.recv(1024)
        assert data == b"hello"
        log.append("server end")

    async def client():
        log.append("client start")
        sock = socket()
        sock.connect(("localhost", available_port))
        _ = await sock.send(b"hello")
        log.append("client end")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "server start", "client start", "client end", "server end", "main end"]


class DummyException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def test_exception_handling():
    log: list[str] = []

    @node
    async def main():
        log.append("main start")
        task = await spawn(foo())
        try:
            result = await task.join()
        except DummyException as e:
            log.append(f"Caught exception: {e.message}")
        else:
            log.append(f"Result: {result}")
        log.append("main end")

    async def foo():
        log.append("foo start")
        raise DummyException("Something went wrong")
        log.append("foo end")  # pyright: ignore[reportUnreachable]

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    assert log == []
    flow.run_until_complete()
    assert log == ["main start", "foo start", "Caught exception: Something went wrong", "main end"]


@pytest.mark.network
def test_tls_socket():
    @node
    async def main():
        sock = socket(use_tls=True, server_hostname="www.example.com")
        sock.connect(("www.example.com", 443))

        _ = await sock.send(b"GET / HTTP/1.1\r\nHost: www.example.com\r\n\r\n")
        response = await sock.recv(1024)

        assert response.startswith(b"HTTP/1.1 200 OK")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete(terminate_on_node_error=True)


@pytest.mark.network
def test_recv_zero_bytes():
    @node
    async def main():
        sock = socket(use_tls=True, server_hostname="www.example.com")
        sock.connect(("www.example.com", 443))

        _ = await sock.send(b"GET / HTTP/1.1\r\nHost: www.example.com\r\n\r\n")
        response = await sock.recv(0)

        assert response == b""

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete(terminate_on_node_error=True)


@pytest.mark.network
def test_recv_double():
    @node
    async def main():
        sock = socket(use_tls=True, server_hostname="www.example.com")
        sock.connect(("www.example.com", 443))

        _ = await sock.send(b"GET / HTTP/1.1\r\nHost: www.example.com\r\nConnection: close\r\n\r\n")
        response = await sock.recv(10024)
        response += await sock.recv(10024)
        response += await sock.recv(10024)
        response += await sock.recv(10024)
        response += await sock.recv(10024)

        assert response.startswith(b"HTTP/1.1 200 OK")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete(terminate_on_node_error=True)


@pytest.mark.network
def test_http_get():
    @node
    async def main():
        client = HttpClient()
        response = await client.get("http://www.example.com")
        assert response.is_ok

        assert response.body.startswith(b"<!doctype html>")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete(terminate_on_node_error=True)


@pytest.mark.network
def test_http_get_https():
    @node
    async def main():
        client = HttpClient()
        response = await client.get("https://www.example.com")
        assert response.is_ok
        assert response.body.startswith(b"<!doctype html>")

    flow = Flow()
    flow.add_node(main()._blank_finalized())
    flow.run_until_complete(terminate_on_node_error=True)
