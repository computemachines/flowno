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

import heapq
import logging
import selectors
from collections import defaultdict, deque
from timeit import default_timer as timer
from typing import Any, Literal, TypeVar, cast

from flowno.core.event_loop.commands import (
    Command,
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
            RawTask[Command, object, object],
            list[RawTask[Command, object, object]]
        ] = defaultdict(list)
        self.waiting_on_network: list[RawTask[SocketCommand, Any, Any]] = []
        self.tasks_waiting_on_a_queue: set[
            RawTask[QueueGetCommand[object] | QueuePutCommand[object], Any, Any]
        ] = set()
        self.finished: dict[RawTask[Command, Any, Any], object] = {}
        self.exceptions: dict[RawTask[Command, Any, Any], Exception] = {}
        self.cancelled: set[RawTask[Command, Any, Any]] = set()
        self._debug_max_wait_time: float | None = None

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
            current_task_packet = cast(TaskHandlePacket[SpawnCommand[object], Any, Any, Exception], current_task_packet)

            new_task = TaskHandle[object](self, command.raw_task)
            self.tasks.append((command.raw_task, None, None))
            self.tasks.append((current_task_packet[0], new_task, None))

        elif isinstance(command, JoinCommand):
            command = cast(JoinCommand[object], command)
            current_task_packet = cast(TaskHandlePacket[JoinCommand[object], Any, Any, Exception], current_task_packet)

            if command.task_handle.is_finished:
                self.tasks.append((current_task_packet[0], self.finished[command.task_handle.raw_task], None))
            elif command.task_handle.is_error or command.task_handle.is_cancelled:
                self.tasks.append((current_task_packet[0], None, self.exceptions[command.task_handle.raw_task]))
            else:
                # wait for the joined task to finish
                self.watching_task[command.task_handle.raw_task].append(current_task_packet[0])

        elif isinstance(command, SleepCommand):
            current_task_packet = cast(TaskHandlePacket[SleepCommand, None, DeltaTime, Exception], current_task_packet)
            if command.end_time <= timer():
                self.tasks.append((current_task_packet[0], None, None))
            else:
                heapq.heappush(self.sleeping, (command.end_time, current_task_packet[0]))

        elif isinstance(command, SocketAcceptCommand):
            current_task_packet = cast(TaskHandlePacket[SocketAcceptCommand, None, None, Exception], current_task_packet)
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0], _command=command, socket_handle=command.handle
            )
            get_current_instrument().on_socket_accept_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_READ, metadata)

        elif isinstance(command, SocketSendCommand):
            current_task_packet = cast(TaskHandlePacket[SocketSendCommand, None, None, Exception], current_task_packet)
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0], _command=command, socket_handle=command.handle
            )
            get_current_instrument().on_socket_send_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_WRITE, metadata)

        elif isinstance(command, SocketRecvCommand):
            current_task_packet = cast(TaskHandlePacket[SocketRecvCommand, None, None, Exception], current_task_packet)
            metadata = InstrumentationMetadata(
                _task=current_task_packet[0], _command=command, socket_handle=command.handle
            )
            get_current_instrument().on_socket_recv_start(metadata)
            self.waiting_on_network.append(current_task_packet[0])
            _ = sel.register(command.handle.socket, selectors.EVENT_READ, metadata)

        elif isinstance(command, QueueGetCommand):
            command = cast(QueueGetCommand[object], command)
            current_task_packet = cast(TaskHandlePacket[QueueGetCommand[object], Any, Any, Exception], current_task_packet)
            queue = command.queue
            if queue.items:
                if command.peek:
                    self.tasks.append((current_task_packet[0], queue.items[0], None))
                else:
                    item = queue.items.popleft()
                    self.tasks.append((current_task_packet[0], item, None))
                    get_current_instrument().on_queue_get(queue=queue, item=item, immediate=False)
                    if queue._put_waiting:  # pyright: ignore[reportPrivateUsage]
                        task_waiting = queue._put_waiting.popleft()  # pyright: ignore[reportPrivateUsage]
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
                    (current_task_packet[0], None, QueueClosedError("Queue has been closed and is empty"))
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
            current_task_packet = cast(TaskHandlePacket[QueuePutCommand[object], Any, None, Exception], current_task_packet)
            queue = command.queue
            item = command.item
            if queue.closed:
                self.tasks.append(
                    (current_task_packet[0], None, QueueClosedError("Cannot put item into closed queue"))
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
                    task_blocked_on_get = queue._get_waiting.popleft()  # pyright: ignore[reportPrivateUsage]
                    self.tasks_waiting_on_a_queue.remove(task_blocked_on_get.task)
                    self.tasks.append((task_blocked_on_get.task, item, None))
                    self.tasks.append((current_task_packet[0], None, None))
                else:
                    queue.items.append(item)
                    get_current_instrument().on_queue_put(queue=queue, item=item, immediate=False)
                    self.tasks.append((current_task_packet[0], None, None))

        elif isinstance(command, QueueNotifyGettersCommand):
            command = cast(QueueNotifyGettersCommand[object], command)
            current_task_packet = cast(TaskHandlePacket[QueueNotifyGettersCommand[object], Any, None, Exception], current_task_packet)
            queue = command.queue
            if queue._get_waiting and queue.items:  # pyright: ignore[reportPrivateUsage]
                task_blocked_on_get = queue._get_waiting.popleft()  # pyright: ignore[reportPrivateUsage]
                self.tasks_waiting_on_a_queue.remove(task_blocked_on_get.task)
                item = queue.items.popleft()
                self.tasks.append((task_blocked_on_get.task, item, None))
                get_current_instrument().on_queue_get(queue=queue, item=item, immediate=False)
            self.tasks.append((current_task_packet[0], None, None))

        elif isinstance(command, QueueCloseCommand):
            command = cast(QueueCloseCommand[object], command)
            current_task_packet = cast(TaskHandlePacket[QueueCloseCommand[object], Any, None, Exception], current_task_packet)
            queue = command.queue
            self.handle_queue_close(queue)
            self.tasks.append((current_task_packet[0], None, None))
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
            self.tasks.append((task_waiting.task, None, QueueClosedError("Queue has been closed and is empty")))
            self.tasks_waiting_on_a_queue.remove(task_waiting.task)
        for task_waiting in queue._put_waiting:  # pyright: ignore[reportPrivateUsage]
            self.tasks.append((task_waiting.task, None, QueueClosedError("Cannot put item into closed queue")))
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
        self._debug_max_wait_time = _debug_max_wait_time
        self.tasks.append((root_task, None, None))
        
        while self.has_living_tasks():
            # Determine the timeout for selector based on tasks and sleeping tasks.
            if self.tasks:
                timeout = 0
            elif self.sleeping:
                timeout = self.sleeping[0][0] - timer()
                if self._debug_max_wait_time is not None and timeout > self._debug_max_wait_time:
                    logger.error(
                        f"Sleeping task timeout {timeout} exceeds max wait time {_debug_max_wait_time}."
                    )
                    timeout = self._debug_max_wait_time
            else:
                timeout = self._debug_max_wait_time
            
            for key, _mask in sel.select(timeout):
                data = cast(InstrumentationMetadata, key.data)
                match data._command:
                    case SocketAcceptCommand():
                        get_current_instrument().on_socket_accept_ready(
                            ReadySocketInstrumentationMetadata.from_instrumentation_metadata(data)
                        )
                    case SocketRecvCommand():
                        get_current_instrument().on_socket_recv_ready(
                            ReadySocketInstrumentationMetadata.from_instrumentation_metadata(data)
                        )
                    case SocketSendCommand():
                        get_current_instrument().on_socket_send_ready(
                            ReadySocketInstrumentationMetadata.from_instrumentation_metadata(data)
                        )
                    case _:
                        raise ValueError("Unknown selector command data type")
                self.tasks.append((data._task, None, None))
                _ = sel.unregister(key.fileobj)
                self.waiting_on_network.remove(data._task)
            
            while self.sleeping and self.sleeping[0][0] <= timer():
                _, task = heapq.heappop(self.sleeping)
                self.tasks.append((task, None, None))
            
            if self.tasks:
                task_packet = self.tasks.popleft()
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
        if join and root_task in self.finished:
            return cast(_ReturnT, self.finished[root_task])
        elif join and root_task in self.exceptions:
            raise self.exceptions[root_task]
        elif join:
            raise RuntimeError("Event loop exited without completing the root task.")
