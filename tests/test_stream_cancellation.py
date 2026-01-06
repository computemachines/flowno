"""Tests for stream cancellation behavior.

WARNING: These tests were written by AI. When debugging, don't assume they are a definitive source of truth.

Stream Cancellation Bug Analysis
================================

This test file includes tests for stream cancellation propagation through intermediate
nodes. The tests in `TestStreamCancellationPropagation` expose several bugs in the
current implementation.

IDENTIFIED PROBLEMS
-------------------

1. **Cancellation Not Reaching Intermediate Producers** (CRITICAL)

   When a consumer cancels a stream and immediately finishes, the producer never
   receives the `StreamCancelled` exception. This is because:

   - Consumer calls `await stream.cancel()` → `StreamCancelCommand` is yielded
   - Event loop stores stream in `_cancelled_streams[producer_node]`
   - Event loop re-queues consumer task (line 1450 in flow.py)
   - Consumer continues, breaks, and returns (task completes)
   - Flow sees no active nodes and terminates
   - Producer never loops back to check `_cancelled_streams`

   Affected tests:
   - `test_cancellation_propagates_through_passthrough_node`
   - `test_cancellation_propagates_through_multiple_passthrough_nodes`

2. **No Automatic Propagation to Input Streams**

   Even if the producer did receive `StreamCancelled`, there's no mechanism to
   automatically cancel the producer's own input streams. A passthrough node
   that receives `StreamCancelled` must manually call `await input_stream.cancel()`
   to propagate the cancellation upstream.

   This is tested in `test_passthrough_manually_cancels_input_on_stream_cancelled`.

3. **Deadlock When One Consumer Cancels Early** (with multiple consumers)

   When one stream consumer cancels while another continues consuming, the flow
   may deadlock. The barrier synchronization gets confused when consumers finish
   at different times due to cancellation.

   Affected test: `test_multiple_consumers_one_cancels`

POTENTIAL SOLUTIONS
-------------------

1. **Force Producer Execution on Cancellation**

   In the `StreamCancelCommand` handler (flow.py lines 1428-1450), uncomment and
   fix the code that resumes the producer:

   ```python
   # After storing in _cancelled_streams, force producer to run:
   if producer_node in self.flow.node_tasks:
       producer_task = self.flow.node_tasks[producer_node].task
       # Add producer to front of queue to process cancellation
       self.tasks.insert(0, (producer_task, None, None))
   ```

2. **Automatic Input Stream Cancellation**

   In `_node_gen_lifecycle` (flow.py line 615), when catching `StreamCancelled`,
   automatically cancel all input streams of the node:

   ```python
   except (StreamCancelled, StopAsyncIteration) as e:
       # If StreamCancelled, propagate to all input streams
       if isinstance(e, StreamCancelled):
           for input_port in node._input_ports.values():
               if input_port.minimum_run_level > 0:  # It's a stream
                   # Need mechanism to cancel input streams here
                   pass
   ```

   Challenge: We need access to the Stream objects for input ports, but they're
   created in `gather_inputs` and may not be easily accessible.

3. **Alternative: Don't Require Explicit Cancellation Handling**

   Simple producer nodes shouldn't need to catch `StreamCancelled`. The framework
   should gracefully handle unhandled `StreamCancelled` exceptions and clean up.
   This already works for direct Source→Consumer connections.

4. **Fix Barrier Synchronization for Mixed Cancellation**

   The barrier system needs to handle the case where some consumers cancel early
   while others continue. Possible approaches:
   - Decrement barrier count when a consumer cancels
   - Don't count cancelled consumers in barrier calculations
   - Track per-consumer cancellation state

NOTES ON SOLVER/RESOLUTION SYSTEM
---------------------------------

The solver and resolution system is complex. Modifying it requires understanding:
- How nodes are scheduled and resumed (ResumeNodesCommand)
- How barriers protect data between generations
- How the resolution queue determines when the flow is complete

Any fix should be carefully tested to ensure it doesn't break the existing
resolution logic or introduce race conditions.
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


class TestStreamCancellationPropagation:
    """Tests for cancellation propagation through intermediate streaming nodes.

    These tests verify the behavior when a consumer cancels a stream and there
    are intermediate "pass-through" nodes between the source and consumer.
    The cancellation should propagate back through all intermediate nodes
    to the original source.
    """

    @pytest.mark.xfail(
        reason="BUG: Cancellation doesn't reach intermediate producers - see docstring for analysis",
        strict=True
    )
    def test_cancellation_propagates_through_passthrough_node(self):
        """Test that cancellation propagates from consumer through passthrough to source.

        Topology: Source -> Pass -> Consume

        When Consume cancels the stream at elem=2, the cancellation should:
        1. Be received by Pass (the immediate producer)
        2. Propagate automatically to Source (Pass's input)

        This is the core bug case: if Pass doesn't handle StreamCancelled,
        does the framework automatically cancel Pass's input streams?

        BUG ANALYSIS:
        The StreamCancelCommand is processed, but the producer (Pass) never sees it
        because after the consumer cancels, it immediately finishes, and the flow
        terminates before Pass can loop back to check _cancelled_streams.

        The fix requires forcing the producer to run after a cancellation is registered,
        even if no other work is pending.
        """
        source_yielded = []
        source_cancelled = False
        pass_received = []
        pass_cancelled = False
        consume_received = []

        @node
        async def Source():
            nonlocal source_cancelled
            try:
                for i in range(5):
                    source_yielded.append(i)
                    yield i
            except StreamCancelled:
                source_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def Pass(stream: Stream[int]):
            """Simple passthrough that doesn't handle StreamCancelled."""
            nonlocal pass_cancelled
            try:
                async for elem in stream:
                    pass_received.append(elem)
                    yield elem
            except StreamCancelled:
                pass_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            total = 0
            async for elem in stream:
                consume_received.append(elem)
                total += elem
                if elem == 2:
                    await stream.cancel()
                    break
            return total

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = Pass(f.source)
            f.consume = Consume(f.passthrough)

        f.run_until_complete()

        # Consumer should have received 0, 1, 2 and cancelled
        assert consume_received == [0, 1, 2], f"Consumer received {consume_received}"
        assert f.consume.get_data() == (3,), "Sum should be 0+1+2=3"

        # Pass should have received the cancellation signal
        assert pass_cancelled, "Pass should have received StreamCancelled"

        # CRITICAL: Source should also receive the cancellation!
        # This is the bug - currently this fails because cancellation
        # doesn't propagate from Pass's output to Pass's input streams.
        assert source_cancelled, (
            "Source should have received StreamCancelled propagated through Pass. "
            "This test exposes the bug: when an intermediate node receives "
            "StreamCancelled and doesn't handle it, the framework should "
            "automatically cancel all of that node's input streams."
        )

    def test_passthrough_manually_cancels_input_on_stream_cancelled(self):
        """Test workaround: passthrough explicitly cancels its input stream.

        This demonstrates how a passthrough node can catch StreamCancelled
        and manually cancel its own input stream to propagate cancellation upstream.
        """
        source_yielded = []
        source_cancelled = False
        consume_received = []

        @node
        async def Source():
            nonlocal source_cancelled
            try:
                for i in range(5):
                    source_yielded.append(i)
                    yield i
            except StreamCancelled:
                source_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def PassWithManualCancel(stream: Stream[int]):
            """Passthrough that manually cancels input on StreamCancelled."""
            try:
                async for elem in stream:
                    yield elem
            except StreamCancelled:
                # Manually propagate cancellation to input stream
                await stream.cancel()
                raise

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            total = 0
            async for elem in stream:
                consume_received.append(elem)
                total += elem
                if elem == 2:
                    await stream.cancel()
                    break
            return total

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = PassWithManualCancel(f.source)
            f.consume = Consume(f.passthrough)

        f.run_until_complete()

        assert consume_received == [0, 1, 2]
        assert f.consume.get_data() == (3,)

        # With manual cancellation, source should be cancelled
        assert source_cancelled, (
            "Source should receive StreamCancelled when Pass manually cancels it"
        )

    @pytest.mark.xfail(
        reason="BUG: Cancellation doesn't reach intermediate producers in chain",
        strict=True
    )
    def test_cancellation_propagates_through_multiple_passthrough_nodes(self):
        """Test cancellation propagation through a chain of passthrough nodes.

        Topology: Source -> Pass1 -> Pass2 -> Consume

        When Consume cancels, cancellation should propagate through
        Pass2 -> Pass1 -> Source.

        This test extends the basic propagation test to verify that cancellation
        works through multiple intermediate nodes, not just one.
        """
        source_cancelled = False
        pass1_cancelled = False
        pass2_cancelled = False

        @node
        async def Source():
            nonlocal source_cancelled
            try:
                for i in range(5):
                    yield i
            except StreamCancelled:
                source_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def Pass1(stream: Stream[int]):
            nonlocal pass1_cancelled
            try:
                async for elem in stream:
                    yield elem
            except StreamCancelled:
                pass1_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def Pass2(stream: Stream[int]):
            nonlocal pass2_cancelled
            try:
                async for elem in stream:
                    yield elem
            except StreamCancelled:
                pass2_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            async for elem in stream:
                if elem == 1:
                    await stream.cancel()
                    break
            return elem

        with FlowHDL() as f:
            f.source = Source()
            f.pass1 = Pass1(f.source)
            f.pass2 = Pass2(f.pass1)
            f.consume = Consume(f.pass2)

        f.run_until_complete()

        assert pass2_cancelled, "Pass2 should receive StreamCancelled"
        assert pass1_cancelled, "Pass1 should receive propagated StreamCancelled"
        assert source_cancelled, "Source should receive propagated StreamCancelled"

    def test_simple_producer_without_cancellation_handling(self):
        """Test if a simple producer can omit StreamCancelled handling.

        Ideally, a simple producer node shouldn't need to wrap its
        generator in try/except StreamCancelled. The framework should
        gracefully handle the case where StreamCancelled propagates
        naturally.
        """
        yielded = []

        @node
        async def SimpleSource():
            """Simple producer with no exception handling."""
            for i in range(5):
                yielded.append(i)
                yield i

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            async for elem in stream:
                if elem == 2:
                    await stream.cancel()
                    break
            return elem

        with FlowHDL() as f:
            f.source = SimpleSource()
            f.consume = Consume(f.source)

        # This should complete without error even though SimpleSource
        # doesn't catch StreamCancelled
        f.run_until_complete()

        assert f.consume.get_data() == (2,)
        # Source may have yielded more before cancellation was processed
        assert 2 in yielded

    def test_producer_returns_final_value_after_cancellation(self):
        """Test that a producer can return a final value after being cancelled.

        When StreamCancelled is caught, the producer should be able to
        clean up and return a final value.
        """
        @node
        async def Source():
            try:
                for i in range(10):
                    yield i
            except StreamCancelled:
                pass
            # Return final value after cancellation
            raise StopAsyncIteration(("cancelled_at", 2))

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            async for elem in stream:
                if elem == 2:
                    await stream.cancel()
                    break

        @node
        async def FinalConsumer(data):
            return data

        with FlowHDL() as f:
            f.source = Source()
            Consume(f.source)
            f.final = FinalConsumer(f.source)

        f.run_until_complete()

        # The final consumer should receive the cancellation value
        assert f.final.get_data() == (("cancelled_at", 2),)

    def test_passthrough_transforms_data_before_cancellation(self):
        """Test passthrough that transforms data before cancellation occurs."""
        transformed = []

        @node
        async def Source():
            for i in range(5):
                yield i

        @node(stream_in=["stream"])
        async def DoublePass(stream: Stream[int]):
            """Doubles each value before passing through."""
            async for elem in stream:
                doubled = elem * 2
                transformed.append(doubled)
                yield doubled

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            total = 0
            async for elem in stream:
                total += elem
                if elem == 4:  # This is 2 * 2
                    await stream.cancel()
                    break
            return total

        with FlowHDL() as f:
            f.source = Source()
            f.double = DoublePass(f.source)
            f.consume = Consume(f.double)

        f.run_until_complete()

        # 0*2=0, 1*2=2, 2*2=4, then cancel
        assert 0 in transformed
        assert 2 in transformed
        assert 4 in transformed
        # Sum: 0 + 2 + 4 = 6
        assert f.consume.get_data() == (6,)

    def test_cancellation_with_buffered_passthrough(self):
        """Test cancellation when passthrough has buffered elements.

        This tests the case where the passthrough has consumed more
        elements from Source than it has yielded to Consumer.
        """
        source_yielded = []
        source_cancelled = False
        pass_consumed = []
        pass_yielded = []
        consumer_received = []

        @node
        async def Source():
            nonlocal source_cancelled
            try:
                for i in range(10):
                    source_yielded.append(i)
                    yield i
            except StreamCancelled:
                source_cancelled = True
                raise

        @node(stream_in=["stream"])
        async def BufferingPass(stream: Stream[int]):
            """Passthrough that buffers 2 elements before yielding."""
            buffer = []
            async for elem in stream:
                pass_consumed.append(elem)
                buffer.append(elem)
                if len(buffer) >= 2:
                    value = buffer.pop(0)
                    pass_yielded.append(value)
                    yield value
            # Flush remaining buffer
            for value in buffer:
                pass_yielded.append(value)
                yield value

        @node(stream_in=["stream"])
        async def Consume(stream: Stream[int]):
            async for elem in stream:
                consumer_received.append(elem)
                if elem == 1:
                    await stream.cancel()
                    break
            return elem

        with FlowHDL() as f:
            f.source = Source()
            f.buffer = BufferingPass(f.source)
            f.consume = Consume(f.buffer)

        f.run_until_complete()

        # Consumer received 0, then 1, then cancelled
        assert consumer_received == [0, 1]
        # Buffer had consumed at least 0, 1, 2 (2 to fill buffer, then yield 0)
        assert len(pass_consumed) >= 3

    @pytest.mark.xfail(
        reason="BUG: Deadlock/timeout when one consumer cancels while another continues",
        strict=True
    )
    def test_multiple_consumers_one_cancels(self):
        """Test that cancellation from one consumer doesn't affect another.

        Topology::

                    Source
                   /      \\
            Consumer1    Consumer2

        Consumer1 cancels early, Consumer2 continues to completion.

        BUG ANALYSIS:
        This test times out due to barrier synchronization issues. When Consumer1
        cancels early, the barrier system still expects it to decrement counts,
        but it has already finished. This leads to a deadlock where Consumer2
        waits forever for the barrier.

        The fix requires updating barrier management to handle early-cancelled
        consumers properly.
        """
        consumer1_items = []
        consumer2_items = []

        @node
        async def Source():
            for i in range(5):
                yield i

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream[int]):
            async for elem in stream:
                consumer1_items.append(elem)
                if elem == 1:
                    await stream.cancel()
                    break
            return elem

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream[int]):
            async for elem in stream:
                consumer2_items.append(elem)
            return sum(consumer2_items)

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = Consumer1(f.source)
            f.c2 = Consumer2(f.source)

        f.run_until_complete()

        # Consumer1 should have cancelled after seeing 1
        assert consumer1_items == [0, 1]
        # Consumer2 should receive all items
        assert consumer2_items == [0, 1, 2, 3, 4]

    def test_diamond_topology_with_cancellation(self):
        r"""Test cancellation in diamond topology.

        Topology::

                Source
               /      \
            Pass1    Pass2
               \      /
               Consumer

        Consumer receives from both Pass1 and Pass2.
        """
        source_items = []
        pass1_items = []
        pass2_items = []

        @node
        async def Source():
            for i in range(5):
                source_items.append(i)
                yield i

        @node(stream_in=["stream"])
        async def Pass1(stream: Stream[int]):
            async for elem in stream:
                pass1_items.append(elem)
                yield elem

        @node(stream_in=["stream"])
        async def Pass2(stream: Stream[int]):
            async for elem in stream:
                pass2_items.append(elem)
                yield elem * 10

        @node(stream_in=["a", "b"])
        async def Consumer(a: Stream[int], b: Stream[int]):
            """Consumes from two streams and cancels when sum threshold reached."""
            total = 0
            # Alternate between streams
            a_iter = a.__aiter__()
            b_iter = b.__aiter__()
            try:
                while True:
                    elem_a = await a_iter.__anext__()
                    total += elem_a
                    if total > 5:
                        await a.cancel()
                        await b.cancel()
                        break
                    elem_b = await b_iter.__anext__()
                    total += elem_b
                    if total > 5:
                        await a.cancel()
                        await b.cancel()
                        break
            except StopAsyncIteration:
                pass
            return total

        with FlowHDL() as f:
            f.source = Source()
            f.p1 = Pass1(f.source)
            f.p2 = Pass2(f.source)
            f.consumer = Consumer(f.p1, f.p2)

        f.run_until_complete()

        # Consumer should have cancelled when total > 5
        # 0 + 0 + 1 + 10 = 11 > 5, so cancels
        assert f.consumer.get_data()[0] > 5
