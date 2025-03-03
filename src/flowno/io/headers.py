"""
HTTP header handling for Flowno's HTTP client.

This module provides a simple, case-insensitive HTTP header container class
that can be used to store, retrieve, and manipulate HTTP headers. It's used
by the :py:mod:`flowno.io.http_client` module for handling request and response
headers.

Example:
    >>> from flowno.io.headers import Headers
    >>> 
    >>> # Create headers collection
    >>> headers = Headers()
    >>> headers.set("Content-Type", "application/json")
    >>> headers.set("Accept-Encoding", ["gzip", "deflate"])
    >>> 
    >>> # Get a header value
    >>> print(headers.get("content-type"))
    application/json
    >>> 
    >>> # Headers are case-insensitive
    >>> print(headers.get("CONTENT-TYPE"))
    application/json
    >>> 
    >>> # Convert headers to a string for HTTP request
    >>> print(headers.stringify())
    content-type: application/json
    accept-encoding: gzip, deflate
"""

class Headers:
    """
    Case-insensitive container for HTTP headers.
    
    This class provides methods for working with HTTP headers, ensuring that
    header names are handled case-insensitively as per HTTP specifications.
    It also handles automatic conversion of list values to comma-separated 
    strings as required by the HTTP protocol.
    
    Examples:
        >>> headers = Headers()
        >>> headers.set("Content-Type", "application/json")
        >>> headers.get("content-type")
        'application/json'
        
        # Using list values for headers that accept multiple values
        >>> headers.set("Accept", ["text/html", "application/json"])
        >>> headers.get("Accept")
        'text/html, application/json'
    """
    
    def __init__(self):
        """Initialize an empty headers collection."""
        self._headers: dict[str, str | list[str]] = {}

    def set(self, name: str, value: str | list[str]) -> None:
        """
        Set a header value.
        
        If the value is a list, it's joined with commas to create a single 
        header value, which is the standard way to represent multiple values 
        for a single header in HTTP.
        
        Args:
            name: Header name (case-insensitive)
            value: Header value or list of values
        
        Examples:
            >>> headers = Headers()
            >>> headers.set("Content-Type", "application/json")
            >>> headers.set("Accept-Encoding", ["gzip", "deflate"])
        """
        if isinstance(value, list):
            value = ", ".join(value)
        self._headers[name.lower()] = value

    def get(self, name: str, default: str | list[str] | None = None) -> str | list[str] | None:
        """
        Get a header value.
        
        Args:
            name: Header name (case-insensitive)
            default: Value to return if the header is not found
            
        Returns:
            The header value, or the default value if not found
            
        Examples:
            >>> headers = Headers()
            >>> headers.set("Content-Type", "application/json")
            >>> headers.get("content-type")
            'application/json'
            >>> headers.get("nonexistent-header", "default-value")
            'default-value'
        """
        return self._headers.get(name.lower(), default)

    def delete(self, name: str) -> None:
        """
        Remove a header.
        
        Args:
            name: Header name (case-insensitive)
            
        Examples:
            >>> headers = Headers()
            >>> headers.set("X-Custom-Header", "value")
            >>> headers.delete("X-Custom-Header")
            >>> headers.get("X-Custom-Header")
            None
        """
        if name.lower() in self._headers:
            del self._headers[name.lower()]

    def __iter__(self):
        """
        Return an iterator over header name-value pairs.
        
        Returns:
            Iterator yielding (name, value) tuples
            
        Examples:
            >>> headers = Headers()
            >>> headers.set("Content-Type", "application/json")
            >>> headers.set("Accept", "text/html")
            >>> for name, value in headers:
            ...     print(f"{name}: {value}")
            content-type: application/json
            accept: text/html
        """
        return iter(self._headers.items())

    def stringify(self) -> str:
        """
        Convert headers to a string suitable for an HTTP request.
        
        Returns:
            HTTP headers as a string with CRLF line endings
            
        Examples:
            >>> headers = Headers()
            >>> headers.set("Content-Type", "application/json")
            >>> headers.set("Accept", "text/html")
            >>> print(headers.stringify())
            content-type: application/json
            accept: text/html
        """
        return "\r\n".join(f"{name}: {value}" for name, value in self._headers.items())

    def merge(self, headers: "Headers") -> None:
        """
        Merge headers from another Headers instance.
        
        This will override any existing headers with the same names.
        
        Args:
            headers: Another Headers instance to merge from
            
        Examples:
            >>> headers1 = Headers()
            >>> headers1.set("Content-Type", "application/json")
            >>> 
            >>> headers2 = Headers()
            >>> headers2.set("Accept", "text/html")
            >>> headers2.set("Content-Type", "text/plain")  # Will override
            >>> 
            >>> headers1.merge(headers2)
            >>> headers1.get("Content-Type")
            'text/plain'
            >>> headers1.get("Accept")
            'text/html'
        """
        for name, value in headers:
            self.set(name, value)


__all__ = ["Headers"]
