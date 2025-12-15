------------------------ MODULE Triangle3_Stream_CyclicStreamConcEx ------------------------
(*
 * Concurrent streaming triangle test with all streaming edges.
 * 
 * Combines:
 *   - CyclicConcurrentStreamingFlow (EventLoop + streaming generation)
 *   - Triangle topology with break edge
 *   - All edges streaming (minRunLevel=1)
 * 
 * Expected behavior:
 *   - A demanded, finds stale C->A edge (break edge), demand C
 *   - C demanded, finds stale B->C edge, demand B
 *   - B demanded, finds stale A->B edge, demand A
 *   - A can start (break edge allows it)
 *   - With streaming, A yields, B can start (streaming consumption)
 *   - Concurrent execution with EventLoop task scheduling
 *)
EXTENDS CyclicConcurrentStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicConcurrentStreamingFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}

\* All edges are streaming (minRunLevel=1)
TriangleMinRunLevel == [e \in TriangleEdges |-> 1]

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges
ConcreteMinRunLevel == TriangleMinRunLevel

=============================================================================
