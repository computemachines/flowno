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
    - FLOWNO_LOG_FILE: Write logs to file when set (e.g., "flowno.log")
    - FLOWNO_LOG_CONSOLE: Enable console logging (default: true, set to "false" to disable)
    - FLOWNO_LOG_PROPAGATE: Propagate logs to parent loggers (default: true, set to "false" to disable)


"""

import logging
import os
from importlib.metadata import PackageNotFoundError, version

from .core.event_loop.event_loop import EventLoop, current_event_loop
from .core.event_loop.primitives import azip, exit, sleep, socket, spawn
from .core.event_loop.queues import AsyncQueue
from .core.event_loop.selectors import SocketHandle
from .core.flow.flow import Flow, TerminateLimitReached, current_flow, current_node, current_context
from .core.flow_hdl import FlowHDL
from .core.flow_hdl_view import FlowHDLView
from .core.node_base import DraftNode, Stream, StreamCancelled
from .core.group_node import DraftGroupNode
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


# Check if user has explicitly configured logging via environment variables
_log_level_env = os.environ.get("FLOWNO_LOG_LEVEL")
_log_file_env = os.environ.get("FLOWNO_LOG_FILE")
_log_console_env = os.environ.get("FLOWNO_LOG_CONSOLE")
_log_propagate_env = os.environ.get("FLOWNO_LOG_PROPAGATE")

LOG_LEVEL = (_log_level_env or "ERROR").upper()
# Example: LOG_TAG_FILTER="flow,event"
raw_tag_filter = os.environ.get("FLOWNO_LOG_TAG_FILTER", "ALL")
tag_list = [t.strip().lower() for t in raw_tag_filter.split(",")]

# Get the flowno logger (not root logger, to avoid interfering with user logging)
logger = logging.getLogger("flowno")

# Set propagate behavior - default is True so pytest and other tools can capture logs
# Set to "false" or "0" to prevent propagation to parent loggers
if _log_propagate_env:
    logger.propagate = _log_propagate_env.lower() not in ("false", "0", "no")
else:
    logger.propagate = True  # Explicitly set default to True

# Only add handlers if user has explicitly set any logging environment variables
# This prevents interfering with user's logging configuration or test frameworks
if _log_level_env or _log_file_env or _log_console_env:
    # Only set level if user configured logging
    logger.setLevel(LOG_LEVEL)
    # Determine console logging preference
    log_console = (_log_console_env or "true").lower() not in ("false", "0", "no")
    
    # Remove existing flowno-specific handlers to prevent duplication on reimport
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter("%(asctime)s - %(levelname)s:%(name)s:%(message)s")
    
    # Create and configure the console handler if enabled
    if log_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(LOG_LEVEL)
        console_handler.addFilter(TagFilter(tag_list))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # Create and configure the file handler if FLOWNO_LOG_FILE is set
    if _log_file_env:
        try:
            file_handler = logging.FileHandler(_log_file_env)
            file_handler.setLevel(LOG_LEVEL)
            file_handler.addFilter(TagFilter(tag_list))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.info(f"File logging enabled: {_log_file_env}")
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to create log file '{_log_file_env}': {e}")

logger.info(f"Log level set to {LOG_LEVEL}")
logger.info(f"Log filter set to {tag_list}")


__all__ = [
    "node",
    "Flow",
    "azip",
    "exit",
    "spawn",
    "sleep",
    "socket",
    "DraftNode",
    "DraftGroupNode",
    "Stream",
    "StreamCancelled",
    "SocketHandle",
    "FlowHDL",
    "FlowHDLView",
    "EventLoop",
    "AsyncQueue",
    "TerminateLimitReached",
    "current_event_loop",
    "current_flow",
    "current_node",
    "current_context",
]
