-------------------- MODULE Complex4_Mono_AlgoCyclicEx --------------------
EXTENDS AlgorithmicCyclicMonoFlow

\* Use config: formal-verification/specs/model-tests/AlgorithmicCyclicMonoFlow.cfg

FanInOutEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>, <<0, 3>>, <<3, 2>>, <<2, 3>>}
FanInOutBreakEdges == {<<2, 0>>, <<2, 3>>}

ConcreteNodes == {0, 1, 2, 3}
ConcreteEdges == FanInOutEdges
ConcreteBreakEdges == FanInOutBreakEdges

=============================================================================
