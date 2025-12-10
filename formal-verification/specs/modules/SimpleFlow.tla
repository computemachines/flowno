---------------------------- MODULE SimpleFlow ----------------------------
EXTENDS Naturals, FiniteSets, Integers

CONSTANTS 
    Nodes,
    Edges

VARIABLES
    generation,     \* generation[n] = int (-1 = never run)
    running         \* running = node currently executing, or -1 if none

vars == <<generation, running>>

NoNode == (-1)

\* Graph helpers
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}

\* A node can start if all upstreams have produced output
CanStart(n) ==
    /\ running = NoNode
    /\ \A u \in Upstream(n) : generation[u] >= 0

\* Actions
Start(n) ==
    /\ CanStart(n)
    /\ running' = n
    /\ UNCHANGED generation

Complete ==
    /\ running # NoNode
    /\ generation' = [generation EXCEPT ![running] = @ + 1]
    /\ running' = NoNode

Init ==
    /\ generation = [n \in Nodes |-> -1]
    /\ running = NoNode

Next ==
    \/ \E n \in Nodes : Start(n)
    \/ Complete

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ generation \in [Nodes -> -1..10]
    /\ running \in Nodes \cup {NoNode}

=============================================================================