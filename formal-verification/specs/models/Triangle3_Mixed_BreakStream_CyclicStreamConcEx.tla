------------------------ MODULE Triangle3_Mixed_BreakStream_CyclicStreamConcEx ------------------------
(*
 * Concurrent cyclic triangle with mixed streaming configuration.
 * 
 * Triangle topology:
 *     A(0) ---> B(1)
 *      ^         |
 *      |         v
 *     C(2) <-----+
 * 
 * Edge configuration:
 *   A->B: minRunLevel=1 (streaming)
 *   B->C: minRunLevel=1 (streaming)
 *   C->A: minRunLevel=0 (mono) - BREAK EDGE
 * 
 * Break edge on the mono edge (C->A).
 * With concurrent EventLoop execution.
 * 
 * Expected behavior:
 *   - A demanded, finds stale C->A edge, demand C
 *   - C demanded, finds stale B->C edge, demand B
 *   - B demanded, finds stale A->B edge, demand A
 *   - A can start (break edge allows it)
 *   - A yields, B can start (streaming consumption)
 *   - B yields, C can start (streaming consumption)
 *   - C completes, A can continue next generation (mono consumption, break edge fresh)
 *   - Concurrent scheduling by EventLoop
 *)
EXTENDS CyclicConcurrentStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicConcurrentStreamingFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}

\* Two streaming edges (A->B, B->C), one mono break edge (C->A)
TriangleMinRunLevel == [e \in TriangleEdges |-> IF e = <<2, 0>> THEN 0 ELSE 1]

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges
ConcreteMinRunLevel == TriangleMinRunLevel

=============================================================================
