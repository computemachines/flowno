"""Scenario-based tests for stream cancellation behavior.

These tests explore the correct behavior of stream cancellation in various
topologies and timing situations. They use manual __aiter__/__anext__ calls
where timing matters, to make the execution order explicit.

The goal is to understand and document the correct behavior, not just
what currently happens.
"""
import pytest
from flowno import FlowHDL, node, Stream
from flowno.core.node_base import StreamCancelled
from flowno.core.event_loop.primitives import sleep


class TestScenario1_DirectCancellation:
    """Scenario 1: Simple Source -> Consumer, consumer cancels and returns.

    Key question: Does the source receive StreamCancelled before flow terminates?

    Current understanding: When consumer calls cancel() and returns immediately,
    the flow may terminate before the source can process the cancellation.
    For a direct connection (no intermediate nodes), does this work?
    """

    def test_direct_cancel_consumer_returns_immediately(self):
        """Consumer cancels and returns in the same iteration."""
        source_events = []

        @node
        async def Source():
            try:
                for i in range(5):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise
            finally:
                source_events.append("finally")

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()

            # Read first value
            val0 = await it.__anext__()
            assert val0 == 0

            # Cancel and return immediately
            await stream.cancel()
            return val0

        with FlowHDL() as f:
            f.source = Source()
            f.consumer = Consumer(f.source)

        f.run_until_complete()

        assert f.consumer.get_data() == (0,)
        # Question: Should source_events contain "cancelled"?
        # Current behavior: probably not, flow terminates first

        # HUMAN COMMENT: Source event should eventually have a "finally" entry, but we can worry about that later.
        print(f"Source events: {source_events}")

    def test_direct_cancel_consumer_reads_after_cancel(self):
        """Consumer cancels, then tries to read again (should get StopAsyncIteration)."""
        source_events = []
        consumer_events = []

        @node
        async def Source():
            try:
                for i in range(5):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()

            val0 = await it.__anext__()
            consumer_events.append(f"read_{val0}")

            await stream.cancel()
            consumer_events.append("cancelled")

            # Try to read again - what happens?
            try:
                val1 = await it.__anext__()
                consumer_events.append(f"read_{val1}")
            except StopAsyncIteration:
                consumer_events.append("stop_iteration")

            return val0

        with FlowHDL() as f:
            f.source = Source()
            f.consumer = Consumer(f.source)

        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"Consumer events: {consumer_events}")
        # Expected: after cancel, next read should raise StopAsyncIteration


