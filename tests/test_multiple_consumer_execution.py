"""Tests for verifying execution count of multiple stream consumers.

Tests that multiple consumers of the same streaming source each execute exactly once,
with various timing patterns.
"""
import pytest
from flowno import FlowHDL, node, Stream
import flowno


class TestMultipleConsumerExecution:
    """Tests verifying that multiple stream consumers execute exactly once."""

    def test_multiple_consumers_basic(self):
        """Test that multiple consumers each execute exactly once - basic case."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            yield "a"
            yield "b"
            log.append("source_end")

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream):
            log.append("consumer1_start")
            async for item in stream:
                log.append(f"consumer1_item_{item}")
            log.append("consumer1_end")

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream):
            log.append("consumer2_start")
            async for item in stream:
                log.append(f"consumer2_item_{item}")
            log.append("consumer2_end")

        with FlowHDL() as f:
            f.source = Source()
            Consumer1(f.source)
            Consumer2(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("consumer1_start") == 1
        assert log.count("consumer1_end") == 1
        assert log.count("consumer2_start") == 1
        assert log.count("consumer2_end") == 1
        
        # Verify both consumers received all items
        assert "consumer1_item_a" in log
        assert "consumer1_item_b" in log
        assert "consumer2_item_a" in log
        assert "consumer2_item_b" in log

    def test_multiple_consumers_with_source_delays(self):
        """Test multiple consumers with delays between source yields."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            yield "first"
            await flowno.sleep(0.01)
            log.append("source_after_delay1")
            yield "second"
            await flowno.sleep(0.01)
            log.append("source_after_delay2")
            yield "third"
            log.append("source_end")

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream):
            log.append("consumer1_start")
            async for item in stream:
                log.append(f"consumer1_item_{item}")
            log.append("consumer1_end")

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream):
            log.append("consumer2_start")
            async for item in stream:
                log.append(f"consumer2_item_{item}")
            log.append("consumer2_end")

        with FlowHDL() as f:
            f.source = Source()
            Consumer1(f.source)
            Consumer2(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("source_after_delay1") == 1
        assert log.count("source_after_delay2") == 1
        assert log.count("consumer1_start") == 1
        assert log.count("consumer1_end") == 1
        assert log.count("consumer2_start") == 1
        assert log.count("consumer2_end") == 1
        
        # Verify both consumers received all items
        assert log.count("consumer1_item_first") == 1
        assert log.count("consumer1_item_second") == 1
        assert log.count("consumer1_item_third") == 1
        assert log.count("consumer2_item_first") == 1
        assert log.count("consumer2_item_second") == 1
        assert log.count("consumer2_item_third") == 1

    def test_multiple_consumers_with_consumer_delays(self):
        """Test multiple consumers with delays in consumer processing."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            yield "x"
            yield "y"
            yield "z"
            log.append("source_end")

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream):
            log.append("consumer1_start")
            async for item in stream:
                log.append(f"consumer1_item_{item}")
                await flowno.sleep(0.01)
                log.append(f"consumer1_processed_{item}")
            log.append("consumer1_end")

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream):
            log.append("consumer2_start")
            async for item in stream:
                log.append(f"consumer2_item_{item}")
                await flowno.sleep(0.005)
                log.append(f"consumer2_processed_{item}")
            log.append("consumer2_end")

        with FlowHDL() as f:
            f.source = Source()
            Consumer1(f.source)
            Consumer2(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("consumer1_start") == 1
        assert log.count("consumer1_end") == 1
        assert log.count("consumer2_start") == 1
        assert log.count("consumer2_end") == 1
        
        # Verify both consumers received and processed all items
        for item in ["x", "y", "z"]:
            assert log.count(f"consumer1_item_{item}") == 1
            assert log.count(f"consumer1_processed_{item}") == 1
            assert log.count(f"consumer2_item_{item}") == 1
            assert log.count(f"consumer2_processed_{item}") == 1

    def test_multiple_consumers_mixed_delays(self):
        """Test multiple consumers with delays in both source and consumers."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            await flowno.sleep(0.005)
            yield "alpha"
            await flowno.sleep(0.005)
            yield "beta"
            log.append("source_end")

        @node(stream_in=["stream"])
        async def Consumer1(stream: Stream):
            log.append("consumer1_start")
            async for item in stream:
                await flowno.sleep(0.002)
                log.append(f"consumer1_item_{item}")
            log.append("consumer1_end")

        @node(stream_in=["stream"])
        async def Consumer2(stream: Stream):
            log.append("consumer2_start")
            async for item in stream:
                await flowno.sleep(0.008)
                log.append(f"consumer2_item_{item}")
            log.append("consumer2_end")

        with FlowHDL() as f:
            f.source = Source()
            Consumer1(f.source)
            Consumer2(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("consumer1_start") == 1
        assert log.count("consumer1_end") == 1
        assert log.count("consumer2_start") == 1
        assert log.count("consumer2_end") == 1
        
        # Verify both consumers received all items
        assert log.count("consumer1_item_alpha") == 1
        assert log.count("consumer1_item_beta") == 1
        assert log.count("consumer2_item_alpha") == 1
        assert log.count("consumer2_item_beta") == 1

    @pytest.mark.skip(reason="Flaky on CI - see GitHub issue for investigation")
    def test_three_consumers_with_varying_delays(self):
        """Test three consumers with different processing speeds."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            for i in range(3):
                yield i
                await flowno.sleep(0.003)
            log.append("source_end")

        @node(stream_in=["stream"])
        async def FastConsumer(stream: Stream):
            log.append("fast_start")
            async for item in stream:
                log.append(f"fast_{item}")
                await flowno.sleep(0.001)
            log.append("fast_end")

        @node(stream_in=["stream"])
        async def MediumConsumer(stream: Stream):
            log.append("medium_start")
            async for item in stream:
                log.append(f"medium_{item}")
                await flowno.sleep(0.005)
            log.append("medium_end")

        @node(stream_in=["stream"])
        async def SlowConsumer(stream: Stream):
            log.append("slow_start")
            async for item in stream:
                log.append(f"slow_{item}")
                await flowno.sleep(0.01)
            log.append("slow_end")

        with FlowHDL() as f:
            f.source = Source()
            FastConsumer(f.source)
            MediumConsumer(f.source)
            SlowConsumer(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("fast_start") == 1
        assert log.count("fast_end") == 1
        assert log.count("medium_start") == 1
        assert log.count("medium_end") == 1
        assert log.count("slow_start") == 1
        assert log.count("slow_end") == 1
        
        # Verify all consumers received all items
        for i in range(3):
            assert log.count(f"fast_{i}") == 1
            assert log.count(f"medium_{i}") == 1
            assert log.count(f"slow_{i}") == 1

    def test_consumers_immediate_vs_delayed_start(self):
        """Test consumers starting at different times relative to source."""
        log = []
        
        @node
        async def Source():
            log.append("source_start")
            yield "item1"
            await flowno.sleep(0.02)
            yield "item2"
            log.append("source_end")

        @node(stream_in=["stream"])
        async def ImmediateConsumer(stream: Stream):
            log.append("immediate_start")
            async for item in stream:
                log.append(f"immediate_{item}")
            log.append("immediate_end")

        @node(stream_in=["stream"])
        async def DelayedConsumer(stream: Stream):
            log.append("delayed_start")
            await flowno.sleep(0.01)
            log.append("delayed_after_sleep")
            async for item in stream:
                log.append(f"delayed_{item}")
            log.append("delayed_end")

        with FlowHDL() as f:
            f.source = Source()
            ImmediateConsumer(f.source)
            DelayedConsumer(f.source)

        f.run_until_complete()

        # Verify each node executed exactly once
        assert log.count("source_start") == 1
        assert log.count("source_end") == 1
        assert log.count("immediate_start") == 1
        assert log.count("immediate_end") == 1
        assert log.count("delayed_start") == 1
        assert log.count("delayed_end") == 1
        assert log.count("delayed_after_sleep") == 1
        
        # Verify both consumers received all items
        assert log.count("immediate_item1") == 1
        assert log.count("immediate_item2") == 1
        assert log.count("delayed_item1") == 1
        assert log.count("delayed_item2") == 1
