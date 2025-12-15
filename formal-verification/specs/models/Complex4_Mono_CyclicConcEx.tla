-------------------- MODULE Complex4_Mono_CyclicConcEx --------------------
EXTENDS CyclicConcurrentMonoFlow

\* Use config: formal-verification/specs/model-tests/CyclicConcurrentMonoFlow.cfg

FanInOutEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>, <<0, 3>>, <<3, 2>>, <<2, 3>>}
FanInOutBreakEdges == {<<2, 0>>, <<2, 3>>}

ConcreteNodes == {0, 1, 2, 3}
ConcreteEdges == FanInOutEdges
ConcreteBreakEdges == FanInOutBreakEdges

=============================================================================
