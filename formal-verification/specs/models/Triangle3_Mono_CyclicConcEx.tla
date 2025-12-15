-------------------- MODULE Triangle3_Mono_CyclicConcEx --------------------
EXTENDS CyclicConcurrentMonoFlow

\* Use config: formal-verification/specs/model-tests/CyclicConcurrentMonoFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges

=============================================================================
