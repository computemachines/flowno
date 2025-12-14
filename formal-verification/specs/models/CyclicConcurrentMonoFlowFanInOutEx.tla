-------------------- MODULE CyclicConcurrentMonoFlowFanInOutEx --------------------
EXTENDS CyclicConcurrentMonoFlow

FanInOutEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>, <<0, 3>>, <<3, 2>>, <<2, 3>>}
FanInOutBreakEdges == {<<2, 0>>, <<2, 3>>}

=============================================================================
