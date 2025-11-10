"""
Custom event loop implementation for Flowno's asynchronous execution model.

This module provides a lightweight, cooperative multitasking event loop that handles:
- Task scheduling and management
- Sleeping/timing operations
- Network socket operations
- Asynchronous queue operations
- Task joining and cancellation

The EventLoop class is the central component of Flowno's asynchronous execution,
implementing a command-based coroutine system similar to Python's asyncio.

This can be used as a standalone event loop without the rest of the Flowno runtime.
"""

from contextvars import ContextVar
import heapq
import logging
import selectors
import signal
import socket
import threading
from collections import defaultdict, deque
from timeit import default_timer as timer
from typing import Any, Literal, TypeVar, cast

from flowno.core.event_loop.commands import (
    Command,
    ExitCommand,
    JoinCommand,
    QueueCloseCommand,
    QueueGetCommand,
    QueueNotifyGettersCommand,
    QueuePutCommand,
    SleepCommand,
    SocketAcceptCommand,
    SocketCommand,
    SocketRecvCommand,
    SocketSendCommand,
    SpawnCommand,
)
from flowno.core.event_loop.instrumentation import (
    InstrumentationMetadata,
    ReadySocketInstrumentationMetadata,
    get_current_instrument,
)
from flowno.core.event_loop.queues import (
    AsyncQueue,
    QueueClosedError,
    TaskWaitingOnQueueGet,
    TaskWaitingOnQueuePut,
)
from flowno.core.event_loop.selectors import sel
from flowno.core.event_loop.tasks import TaskCancelled, TaskHandle
from flowno.core.event_loop.types import (
    DeltaTime,
    RawTask,
    RawTaskPacket,
    TaskHandlePacket,
    Time,
)
from typing_extensions import overload

logger = logging.getLogger(__name__)

_ReturnT = TypeVar("_ReturnT")

_current_task: ContextVar[RawTask[Command, Any, Any] | None] = ContextVar("_current_task", default=None)

def current_task() -> RawTask[Command, Any, Any] | None:
    """
    Get the currently executing task in the event loop.
    
    Returns:
        The currently executing task, or None if called outside a task context.
    """
    return _current_task.get()

_current_event_loop: "EventLoop | None" = None

def current_event_loop() -> "EventLoop | None":
    """
    Get the currently executing EventLoop instance.
    
    Returns:
        The current EventLoop instance, or None if not in an EventLoop context.
    """
    global _current_event_loop
    
    return _current_event_loop