class TestScenario3_TwoConsumersOneCancels:
    """Scenario 3: One producer, two streaming consumers, one cancels.

    Topology:
        Source
       /      \
      C1       C2

    Key questions:
    - When C1 cancels, should Source stop producing?
    - Should C2 be affected by C1's cancellation?
    - What happens to barriers?
    """

    def test_c1_cancels_before_c2_reads_first_value(self):
        """C1 reads (0,0), cancels. C2 hasn't read yet."""
        source_events = []
        c1_events = []
        c2_events = []

        @node
        async def Source():
            try:
                for i in range(3):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def C1(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            c1_events.append(f"read_{val}")
            await stream.cancel()
            c1_events.append("cancelled")
            return val

        @node(stream_in=["stream"])
        async def C2(stream: Stream[int]):
            # C2 reads all values without cancelling
            async for val in stream:
                c2_events.append(f"read_{val}")
            return len(c2_events)

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = C1(f.source)
            f.c2 = C2(f.source)

        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"C1 events: {c1_events}")
        print(f"C2 events: {c2_events}")

        # Expected behavior:
        # - C1 reads (0,0), cancels, returns
        # - C2 should still be able to read all values
        # - Source should NOT receive StreamCancelled until C2 is also done

        # HUMAN COMMENT: This is incorrect behavior. Source should get cancelled after C1 cancels, regardless of C2.

    def test_c1_cancels_after_c2_stalls_for_next(self):
        """C1 and C2 both read (0,0). C2 stalls for (0,1). C1 cancels."""
        c1_events = []
        c2_events = []

        @node
        async def Source():
            for i in range(3):
                yield i

        @node(stream_in=["stream"])
        async def C1(stream: Stream[int]):
            it = stream.__aiter__()

            # Read first value
            val0 = await it.__anext__()
            c1_events.append(f"read_{val0}")

            # Small delay to let C2 stall
            await sleep(0.01)

            # Cancel
            await stream.cancel()
            c1_events.append("cancelled")
            return val0

        @node(stream_in=["stream"])
        async def C2(stream: Stream[int]):
            it = stream.__aiter__()

            # Read first value
            val0 = await it.__anext__()
            c2_events.append(f"read_{val0}")

            # Try to read second value (will stall if not available)
            try:
                val1 = await it.__anext__()
                c2_events.append(f"read_{val1}")
            except StopAsyncIteration:
                c2_events.append("stop_iteration")

            return val0

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = C1(f.source)
            f.c2 = C2(f.source)

        f.run_until_complete()

        print(f"C1 events: {c1_events}")
        print(f"C2 events: {c2_events}")

        # Question: What should happen to C2's read of (0,1)?
        # - Should it succeed (Source produces more)?
        # - Should it fail with StopAsyncIteration (Source cancelled)?

        # HUMAN COMMENT: C2 should get StopAsyncIteration after C1 cancels, either directly or whenever it is resumed for whatever reason.

    def test_both_consumers_cancel_same_generation(self):
        """Both C1 and C2 read (0,0), then both cancel."""
        source_events = []

        @node
        async def Source():
            try:
                for i in range(3):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def C1(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        @node(stream_in=["stream"])
        async def C2(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = C1(f.source)
            f.c2 = C2(f.source)

        f.run_until_complete()

        print(f"Source events: {source_events}")

        # Expected: Source should receive StreamCancelled exactly once


class TestScenario5_ChainWithPassthrough:
    """Scenario 5: Source -> Pass -> Consumer, consumer cancels.

    Key questions:
    - Does Pass receive StreamCancelled?
    - Does Source receive StreamCancelled?
    - Who is responsible for propagating cancellation upstream?
    """

    def test_passthrough_receives_cancellation(self):
        """Basic test: does Pass even see the cancellation?"""
        source_events = []
        pass_events = []

        @node
        async def Source():
            try:
                for i in range(5):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def Pass(stream: Stream[int]):
            try:
                async for val in stream:
                    pass_events.append(f"forward_{val}")
                    yield val
            except StreamCancelled:
                pass_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = Pass(f.source)
            f.consumer = Consumer(f.passthrough)

        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"Pass events: {pass_events}")

        # Key assertion: Pass should receive StreamCancelled
        assert "cancelled" in pass_events, "Pass should receive StreamCancelled"

        # HUMAN COMMENT:
        # This is far more complicate and there are multiple possible behaviors.
        # Let me think it through starting from the consumer cancelling.
        # 1. Consumer calls cancel() on Pass's stream.
        # 2. Pass is marked as cancelled, and on next yield it raises StreamCancelled, but it does not get added to the resolution queue yet.
        # 3. The event loop returns control to Consumer, which returns from its node function.
        # 4. The resolution queue is empty, so the flow terminates.
        # OR
        # 1. Consumer calls cancel() on Pass's stream.
        # 2. The event loop calls aclose on Pass's generator. (Involves possibly removing the StreamCancelled concept entrirely?)
        # 3. Pass handles the GeneratorExit instead of StreamCancelled. Maybe StreamCancelled could be a subclass of GeneratorExit?
        # 4. If Pass wants to propagate cancellation, it calls cancel() on its input stream.
        #    OR it ignores the GeneratorExit. Can that be detected from the event loop?
        # 5. If Pass's input stream is also cancelled, the cycle continues upstream. Every node gets a chance to clean up.
        # OR
        # 1. Consumer calls cancel() on Pass's stream.
        # 2. Pass is marked as cancelled, and on next resume it is injected StreamCancelled or GeneratorExit.
        # 3. Pass handles it or lets it propagate to the event loop.
        # 4. The event loop repeats this process upstream if also cancelled.


    def test_passthrough_propagates_to_source(self):
        """When Pass receives StreamCancelled, does Source also get it?

        This tests whether the framework automatically propagates cancellation
        to input streams, or if Pass must do it manually.
        """
        source_events = []
        pass_events = []

        @node
        async def Source():
            try:
                for i in range(5):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def Pass(stream: Stream[int]):
            # Pass does NOT manually cancel its input
            try:
                async for val in stream:
                    pass_events.append(f"forward_{val}")
                    yield val
            except StreamCancelled:
                pass_events.append("cancelled")
                # Note: NOT calling stream.cancel() here
                raise

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = Pass(f.source)
            f.consumer = Consumer(f.passthrough)

        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"Pass events: {pass_events}")

        # Question: Should Source automatically receive cancellation?
        # Or must Pass explicitly call stream.cancel()?

        # HUMAN COMMENT: See above human comment. I want to allow implicit propagation, but can live without it for now.

    def test_passthrough_manual_propagation(self):
        """Pass explicitly cancels its input stream when it receives StreamCancelled."""
        source_events = []
        pass_events = []

        @node
        async def Source():
            try:
                for i in range(5):
                    source_events.append(f"yield_{i}")
                    yield i
            except StreamCancelled:
                source_events.append("cancelled")
                raise

        @node(stream_in=["stream"])
        async def Pass(stream: Stream[int]):
            try:
                async for val in stream:
                    pass_events.append(f"forward_{val}")
                    yield val
            except StreamCancelled:
                pass_events.append("cancelled")
                # Manually propagate cancellation
                await stream.cancel()
                pass_events.append("propagated")
                raise

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = Pass(f.source)
            f.consumer = Consumer(f.passthrough)

        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"Pass events: {pass_events}")

        # With manual propagation, Source should receive cancellation
        assert "cancelled" in source_events, "Source should receive cancellation"


