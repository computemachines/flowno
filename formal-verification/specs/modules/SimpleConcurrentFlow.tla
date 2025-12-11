---------------------------- MODULE SimpleConcurrentFlow ----------------------------
EXTENDS Naturals, Integers, FiniteSets, Sequences

CONSTANTS Nodes, Edges

\* Compute max node ID for EventLoopBasic
MaxNodeId == CHOOSE max \in Nodes : \A n \in Nodes : n <= max

\* EventLoopBasic variables (we declare them, INSTANCE binds to them)
VARIABLES
    taskState,
    joinWaiters

\* Flow-specific variables  
VARIABLES
    generation,
    resolutionQueue,
    lastAction

EL == INSTANCE EventLoopBasic WITH MaxTaskId <- MaxNodeId

vars == <<taskState, joinWaiters, generation, resolutionQueue, lastAction>>
flowVars == <<generation, resolutionQueue, lastAction>>

\* ===== Graph helpers (unchanged) =====
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}
IsEdgeStale(u, d) == generation[u] <= generation[d]

RECURSIVE SolutionSet(_)
SolutionSet(n) ==
    LET staleUpstream == {u \in Upstream(n) : IsEdgeStale(u, n)}
    IN IF staleUpstream = {}
       THEN {n}
       ELSE UNION {SolutionSet(u) : u \in staleUpstream}

\* ===== Init: all nodes Ready, one demand =====
Init ==
    /\ taskState = [t \in EL!Tasks |-> [state |-> EL!Ready]]
    /\ joinWaiters = [t \in EL!Tasks |-> {}]
    /\ generation = [n \in Nodes |-> -1]
    /\ resolutionQueue = {3}
    /\ lastAction = "Init"

\* ===== Actions =====

\* Pop demand, solve, schedule one solution node
ResolveAndSchedule(demanded, n) ==
    /\ demanded \in resolutionQueue
    /\ n \in SolutionSet(demanded)
    /\ (n = demanded \/ n \notin resolutionQueue)
    /\ EL!Schedule(n)                              \* precondition: Ready(n), none Running
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ UNCHANGED generation
    /\ lastAction' = << "ResolveAndSchedule", demanded, n >>

\* Running node completes, increments generation, enqueues downstream
NodeComplete(n) ==
    /\ EL!YieldReady(n)                            \* precondition: Running(n)
    /\ generation' = [generation EXCEPT ![n] = @ + 1]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ lastAction' = << "NodeComplete", n >>
Sleep(t) ==
    /\ EL!YieldSleep(t)
    /\ UNCHANGED <<generation, resolutionQueue>>
    /\ lastAction' = <<"Sleep", t>>

Wake(t) ==
    /\ EL!WakeFromSleep(t)
    /\ UNCHANGED <<generation, resolutionQueue>>
    /\ lastAction' = <<"Wake", t>>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : ResolveAndSchedule(demanded, n)
    \/ \E n \in Nodes : NodeComplete(n)
    \/ \E t \in Nodes : Sleep(t)
    \/ \E t \in Nodes : Wake(t)

Spec == Init /\ [][Next]_vars
ELSpec == EL!Spec

\* ===== Invariants =====
TypeOK ==
    /\ EL!TypeOK
    /\ generation \in [Nodes -> -1..1]
    /\ resolutionQueue \subseteq Nodes

\* Inherited from EventLoopBasic
AtMostOneRunning == EL!AtMostOneRunning

=============================================================================