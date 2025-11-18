from typing import Literal, NewType, TypeAlias

RunLevel: TypeAlias = Literal[0, 1, 2, 3]

Status: TypeAlias = tuple[Literal["deferred"]] | tuple[Literal["running"], RunLevel] | tuple[Literal["ready"]] | tuple[
    Literal["error"], Exception
]


DataGeneration: TypeAlias = tuple[int, ...]
Generation: TypeAlias = DataGeneration | None

InputPortIndex = NewType("InputPortIndex", int)
OutputPortIndex = NewType("OutputPortIndex", int)


class _SkipType:
    """Sentinel type for conditional execution skips.

    When a PropagateIf node's condition is False, it returns SKIP instead of data.
    Downstream nodes automatically propagate SKIP without executing their computation.
    """
    _instance: "_SkipType | None" = None

    def __new__(cls) -> "_SkipType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "SKIP"

    def __str__(self) -> str:
        return "SKIP"


# Singleton instance for skip sentinel
SKIP = _SkipType()


__all__ = [
    "Status",
    "InputPortIndex",
    "OutputPortIndex",
    "RunLevel",
    "Generation",
    "DataGeneration",
    "SKIP",
]
