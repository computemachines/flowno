----------------------- MODULE Diamond4_Mono_CyclicEx -----------------------
EXTENDS CyclicMonoFlow

\* Use config: formal-verification/specs/model-tests/CyclicMonoFlow.cfg

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

ConcreteNodes == {0, 1, 2, 3}
ConcreteEdges == DiamondEdges
ConcreteBreakEdges == DiamondBreakEdges

=============================================================================
