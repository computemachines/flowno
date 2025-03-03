"""
Type definitions for Flowno's event loop system.

This module defines the core type aliases used throughout Flowno's event loop
implementation. These types are primarily for internal use by the event loop
system, but understanding them can be helpful when extending the event loop
or creating custom primitives.

Most users should not need to import from this module directly.
"""

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

if TYPE_CHECKING:
    from .commands import Command  # Only import during type checking

#: Type alias for absolute time (in seconds since epoch)
Time: TypeAlias = float

#: Type alias for a time duration in seconds
DeltaTime: TypeAlias = float

#: Generic yield type for coroutines
_YieldT = TypeVar("_YieldT")

#: Generic send type for coroutines (contravariant)
_SendT_contra = TypeVar("_SendT_contra", contravariant=True)

#: Generic return type for coroutines (covariant)
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True)

#: Command yield type (forward reference to Command)
_CommandYieldT_co = TypeVar("_CommandYieldT_co", bound="Command", covariant=True)

#: Generic exception type
_Exception = TypeVar("_Exception", bound=Exception)

#: Type alias for a raw task coroutine with generic yield, send, and return types
RawTask: TypeAlias = Coroutine[_YieldT, _SendT_contra, _ReturnT_co]

#: Type alias for a task coroutine that yields commands and can be sent/returned anything
AnyRawTask = RawTask["Command", Any, Any]

#: Type alias for a task coroutine using object types
ObjectRawTask = RawTask["Command", object, object]

#: Type alias for a task packet containing the task coroutine, value to send, and any exception
RawTaskPacket: TypeAlias = tuple[
    RawTask[_CommandYieldT_co, _SendT_contra, _ReturnT_co],
    _SendT_contra,
    _Exception | None,
]

#: Type alias for a task packet that includes a task handle
TaskHandlePacket: TypeAlias = tuple[
    RawTask[_CommandYieldT_co, _SendT_contra, _ReturnT_co],
    _SendT_contra,
    _Exception | None,
]

#: Type alias for socket address formats (either tuple or string)
_Address: TypeAlias = tuple[Any, ...] | str


__all__ = [
    "Time",
    "DeltaTime",
    "RawTask",
    "AnyRawTask",
    "ObjectRawTask",
    "RawTaskPacket",
    "TaskHandlePacket",
]
