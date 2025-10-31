Only run non `network` marked tests. E.g. `uv run pytest -m "not network"`.
Only run tests when ready for release or when completely baffled by a bug. 

CURRENT GOAL: stream cancellation
Manual testing instructions:
Run `timeout --signal=INT 15 uv run python stream_cancel_example.py`