class TestScenario6_ReadAfterCancelOnChain:
    """Scenario 6: What happens when nodes try to read after cancellation?

    After cancellation, repeated stream reads should get StopAsyncIteration,
    not stall and demand more data.
    """

    def test_consumer_reads_after_cancel(self):
        """Consumer cancels, then tries multiple reads."""
        consumer_events = []

        @node
        async def Source():
            for i in range(5):
                yield i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()

            val0 = await it.__anext__()
            consumer_events.append(f"read_{val0}")

            await stream.cancel()
            consumer_events.append("cancelled")

            # Try multiple reads after cancel
            for attempt in range(3):
                try:
                    val = await it.__anext__()
                    consumer_events.append(f"read_{val}")
                except StopAsyncIteration:
                    consumer_events.append(f"stop_{attempt}")
                    break

            return val0

        with FlowHDL() as f:
            f.source = Source()
            f.consumer = Consumer(f.source)

        f.run_until_complete()

        print(f"Consumer events: {consumer_events}")

        # Expected: after cancel, reads should get StopAsyncIteration

    def test_passthrough_reads_after_downstream_cancel(self):
        """Passthrough tries to read after its downstream consumer cancelled."""
        pass_events = []

        @node
        async def Source():
            for i in range(5):
                yield i

        @node(stream_in=["stream"])
        async def Pass(stream: Stream[int]):
            it = stream.__aiter__()

            try:
                while True:
                    val = await it.__anext__()
                    pass_events.append(f"read_{val}")
                    yield val
            except StopAsyncIteration:
                pass_events.append("source_exhausted")
            except StreamCancelled:
                pass_events.append("cancelled_at_yield")
                # What happens if we try to read more?
                try:
                    more = await it.__anext__()
                    pass_events.append(f"read_after_cancel_{more}")
                except StopAsyncIteration:
                    pass_events.append("stop_after_cancel")
                raise

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.passthrough = Pass(f.source)
            f.consumer = Consumer(f.passthrough)

        f.run_until_complete()

        print(f"Pass events: {pass_events}")


