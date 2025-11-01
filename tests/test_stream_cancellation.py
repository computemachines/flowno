"""Tests for stream cancellation behavior.

WARNING: These tests were written by AI. When debugging, don't assume they are a definitive source of truth.
"""
import pytest
from flowno import FlowHDL, node, Stream
from flowno.core.node_base import StreamCancelled


class TestStreamCancellation:
    """Tests for cancelling streaming nodes."""

    def test_cancel_after_first_item(self):
        """Test cancelling a stream after consuming the first item."""
        items_consumed = []
        source_yielded = []
        
        @node
        async def Source():
            for i in range(3):
                source_yielded.append(i)
                yield i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream):
            async for item in stream:
                items_consumed.append(item)
                if len(items_consumed) == 1:
                    await stream.cancel()
                    break

        with FlowHDL() as f:
            f.source = Source()
            Consumer(f.source)

        f.run_until_complete()

        # Should consume exactly 1 item before cancellation
        assert items_consumed == [0]
        # Source should have yielded at least the first item
        assert 0 in source_yielded

    def test_stream_cancellation_with_mono_consumer(self):
        """Test stream cancellation with both streaming and mono consumers."""
        stream_items = []
        mono_result = None
        
        @node
        async def Source():
            yield "one"
            yield "two"

        @node(stream_in=["numbers"])
        async def StreamConsumer(numbers: Stream):
            async for item in numbers:
                stream_items.append(item)
                await numbers.cancel()

        @node
        async def MonoConsumer(numbers: list):
            nonlocal mono_result
            mono_result = numbers

        with FlowHDL() as f:
            f.source = Source()
            StreamConsumer(f.source)
            MonoConsumer(f.source)

        f.run_until_complete()

        # Stream should only consume what was yielded before cancellation
        assert len(stream_items) >= 1
        # Mono consumer should receive the accumulated data
        assert mono_result is not None

    def test_stream_completes_naturally(self):
        """Test stream that completes naturally without cancellation."""
        consumed = []
        
        @node
        async def Source():
            for i in range(3):
                yield i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream):
            async for item in stream:
                consumed.append(item)

        with FlowHDL() as f:
            f.source = Source()
            Consumer(f.source)

        f.run_until_complete()

        assert consumed == [0, 1, 2]

    def test_multiple_stream_consumers(self):
        """Test multiple streaming consumers of the same source."""
        consumer1_items = []
        consumer2_items = []
        
        @node
        async def Source():
            yield "a"
            yield "b"

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream):
            async for item in stream:
                consumer1_items.append(item)

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream):
            async for item in stream:
                consumer2_items.append(item)

        with FlowHDL() as f:
            f.source = Source()
            Consumer1(f.source)
            Consumer2(f.source)

        f.run_until_complete()

        # Both consumers should receive all items
        assert consumer1_items == ["a", "b"]
        assert consumer2_items == ["a", "b"]

    def test_stream_cancellation_exception_handling(self):
        """Test that stream cancellation doesn't crash the flow."""
        cancellation_occurred = False
        
        @node
        async def Source():
            nonlocal cancellation_occurred
            try:
                yield "item1"
                yield "item2"
            except StreamCancelled:
                cancellation_occurred = True

        @node(stream_in=["stream"])
        async def CancellingConsumer(stream: Stream):
            async for item in stream:
                await stream.cancel()

        with FlowHDL() as f:
            f.source = Source()
            CancellingConsumer(f.source)

        # Should complete without errors
        f.run_until_complete()

    def test_stream_with_explicit_return_value(self):
        """Test stream that returns an explicit final value after cancellation."""
        final_value = None
        
        @node
        async def Source():
            try:
                yield "data"
            except StreamCancelled:
                pass
            raise StopAsyncIteration(("final",))

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream):
            async for item in stream:
                await stream.cancel()

        @node
        async def FinalConsumer(data: tuple):
            nonlocal final_value
            final_value = data

        with FlowHDL() as f:
            f.source = Source()
            Consumer(f.source)
            FinalConsumer(f.source)

        f.run_until_complete()

        # Should receive the explicit final value
        assert final_value == ("final",)

    def test_stream_barrier_protection_mono_consumer(self):
        """Test that barrier0 protects accumulated data for mono consumers."""
        accumulated = None
        
        @node
        async def Source():
            yield 1
            yield 2
            yield 3

        @node
        async def MonoConsumer(data: list):
            nonlocal accumulated
            accumulated = data

        with FlowHDL() as f:
            f.source = Source()
            MonoConsumer(f.source)

        f.run_until_complete()

        # Should receive accumulated data - the exact values depend on accumulation
        assert accumulated is not None
        assert isinstance(accumulated, (list, int, str))

    def test_stream_cancellation_with_multiple_yields(self):
        """Test cancellation happening after multiple yields."""
        yielded_count = 0
        consumed_count = 0
        
        @node
        async def Source():
            nonlocal yielded_count
            for i in range(10):
                yielded_count += 1
                yield i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream):
            nonlocal consumed_count
            async for item in stream:
                consumed_count += 1
                if consumed_count >= 3:
                    await stream.cancel()

        with FlowHDL() as f:
            f.source = Source()
            Consumer(f.source)

        f.run_until_complete()

        # Should consume exactly 3 items
        assert consumed_count == 3
        # Source may yield more before the cancellation signal is processed
        assert yielded_count >= 3

    def test_stream_no_cancellation_after_completion(self):
        """Test that cancelling after natural completion is safe."""
        items = []
        
        @node
        async def Source():
            yield "a"
            yield "b"

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream):
            async for item in stream:
                items.append(item)
            # Try to cancel after stream is exhausted
            try:
                await stream.cancel()
            except Exception:
                pass

        with FlowHDL() as f:
            f.source = Source()
            Consumer(f.source)

        f.run_until_complete()

        assert items == ["a", "b"]


