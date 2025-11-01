Only run non `network` marked tests. E.g. `uv run pytest -m "not network"`.
Only run tests when ready for release or when completely baffled by a bug. 

This framework does NOT use asyncio. Check the docs for details on how to execute async code with the bare flowno EventLoop.