class TestBarrierBehavior:
    """Tests focused on understanding barrier behavior with cancellation.

    The barrier prevents a producer from overwriting data before all consumers
    have read it. When a consumer cancels, what happens to the barrier?
    """

    def test_barrier_with_single_consumer_cancel(self):
        """Single consumer cancels - does producer get stuck on barrier?"""
        source_events = []

        @node
        async def Source():
            for i in range(3):
                source_events.append(f"pre_yield_{i}")
                yield i
                source_events.append(f"post_yield_{i}")

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        with FlowHDL() as f:
            f.source = Source()
            f.consumer = Consumer(f.source)

        f.run_until_complete()

        print(f"Source events: {source_events}")

        # If source has post_yield_0, it means barrier was released after consumer read
        # Question: does source try to yield again after consumer cancelled?

    def test_barrier_with_two_consumers_one_cancels(self):
        """Two consumers, one cancels after reading. Does barrier deadlock?"""
        source_events = []

        @node
        async def Source():
            for i in range(3):
                source_events.append(f"pre_yield_{i}")
                yield i
                source_events.append(f"post_yield_{i}")

        @node(stream_in=["stream"])
        async def C1(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            # C1 reads one value and cancels
            await stream.cancel()
            return val

        @node(stream_in=["stream"])
        async def C2(stream: Stream[int]):
            # C2 wants to read all values
            total = 0
            async for val in stream:
                total += val
            return total

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = C1(f.source)
            f.c2 = C2(f.source)

        # This might timeout if barrier deadlocks
        f.run_until_complete()

        print(f"Source events: {source_events}")
        print(f"C1 result: {f.c1.get_data()}")
        print(f"C2 result: {f.c2.get_data()}")


class TestCancellationSemantics:
    """Tests exploring the semantic meaning of cancellation.

    Cancellation means: "This is the last data I want from this stream
    in this run-level-0 generation."
    """

    def test_cancel_means_no_more_data_for_me(self):
        """After cancel, consumer should not receive more data."""
        consumer_vals = []

        @node
        async def Source():
            for i in range(10):
                yield i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            it = stream.__aiter__()

            for _ in range(3):
                try:
                    val = await it.__anext__()
                    consumer_vals.append(val)
                except StopAsyncIteration:
                    break

            await stream.cancel()

            # Try to read more after cancel
            for _ in range(3):
                try:
                    val = await it.__anext__()
                    consumer_vals.append(("after_cancel", val))
                except StopAsyncIteration:
                    consumer_vals.append("stop")
                    break

            return consumer_vals

        with FlowHDL() as f:
            f.source = Source()
            f.consumer = Consumer(f.source)

        f.run_until_complete()

        print(f"Consumer vals: {consumer_vals}")

        # After cancel, should only see StopAsyncIteration, not more values

    def test_cancel_with_mono_consumer_downstream(self):
        """Streaming consumer cancels, but there's a mono consumer too.

        Topology:
            Source (streaming)
           /      \
          C1       C2
          (stream) (mono - wants final accumulated value)

        When C1 cancels, C2 still needs Source's final value.
        """
        @node
        async def Source():
            for i in range(5):
                yield i
            # Accumulated value will be [0,1,2,3,4] or sum

        @node(stream_in=["stream"])
        async def C1_Stream(stream: Stream[int]):
            it = stream.__aiter__()
            val = await it.__anext__()
            await stream.cancel()
            return val

        @node
        async def C2_Mono(data):
            # C2 receives the final/accumulated value from Source
            return f"mono_received: {data}"

        with FlowHDL() as f:
            f.source = Source()
            f.c1 = C1_Stream(f.source)
            f.c2 = C2_Mono(f.source)

        f.run_until_complete()

        print(f"C1 result: {f.c1.get_data()}")
        print(f"C2 result: {f.c2.get_data()}")

        # Question: What does C2 receive?
        # - The value at time of cancel?
        # - The full accumulated value (if Source finished naturally)?
        # - Something else?


class TestCycleCancellation:
    """Test that cancellation state is properly cleared between generations in cycles.

    Key concern: If _consumers_that_cancelled is not cleared between generations,
    a consumer that cancelled in generation 0 would be broken in generation 1.
    """

    def test_streaming_cycle_cancel_first_gen_continue_second(self):
        """Cancel stream in first generation, verify second generation works.

        Topology: Source -> Consumer (with streaming edge, defaulted on back edge)

        Gen 0: Consumer cancels after first item
        Gen 1: Consumer should read all items normally
        """
        from flowno.core.flow.flow import TerminateLimitReached
        from pytest import raises

        gen_events = []

        @node
        async def Source(prev_result: int = 0):
            """Yields items based on generation."""
            gen_events.append(f"source_start_{prev_result}")
            for i in range(3):
                gen_events.append(f"source_yield_{i}")
                yield prev_result + i
            gen_events.append("source_complete")

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            """Cancels on first gen, reads fully on subsequent gens."""
            gen_events.append("consumer_start")
            items = []
            it = stream.__aiter__()

            # Read first item
            try:
                val = await it.__anext__()
                items.append(val)
                gen_events.append(f"consumer_read_{val}")
            except StopAsyncIteration:
                gen_events.append("consumer_empty")
                return sum(items)

            # On first generation (items will be [0]), cancel
            # On subsequent generations, continue reading
            if len(gen_events) < 10:  # Heuristic for first gen
                gen_events.append("consumer_cancel")
                await stream.cancel()
            else:
                # Read remaining items
                try:
                    while True:
                        val = await it.__anext__()
                        items.append(val)
                        gen_events.append(f"consumer_read_{val}")
                except StopAsyncIteration:
                    pass

            gen_events.append(f"consumer_done_{items}")
            return sum(items)

        with FlowHDL() as f:
            f.source = Source(f.consumer)
            f.consumer = Consumer(f.source)

        # Run for 2 generations
        with raises(TerminateLimitReached):
            f.run_until_complete(stop_at_node_generation={f.consumer: (1,)})

        # Verify gen 0 had cancellation
        assert "consumer_cancel" in gen_events, "Consumer should have cancelled in gen 0"

        # Verify gen 1 was able to read items (cancellation state was cleared)
        # Look for multiple reads after the cancel event
        cancel_idx = gen_events.index("consumer_cancel")
        reads_after_cancel = [e for e in gen_events[cancel_idx:] if e.startswith("consumer_read_")]
        assert len(reads_after_cancel) >= 2, f"Expected reads in gen 1, got: {reads_after_cancel}"

    def test_streaming_cycle_with_mono_backedge_cancel_persists(self):
        """Test cycle with streaming forward edge and mono back edge.

        Topology:
            Source --stream--> Consumer
               ^                  |
               |___mono___________|

        If Consumer cancels the stream in gen 0, does it work in gen 1?
        """
        from flowno.core.flow.flow import TerminateLimitReached
        from pytest import raises

        source_gens = []
        consumer_gens = []

        @node
        async def Source(feedback: int = 0):
            source_gens.append(feedback)
            for i in range(3):
                yield feedback + i

        @node(stream_in=["stream"])
        async def Consumer(stream: Stream[int]):
            consumer_gens.append("start")
            items = []
            gen_num = len(consumer_gens)

            async for item in stream:
                items.append(item)
                if gen_num == 1 and len(items) == 1:
                    # Cancel on first gen after first item
                    await stream.cancel()
                    break

            consumer_gens.append(f"done_{items}")
            return items[0] if items else -1  # Return first item as feedback

        with FlowHDL() as f:
            f.source = Source(f.consumer)
            f.consumer = Consumer(f.source)

        with raises(TerminateLimitReached):
            f.run_until_complete(stop_at_node_generation={f.consumer: (1,)})

        print(f"Source gens: {source_gens}")
        print(f"Consumer gens: {consumer_gens}")

        # Gen 0: Consumer reads [0], cancels, returns 0
        # Gen 1: Consumer should read normally (e.g., [0, 1, 2] with feedback=0)
        assert len(consumer_gens) >= 3, f"Expected at least 2 consumer runs, got: {consumer_gens}"
