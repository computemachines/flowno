-------------------- MODULE AlgorithmicCyclicMonoFlowTriangleEx --------------------
EXTENDS AlgorithmicCyclicMonoFlow

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}

=============================================================================
