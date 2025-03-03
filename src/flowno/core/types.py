from typing import Literal, NewType, TypeAlias

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
]
