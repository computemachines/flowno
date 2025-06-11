"""
Exploratory test for FlowHDLView attribute placeholders.
Accessing an undefined attribute should yield a NodePlaceholder.
"""

from typing import cast
from typing_extensions import assert_type

from flowno import FlowHDL
from flowno.core.node_base import AnyNode, NodePlaceholder


def placeholder_behavior() -> None:
    with FlowHDL() as f:
        placeholder = f.undefined
        _ = assert_type(placeholder, NodePlaceholder)

        dummy: AnyNode = cast(AnyNode, object())
        f.undefined = dummy
        defined = f.undefined
        _ = assert_type(defined, AnyNode)

