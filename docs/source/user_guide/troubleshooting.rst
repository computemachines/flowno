Troubleshooting
===============

- **Type Checking Support**: Optional type annotations in `@node` async functions are passed through to the `Node` instances. This allows for static type checking of the flow with tools like Pyright or MyPy.
  * Note: Pyright version 1.1.167 crashes when type checking Flowno. Same as: [pyright/issues/8137](https://github.com/microsoft/pyright/issues/8137).
