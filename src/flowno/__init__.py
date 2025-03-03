"""
Flowno: A Python DSL for building dataflow programs.

This module provides tools for creating concurrent, cyclic, and streaming dataflow
programs.

Key features:
    - Node-based design with the @node decorator
    - Support for cyclic dependencies and streaming data
    - Built-in concurrency with a custom event loop
    - Type-checked node connections

Configure logging with environment variables:
    - FLOWNO_LOG_LEVEL: Set logging level (default: ERROR)
    - FLOWNO_LOG_TAG_FILTER: Filter logs by tags (default: ALL)


"""

import logging
import os
from importlib.metadata import PackageNotFoundError, version

from .core.event_loop.event_loop import EventLoop
from .core.event_loop.primitives import azip, sleep, socket, spawn
from .core.event_loop.queues import AsyncQueue
from .core.event_loop.selectors import SocketHandle
from .core.flow.flow import Flow, TerminateLimitReached
from .core.flow_hdl import FlowHDL
from .core.node_base import DraftNode, Stream
from .decorators import node

try:
    __version__ = version("flowno")
except PackageNotFoundError:
    __version__ = "unknown"


class TagFilter(logging.Filter):
    def __init__(self, tags):
        """
        :param tags: a list of tag strings (already lowercased)
        """
        super().__init__()
        self.tags = tags  # e.g., ["flow", "event"]

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Return True if record.tag is in self.tags or if 'all' is in self.tags.
        If record.tag is not set, default to 'all'.
        """
        rec_tag = getattr(record, "tag", "all").lower()
        if "all" in self.tags:
            return True
        return rec_tag in self.tags


LOG_LEVEL = os.environ.get("FLOWNO_LOG_LEVEL", "ERROR").upper()
# Example: LOG_TAG_FILTER="flow,event"
raw_tag_filter = os.environ.get("FLOWNO_LOG_TAG_FILTER", "ALL")

# Split on commas, strip whitespace, and lowercase everything
tag_list = [t.strip().lower() for t in raw_tag_filter.split(",")]

# Get the root logger
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# Remove all existing handlers to prevent duplication
if logger.hasHandlers():
    logger.handlers.clear()

# Create and configure the custom handler
handler = logging.StreamHandler()
handler.setLevel(LOG_LEVEL)
handler.addFilter(TagFilter(tag_list))

# Optionally, set a formatter
formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
handler.setFormatter(formatter)

# Add the custom handler to the root logger
logger.addHandler(handler)

# Log messages without 'extra'
logger.info(f"Log level set to {LOG_LEVEL}")
logger.info(f"Log filter set to {tag_list}")  # Removed 'extra'


__all__ = [
    "node",
    "Flow",
    "azip",
    "spawn",
    "sleep",
    "socket",
    "nodes",
    "DraftNode",
    "Stream",
    "SocketHandle",
    "FlowHDL",
    "EventLoop",
    "AsyncQueue",
    "TerminateLimitReached",
]
