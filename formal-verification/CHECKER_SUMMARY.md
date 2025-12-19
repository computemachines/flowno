# Checker Summary

## Architecture Overview

- **Models** (`specs/models/`): Define the specific topology (nodes, edges) and concrete constants for a test case.
- **Configs** (`specs/model-tests/`): Define the sets of constants to bind and the invariants/properties to check.
- **Modules** (`specs/modules/`): The underlying system models (e.g., `CyclicStreamingFlow`, `SimpleFlow`). These are abstract and cannot be executed until constants are defined by a Model and Config.

## Implementation Notes

- **Property-based vs Algorithmic**: Some modules have an "Algorithmic" variant (e.g., `AlgorithmicCyclicMonoFlow`). This is purely an optimization to speed up checking. The reachable state space should be identical to the Property-based version. This distinction is noted in the grid cells but not used as a primary column dimension.

## Coverage Grid

The grid below maps the **Dataflow Structure** (Model Topology + Edge Configuration) against the **Module Implementation** used to verify it.

### Column Dimensions (Module Implementations)
- **Execution Model**: Abstract vs Concurrent
- **Topology Support**: Acyclic vs Cyclic
- **Streaming Support**: Mono vs Streaming

### Row Dimensions (Dataflow Structure)
- **Edge Config**: AllMono, AllStreaming, Mixed
- **Test Topology**: Linear, Fanin, Fanout, Diamond, Triangle, FanInOut

---

|  | Abstract Acyclic Mono (SimpleFlow.tla) | Abstract Acyclic Streaming (??) | Abstract Cyclic Mono (CyclicMonoFlow.tla) | Abstract Cyclic Streaming (CyclicStreamingFlow.tla) | Concurrent Acyclic Mono (SimpleConcurrentFlow.tla) | Concurrent Acyclic Streaming (??) | Concurrent Cyclic Mono (CyclicConcurrentMonoFlow.tla) | Concurrent Cyclic Streaming (CyclicConcurrentStreamingFlow.tla) |
|--|----------------------|---------------------------|----------------------|--------------------------|------------------------|-----------------------------|-----------------------|----------------------------|
| **AllMono, Linear2** |  |  |  |  |  |  |  |  |
| **AllMono, FanIn3** |  |  |  | Property: FanIn3_Mono_CyclicStreamEx.tla 104 states. 1.00 seconds. |  |  |  |  |
| **AllMono, FanOut3** |  |  |  | Property: FanOut3_Mono_CyclicStreamEx.tla 33 states. .92 seconds. |  |  |  |  |
| **AllMono, Diamond4** | Property: Diamond4_Mono_Ex.tla 13 states. .96 seconds. |  | Property: Diamond4_Mono_CyclicEx.tla 13 states. 3.00 seconds. | Property: Diamond4_Mono_CyclicStreamEx.tla 2460 states. 1.98 seconds. | Property: Diamond4_Mono_ConcEx.tla 49 states. 0.85 seconds. |  |  |  |
| **AllMono, Triangle3** | N/A | N/A | Property: Triangle3_Mono_CyclicEx.tla 26 states. 1.51 seconds.<br>Algorithmic: Triangle3_Mono_AlgoCyclicEx.tla 26 states. .86 seconds. |  | N/A | N/A | Property: Triangle3_Mono_CyclicConcEx.tla 40 states. 1.32 seconds.<br>Algorithmic: Triangle3_Mono_AlgoCyclicConcEx.tla 40 states. .91 seconds. |  |
| **AllMono, Complex4** | N/A | N/A | Property: Complex4_Mono_CyclicEx.tla 46 states. 9.91 seconds.<br>Algorithmic: Complex4_Mono_AlgoCyclicEx.tla 46 states. .95 seconds. |  | N/A | N/A | Property: Complex4_Mono_CyclicConcEx.tla 133 states. 9.86 seconds.<br>Algorithmic: Complex4_Mono_AlgoCyclicConcEx.tla 133 states. 1.01 seconds. |  |
| **AllStreaming, Linear2** | N/A |  | N/A | Property: Linear2_Stream_CyclicStreamEx.tla 10 states. .84 seconds. | N/A |  | N/A | Property: Linear2_Stream_CyclicStreamConcEx.tla 16 states. 1.00 seconds. |
| **AllStreaming, FanIn3** | N/A |  | N/A | Property: FanIn3_Stream_CyclicStreamEx.tla 22 states. .86 seconds. | N/A |  | N/A |  |
| **AllStreaming, FanOut3** | N/A |  | N/A | Property: FanOut3_Stream_CyclicStreamEx.tla 40 states. .88 seconds. | N/A |  | N/A |  |
| **AllStreaming, Diamond4** | N/A |  | N/A | Property: Diamond4_Stream_CyclicStreamEx.tla 15732 states. 5.86 seconds. | N/A |  | N/A |  |
| **AllStreaming, Triangle3** | N/A | N/A | N/A | Property: Triangle3_Stream_CyclicStreamEx.tla 1866 states. 1.29 seconds. | N/A | N/A | N/A | Property: Triangle3_Stream_CyclicStreamConcEx.tla 3378 states. 1.00 seconds. |
| **AllStreaming, Complex4** | N/A | N/A | N/A |  | N/A | N/A | N/A |  |
| **Mixed, Linear2** | N/A |  | N/A | Property: Linear2_StreamToMono_CyclicStreamEx.tla 14 states. .85 seconds. | N/A |  | N/A |  |
| **Mixed, FanIn3** | N/A |  | N/A |  | N/A |  | N/A |  |
| **Mixed, FanOut3** | N/A |  | N/A |  | N/A |  | N/A |  |
| **Mixed, Diamond4** | N/A |  | N/A | Property: Diamond4_TopStream_CyclicStreamEx.tla 8008 states. 3.33 seconds.<br>Property: Diamond4_BotStream_CyclicStreamEx.tla 5307 states. 2.92 seconds.<br>Property: Diamond4_LeftStream_CyclicStreamEx.tla 11870 states. 5.97 seconds. | N/A |  | N/A |  |
| **Mixed, Triangle3** | N/A | N/A | N/A | Property: Triangle3_Mixed_BreakMono_CyclicStreamEx.tla 582 states. 1.13 seconds.<br>Property: Triangle3_Mixed_BreakStream_CyclicStreamEx.tla 490 states. 1.11 seconds. | N/A | N/A | N/A | Property: Triangle3_Mixed_BreakStream_CyclicStreamConcEx.tla 976 states. 1.00 seconds. |
| **Mixed, Complex4** | N/A | N/A | N/A |  | N/A | N/A | N/A |  |

## Infrastructure Tests

These tests verify the underlying `EventLoop` and `EventLoopBasic` modules directly, without a flow topology.

| Model | Description | States | Time |
|-------|-------------|--------|------|
| EventLoopBasicEx.tla | Basic task scheduling (Ready/Running/Sleeping/Joining) | 1165 | 1.00s |
| EventLoopEx.tla | Full EventLoop with AsyncQueue (Put/Get/Close) | 7531 | 1.00s |