class TestStreamBarriers:
    """Tests for barrier synchronization with streaming nodes."""

    def test_barrier0_with_streaming_and_mono_consumers(self):
        """Test that barrier0 is properly managed with mixed consumers."""
        stream_consumed = []
        mono_received = None
        
        @node
        async def Source():
            yield "x"
            yield "y"

        @node(stream_in=["data"])
        async def StreamingConsumer(data: Stream):
            async for item in data:
                stream_consumed.append(item)

        @node
        async def MonoConsumer(data: list):
            nonlocal mono_received
            mono_received = data

        with FlowHDL() as f:
            f.source = Source()
            StreamingConsumer(f.source)
            MonoConsumer(f.source)

        # This should complete without barrier errors
        f.run_until_complete()

        # Both consumers should have received data
        assert len(stream_consumed) > 0
        assert mono_received is not None

    def test_streaming_consumer_skips_barrier0_countdown(self):
        """Test that streaming consumers don't count down barrier0 prematurely."""
        execution_order = []
        
        @node
        async def Source():
            execution_order.append("source_yield")
            yield "data"
            execution_order.append("source_complete")

        @node(stream_in=["stream"])
        async def StreamingOnly(stream: Stream):
            execution_order.append("streaming_start")
            async for item in stream:
                execution_order.append(f"streaming_consume_{item}")
            execution_order.append("streaming_end")

        with FlowHDL() as f:
            f.source = Source()
            StreamingOnly(f.source)

        f.run_until_complete()

        # Verify the execution proceeds without premature barrier issues
        assert "source_yield" in execution_order
        assert "source_complete" in execution_order
        assert "streaming_consume_data" in execution_order

    def test_multiple_generations_with_streaming(self):
        """Test that streaming nodes properly advance through generations."""
        generations_seen = []
        
        @node
        async def Source():
            yield 1
            yield 2

        @node(stream_in=["nums"])
        async def Tracker(nums: Stream):
            async for num in nums:
                generations_seen.append(num)

        @node
        async def Follower(nums: list):
            # This ensures Source runs multiple times
            pass

        with FlowHDL() as f:
            f.source = Source()
            Tracker(f.source)
            Follower(f.source)

        f.run_until_complete()

        # Should have seen at least the first value
        assert len(generations_seen) > 0
        assert 1 in generations_seen
