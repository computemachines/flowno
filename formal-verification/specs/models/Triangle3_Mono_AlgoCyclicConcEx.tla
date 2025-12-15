---------------- MODULE Triangle3_Mono_AlgoCyclicConcEx ----------------
EXTENDS AlgorithmicCyclicConcurrentMonoFlow

\* Use config: formal-verification/specs/model-tests/AlgorithmicCyclicConcurrentMonoFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges

=============================================================================
