"""Pytest configuration and fixtures for flowno tests."""

import pytest
from flowno.core.flow_hdl_view import FlowHDLView


@pytest.fixture(autouse=True)
def clear_flowhdl_context():
    """Clear FlowHDLView.contextStack before and after each test.

    This prevents test pollution when a test fails before __exit__
    is called, which would leave stale entries in the contextStack
    that affect subsequent tests.
    """
    # Clear before test
    FlowHDLView.contextStack.clear()

    yield

    # Clear after test (in case test failed mid-execution)
    FlowHDLView.contextStack.clear()
