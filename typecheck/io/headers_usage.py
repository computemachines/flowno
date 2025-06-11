"""
Exploratory type-checking tests for the ``Headers`` utility.

This checks basic operations such as setting, retrieving, and iterating
header values.
"""

from typing_extensions import assert_type
from flowno.io import Headers


def exercise_headers() -> None:
    headers = Headers()
    headers.set("Accept", ["application/json", "text/plain"])
    headers.set("Content-Type", "application/json")

    value = headers.get("accept")
    _ = assert_type(value, str | list[str] | None)

    for name, val in headers:
        _ = assert_type(name, str)
        _ = assert_type(val, str | list[str])

    header_string = headers.stringify()
    _ = assert_type(header_string, str)
