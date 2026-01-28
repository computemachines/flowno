from typing import Literal, NewType, TypeAlias


class _SkipType:
    """Sentinel value indicating a node should be skipped (conditional execution).

    When a node's input is SKIP, the node should not execute its implementation
    and should instead propagate SKIP to all its outputs. This enables conditional
    execution in dataflow graphs.

    Use the SKIP singleton instance, not this class directly.
    """
    _instance: "_SkipType | None" = None

    def __new__(cls) -> "_SkipType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "SKIP"

    def __reduce__(self) -> str:
        # Support pickling by returning the name that can be imported
        return "SKIP"


# Singleton sentinel value for conditional execution
SKIP: _SkipType = _SkipType()
"""Sentinel value indicating a node should be skipped.

When a PropagateIf node's condition is False, it returns SKIP.
When any node receives SKIP as an input, it propagates SKIP to all outputs
without executing its implementation.
"""


RunLevel: TypeAlias = Literal[0, 1, 2, 3]

Status: TypeAlias = tuple[Literal["deferred"]] | tuple[Literal["running"], RunLevel] | tuple[Literal["ready"]] | tuple[
    Literal["error"], Exception
]


DataGeneration: TypeAlias = tuple[int, ...]
Generation: TypeAlias = DataGeneration | None

InputPortIndex = NewType("InputPortIndex", int)
OutputPortIndex = NewType("OutputPortIndex", int)


__all__ = [
    "Status",
    "InputPortIndex",
    "OutputPortIndex",
    "RunLevel",
    "Generation",
    "DataGeneration",
    "SKIP",
    "_SkipType",
]