class EventLoop:
    """
    The core event loop implementation for Flowno's asynchronous execution model.

    Manages task scheduling, I/O operations, and synchronization primitives for
    the dataflow runtime.
    """

    def __init__(self) -> None:
        self.tasks: deque[RawTaskPacket[Command, Any, object, Exception]] = deque()
        self.sleeping: list[tuple[Time, RawTask[SleepCommand, None, DeltaTime]]] = []
        self.watching_task: defaultdict[
            RawTask[Command, object, object], list[RawTask[Command, object, object]]
        ] = defaultdict(list)
        self.waiting_on_network: list[RawTask[SocketCommand, Any, Any]] = []
        self.tasks_waiting_on_a_queue: set[
            RawTask[QueueGetCommand[object] | QueuePutCommand[object], Any, Any]
        ] = set()
        self.finished: dict[RawTask[Command, Any, Any], object] = {}
        self.exceptions: dict[RawTask[Command, Any, Any], Exception] = {}
        self.cancelled: set[RawTask[Command, Any, Any]] = set()
        self._debug_max_wait_time: float | None = None
        self._loop_thread: threading.Thread | None = None
        self._wakeup_reader, self._wakeup_writer = socket.socketpair()
        self._wakeup_reader.setblocking(False)
        self._wakeup_writer.setblocking(False)
        self._exit_requested: tuple[bool, object, Exception | None] = (
            False,
            None,
            None,
        )
        self._signal_handlers_installed = False

    def _dump_debug_info(self, reason: str = "Signal received") -> None:
        """
        Log detailed debug information about the current state of the event loop.

        This method provides comprehensive debugging information useful when the
        event loop is interrupted or appears to be stuck.

        Args:
            reason: The reason for dumping debug info (e.g., "SIGINT received")
        """
        logger.warning(f"=== EVENT LOOP DEBUG INFO ({reason}) ===")

        # Basic task counts
        logger.warning(f"Active tasks in queue: {len(self.tasks)}")
        logger.warning(f"Sleeping tasks: {len(self.sleeping)}")
        logger.warning(f"Tasks waiting on network I/O: {len(self.waiting_on_network)}")
        logger.warning(f"Tasks waiting on queues: {len(self.tasks_waiting_on_a_queue)}")

        # Task details
        if self.tasks:
            logger.warning("=== ACTIVE TASKS ===")
            for i, (task, send_value, exception) in enumerate(self.tasks):
                logger.warning(f"  Task {i}: {task}")
                if send_value is not None:
                    logger.warning(f"    Pending send value: {send_value}")
                if exception is not None:
                    logger.warning(f"    Pending exception: {exception}")

        # Sleeping tasks details
        if self.sleeping:
            logger.warning("=== SLEEPING TASKS ===")
            current_time = timer()
            for wake_time, task in self.sleeping[:5]:  # Show first 5 sleeping tasks
                time_remaining = wake_time - current_time
                logger.warning(f"  Task: {task}, wakes in {time_remaining:.3f}s")
            if len(self.sleeping) > 5:
                logger.warning(
                    f"  ... and {len(self.sleeping) - 5} more sleeping tasks"
                )

        # Network I/O tasks
        if self.waiting_on_network:
            logger.warning("=== NETWORK I/O TASKS ===")
            for task in self.waiting_on_network[:5]:  # Show first 5 network tasks
                logger.warning(f"  Task: {task}")
            if len(self.waiting_on_network) > 5:
                logger.warning(
                    f"  ... and {len(self.waiting_on_network) - 5} more network tasks"
                )

        # Queue waiting tasks
        if self.tasks_waiting_on_a_queue:
            logger.warning("=== QUEUE WAITING TASKS ===")
            for task in list(self.tasks_waiting_on_a_queue)[
                :5
            ]:  # Show first 5 queue tasks
                logger.warning(f"  Task: {task}")
            if len(self.tasks_waiting_on_a_queue) > 5:
                logger.warning(
                    f"  ... and {len(self.tasks_waiting_on_a_queue) - 5} more queue tasks"
                )

        # Task watching relationships
        watching_count = sum(len(watchers) for watchers in self.watching_task.values())
        if watching_count > 0:
            logger.warning(f"=== TASK WATCHING ({watching_count} relationships) ===")
            count = 0
            for watched_task, watchers in self.watching_task.items():
                if count >= 5:  # Limit output
                    logger.warning(
                        f"  ... and {watching_count - count} more relationships"
                    )
                    break
                if watchers:
                    logger.warning(f"  {watched_task} watched by {len(watchers)} tasks")
                    count += len(watchers)

        # Finished and exception tasks
        logger.warning(f"Finished tasks: {len(self.finished)}")
        logger.warning(f"Tasks with exceptions: {len(self.exceptions)}")
        logger.warning(f"Cancelled tasks: {len(self.cancelled)}")

        logger.warning("=== END DEBUG INFO ===")

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for debugging interrupted event loops."""
        if self._signal_handlers_installed:
            return

        def signal_handler(signum: int, frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            self._dump_debug_info(f"Signal {sig_name} received")
            # Re-raise KeyboardInterrupt for SIGINT to maintain normal behavior
            if signum == signal.SIGINT:
                raise KeyboardInterrupt()

        # Install handlers for common interrupt signals
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            # Only install SIGUSR1 on Unix systems
            if hasattr(signal, "SIGUSR1"):
                signal.signal(signal.SIGUSR1, signal_handler)
            self._signal_handlers_installed = True
            logger.debug("Signal handlers installed for event loop debugging")
        except (OSError, ValueError) as e:
            # Signal handling might not be available in all contexts (e.g., threads)
            logger.debug(f"Could not install signal handlers: {e}")

    def _uninstall_signal_handlers(self) -> None:
        """Restore default signal handlers."""
        if not self._signal_handlers_installed:
            return

        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            if hasattr(signal, "SIGUSR1"):
                signal.signal(signal.SIGUSR1, signal.SIG_DFL)
            self._signal_handlers_installed = False
            logger.debug("Signal handlers uninstalled")
        except (OSError, ValueError) as e:
            logger.debug(f"Could not uninstall signal handlers: {e}")

    def has_living_tasks(self) -> bool:
        """Return True if there are any tasks still needing processing."""
        if self.tasks or self.sleeping or self.waiting_on_network:
            return True
        for _watched_task, watching_tasks in self.watching_task.items():
            if watching_tasks:
                return True
        if self.tasks_waiting_on_a_queue:
            return True
        return False

    def create_task(
        self,
        raw_task: RawTask[Command, Any, Any],
    ) -> TaskHandle[Command]:
        """
        Create a new task handle for the given raw task and enqueue
        the task in the event loop's task queue.

        Args:
            raw_task: The raw task to create a handle for.

        Returns:
            A TaskHandle object representing the created task.
        """
        self.tasks.append((raw_task, None, None))

        # If called from another thread, wake up the event loop
        if (
            self._loop_thread is not None
            and threading.current_thread() != self._loop_thread
        ):
            try:
                self._wakeup_writer.send(b"\x00")
            except (BlockingIOError, socket.error):
                pass

        return TaskHandle(self, raw_task)

    def _handle_command(
        self,
        current_task_packet: TaskHandlePacket[Command, Any, Any, Exception],
        command: Command,
    ) -> bool:
        """
        Handle the command yielded by the current task.

        Returns True if the command was successfully handled.
        """
        if isinstance(command, SpawnCommand):
            command = cast(SpawnCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[SpawnCommand[object], Any, Any, Exception],
                current_task_packet,
            )

            new_task = TaskHandle[object](self, command.raw_task)
            self.tasks.append((command.raw_task, None, None))
            self.tasks.append((current_task_packet[0], new_task, None))

        elif isinstance(command, JoinCommand):
            command = cast(JoinCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[JoinCommand[object], Any, Any, Exception],
                current_task_packet,
            )

            if command.task_handle.is_finished:
                self.tasks.append(
                    (
                        current_task_packet[0],
                        self.finished[command.task_handle.raw_task],
                        None,
                    )
                )
            elif command.task_handle.is_error or command.task_handle.is_cancelled:
                self.tasks.append(
                    (
                        current_task_packet[0],
                        None,
                        self.exceptions[command.task_handle.raw_task],
                    )
                )
            else:
                # wait for the joined task to finish
                self.watching_task[command.task_handle.raw_task].append(
                    current_task_packet[0]
                )

        elif isinstance(command, SleepCommand):
            current_task_packet = cast(
                TaskHandlePacket[SleepCommand, None, DeltaTime, Exception],
                current_task_packet,
            )
            if command.end_time <= timer():
                self.tasks.append((current_task_packet[0], None, None))
            else:
                heapq.heappush(
                    self.sleeping, (command.end_time, current_task_packet[0])
                )

        elif isinstance(command, SocketAcceptCommand):
            current_task_packet = cast(
                TaskHandlePacket[SocketAcceptCommand, None, None, Exception],
                current_task_packet,
            )
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0],
                _command=command,
                socket_handle=command.handle,
            )
            get_current_instrument().on_socket_accept_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_READ, metadata)

        elif isinstance(command, SocketSendCommand):
            current_task_packet = cast(
                TaskHandlePacket[SocketSendCommand, None, None, Exception],
                current_task_packet,
            )
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0],
                _command=command,
                socket_handle=command.handle,
            )
            get_current_instrument().on_socket_send_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_WRITE, metadata)

        elif isinstance(command, SocketRecvCommand):
            current_task_packet = cast(
                TaskHandlePacket[SocketRecvCommand, None, None, Exception],
                current_task_packet,
            )
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0],
                _command=command,
                socket_handle=command.handle,
            )
            get_current_instrument().on_socket_recv_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_READ, metadata)

        elif isinstance(command, QueueGetCommand):
            command = cast(QueueGetCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[QueueGetCommand[object], Any, Any, Exception],
                current_task_packet,
            )
            queue = command.queue
            if queue.items:
                if command.peek:
                    self.tasks.append((current_task_packet[0], queue.items[0], None))
                else:
                    item = queue.items.popleft()
                    self.tasks.append((current_task_packet[0], item, None))
                    get_current_instrument().on_queue_get(
                        queue=queue, item=item, immediate=False
                    )
                    if queue._put_waiting:  # pyright: ignore[reportPrivateUsage]
                        task_waiting = (
                            queue._put_waiting.popleft()
                        )  # pyright: ignore[reportPrivateUsage]
                        self.tasks_waiting_on_a_queue.remove(task_waiting.task)
                        if queue._get_waiting:  # pyright: ignore[reportPrivateUsage]
                            raise RuntimeError(
                                "Internal error: Tasks waiting to both get and put on the same queue"
                            )
                        else:
                            queue.items.append(task_waiting.item)
                            self.tasks.append((task_waiting.task, None, None))
            elif queue.closed:
                self.tasks.append(
                    (
                        current_task_packet[0],
                        None,
                        QueueClosedError("Queue has been closed and is empty"),
                    )
                )
            else:
                queue._get_waiting.append(  # pyright: ignore[reportPrivateUsage]
                    TaskWaitingOnQueueGet(
                        task=current_task_packet[0],
                        peek=command.peek,
                    )
                )
                self.tasks_waiting_on_a_queue.add(current_task_packet[0])

        elif isinstance(command, QueuePutCommand):
            command = cast(QueuePutCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[QueuePutCommand[object], Any, None, Exception],
                current_task_packet,
            )
            queue = command.queue
            item = command.item
            if queue.closed:
                self.tasks.append(
                    (
                        current_task_packet[0],
                        None,
                        QueueClosedError("Cannot put item into closed queue"),
                    )
                )
            elif queue.maxsize is not None and len(queue.items) >= queue.maxsize:
                queue._put_waiting.append(  # pyright: ignore[reportPrivateUsage]
                    TaskWaitingOnQueuePut(
                        task=current_task_packet[0],
                        item=item,
                    )
                )
                self.tasks_waiting_on_a_queue.add(current_task_packet[0])
            else:
                if queue._get_waiting:  # pyright: ignore[reportPrivateUsage]
                    task_blocked_on_get = (
                        queue._get_waiting.popleft()
                    )  # pyright: ignore[reportPrivateUsage]
                    self.tasks_waiting_on_a_queue.remove(task_blocked_on_get.task)
                    self.tasks.append((task_blocked_on_get.task, item, None))
                    self.tasks.append((current_task_packet[0], None, None))
                else:
                    queue.items.append(item)
                    get_current_instrument().on_queue_put(
                        queue=queue, item=item, immediate=False
                    )
                    self.tasks.append((current_task_packet[0], None, None))

        elif isinstance(command, QueueNotifyGettersCommand):
            command = cast(QueueNotifyGettersCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[
                    QueueNotifyGettersCommand[object], Any, None, Exception
                ],
                current_task_packet,
            )
            queue = command.queue
            if (
                queue._get_waiting and queue.items
            ):  # pyright: ignore[reportPrivateUsage]
                task_blocked_on_get = (
                    queue._get_waiting.popleft()
                )  # pyright: ignore[reportPrivateUsage]
                self.tasks_waiting_on_a_queue.remove(task_blocked_on_get.task)
                item = queue.items.popleft()
                self.tasks.append((task_blocked_on_get.task, item, None))
                get_current_instrument().on_queue_get(
                    queue=queue, item=item, immediate=False
                )
            self.tasks.append((current_task_packet[0], None, None))

        elif isinstance(command, QueueCloseCommand):
            command = cast(QueueCloseCommand[object], command)
            current_task_packet = cast(
                TaskHandlePacket[QueueCloseCommand[object], Any, None, Exception],
                current_task_packet,
            )
            queue = command.queue
            self.handle_queue_close(queue)
            self.tasks.append((current_task_packet[0], None, None))
        elif isinstance(command, ExitCommand):
            # Handle the exit command

            # Mark the task as finished regardless of whether we're exiting normally or with an exception
            # This prevents "event loop exited without completing the root task" errors
            self.finished[current_task_packet[0]] = command.return_value

            # If there's an exception, raise it immediately (will be caught in run_until_complete)
            if command.exception is not None:
                raise command.exception
            else:
                # Set the exit flag with the return value and no exception
                self._exit_requested = (True, command.return_value, None)
        else:
            return False
        return True

    def handle_queue_close(self, queue: AsyncQueue[Any]) -> None:
        """
        Handle a queue being closed. Also resumes all tasks waiting on the queue
        with an appropriate exception.
        """
        queue.closed = True
        for task_waiting in queue._get_waiting:  # pyright: ignore[reportPrivateUsage]
            self.tasks.append(
                (
                    task_waiting.task,
                    None,
                    QueueClosedError("Queue has been closed and is empty"),
                )
            )
            self.tasks_waiting_on_a_queue.remove(task_waiting.task)
        for task_waiting in queue._put_waiting:  # pyright: ignore[reportPrivateUsage]
            self.tasks.append(
                (
                    task_waiting.task,
                    None,
                    QueueClosedError("Cannot put item into closed queue"),
                )
            )
            self.tasks_waiting_on_a_queue.remove(task_waiting.task)

    def cancel(self, raw_task: RawTask[Command, Any, Any]) -> bool:
        """
        Cancel a task.

        Args:
            raw_task: The task to cancel.

        Returns:
            True if the task was successfully cancelled; False if it was already finished or errored.
        """
        if raw_task in self.finished or raw_task in self.exceptions:
            return False
        self.tasks.append((raw_task, None, TaskCancelled(TaskHandle(self, raw_task))))
        return True

    @overload
    def run_until_complete(
        self,
        root_task: RawTask[Command, Any, _ReturnT],
        join: Literal[False] = False,
        wait_for_spawned_tasks: bool = True,
        _debug_max_wait_time: float | None = None,
    ) -> None: ...

    @overload
    def run_until_complete(
        self,
        root_task: RawTask[Command, Any, _ReturnT],
        join: bool = False,
        wait_for_spawned_tasks: bool = True,
        _debug_max_wait_time: float | None = None,
    ) -> _ReturnT: ...

    def run_until_complete(
        self,
        root_task: RawTask[Command, Any, _ReturnT],
        join: bool = False,
        wait_for_spawned_tasks: bool = True,
        _debug_max_wait_time: float | None = None,
    ) -> _ReturnT | None:
        """
        Run the event loop until the given root task is complete.

        This method executes the main event loop, processing tasks, handling I/O operations,
        and managing task synchronization until the root task completes. It can optionally
        wait for all spawned tasks to finish as well.

        Args:
            root_task (RawTask[Command, Any, _ReturnT]): The coroutine task to execute as the root
                                                         of the execution graph.
            join (bool): When True, returns the result value of the root task. When False,
                         returns None regardless of the task's result. If the task raises an
                         exception and join=True, the exception is re-raised.
            wait_for_spawned_tasks (bool): When True, continue running the event loop until all
                                           tasks spawned by the root task have completed. When False,
                                           stop as soon as the root task completes.
            _debug_max_wait_time (float | None): Optional timeout value in seconds used for debugging.
                                                 Limits how long the event loop will wait for network or
                                                 sleeping operations.

        Returns:
            _ReturnT | None: If join=True, returns the result of the root task (of type _ReturnT).
                             If join=False, returns None.

        Raises:
            RuntimeError: If the event loop exits without completing the root task
                          when join=True.
            Exception: Any exception raised by the root task is propagated if join=True.
        """
        self._install_signal_handlers()
        try:
            return_value = self._run_event_loop_core(
                root_task,
                join=join,
                wait_for_spawned_tasks=wait_for_spawned_tasks,
                _debug_max_wait_time=_debug_max_wait_time,
            )
            self._uninstall_signal_handlers()
        except:
            self._uninstall_signal_handlers()
            raise
        return return_value

    def _run_event_loop_core(
        self,
        root_task: RawTask[Command, Any, _ReturnT],
        join: bool = False,
        wait_for_spawned_tasks: bool = True,
        _debug_max_wait_time: float | None = None,
    ):
        global _current_event_loop
        _current_event_loop = self
        
        try:
            self._debug_max_wait_time = _debug_max_wait_time
            self._loop_thread = threading.current_thread()
            self._exit_requested = (False, None, None)  # Reset exit flag
            self.tasks.append((root_task, None, None))

            # Register wakeup socket with selector
            # Blank metadata for wakeup socket. Never used.
            metadata = InstrumentationMetadata(
                _task=None, _command=None, socket_handle=None
            )
            sel.register(self._wakeup_reader, selectors.EVENT_READ, metadata)

            while self.has_living_tasks():
                # Check if exit was requested
                exit_requested, exit_value, exit_exception = self._exit_requested
                if exit_requested:
                    # Handle any requested exit
                    if exit_exception is not None:
                        raise exit_exception
                    elif join:
                        return cast(_ReturnT, exit_value)
                    else:
                        return None

                # Determine the timeout for selector based on tasks and sleeping tasks.
                if self.tasks:
                    timeout = 0
                elif self.sleeping:
                    timeout = self.sleeping[0][0] - timer()
                    if (
                        self._debug_max_wait_time is not None
                        and timeout > self._debug_max_wait_time
                    ):
                        logger.error(
                            f"Sleeping task timeout {timeout} exceeds max wait time {_debug_max_wait_time}."
                        )
                        timeout = self._debug_max_wait_time
                else:
                    timeout = self._debug_max_wait_time

                for key, _mask in sel.select(timeout):
                    data = cast(InstrumentationMetadata, key.data)
                    if key.fileobj == self._wakeup_reader:
                        # Clear wakeup signal
                        try:
                            self._wakeup_reader.recv(1024)
                        except (BlockingIOError, socket.error):
                            pass
                        continue  # Skip further processing for wakeup socket

                    # Handle regular socket commands
                    if data._command is None:
                        # Skip processing if no command (shouldn't happen for regular sockets)
                        continue

                    match data._command:
                        case SocketAcceptCommand():
                            get_current_instrument().on_socket_accept_ready(
                                ReadySocketInstrumentationMetadata.from_instrumentation_metadata(
                                    data
                                )
                            )
                        case SocketRecvCommand():
                            get_current_instrument().on_socket_recv_ready(
                                ReadySocketInstrumentationMetadata.from_instrumentation_metadata(
                                    data
                                )
                            )
                        case SocketSendCommand():
                            get_current_instrument().on_socket_send_ready(
                                ReadySocketInstrumentationMetadata.from_instrumentation_metadata(
                                    data
                                )
                            )
                        case _:
                            raise ValueError(
                                f"Unknown selector command data type: {type(data._command)}"
                            )

                    self.tasks.append((data._task, None, None))
                    _ = sel.unregister(key.fileobj)
                    self.waiting_on_network.remove(data._task)

                while self.sleeping and self.sleeping[0][0] <= timer():
                    _, task = heapq.heappop(self.sleeping)
                    self.tasks.append((task, None, None))

                if self.tasks:
                    task_packet = self.tasks.popleft()
                    
                    # Set the current task before executing
                    token = _current_task.set(task_packet[0])
                    
                    try:
                        if task_packet[2] is not None:
                            command = task_packet[0].throw(task_packet[2])
                        else:
                            command = task_packet[0].send(task_packet[1])
                    except StopIteration as e:
                        returned_value = cast(object, e.value)
                        self.finished[task_packet[0]] = returned_value
                        for watcher in self.watching_task[task_packet[0]]:
                            self.tasks.append((watcher, returned_value, None))
                        del self.watching_task[task_packet[0]]
                        if task_packet[0] == root_task and not wait_for_spawned_tasks:
                            return cast(_ReturnT, returned_value) if join else None
                    except TaskCancelled as e:
                        self.cancelled.add(task_packet[0])
                        self.exceptions[task_packet[0]] = e
                        for watcher in self.watching_task[task_packet[0]]:
                            self.tasks.append((watcher, None, e))
                        del self.watching_task[task_packet[0]]
                        if task_packet[0] == root_task and not wait_for_spawned_tasks:
                            if join:
                                raise e
                            else:
                                return
                    except Exception as e:
                        logger.exception(f"Task {task_packet[0]} raised an exception: {e}")
                        self.exceptions[task_packet[0]] = e
                        for watcher in self.watching_task[task_packet[0]]:
                            self.tasks.append((watcher, None, e))
                        del self.watching_task[task_packet[0]]
                        if task_packet[0] == root_task and not wait_for_spawned_tasks:
                            if join:
                                raise e
                            else:
                                return
                    else:
                        _ = self._handle_command(task_packet, command)
                    finally:
                        # Reset the context after task execution
                        _current_task.reset(token)
            
            if join and root_task in self.finished:
                return cast(_ReturnT, self.finished[root_task])
            elif join and root_task in self.exceptions:
                raise self.exceptions[root_task]
            elif join:
                raise RuntimeError("Event loop exited without completing the root task.")
        finally:
            _current_event_loop = None
