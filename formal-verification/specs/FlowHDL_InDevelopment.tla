-------------------- MODULE FlowHDL_InDevelopment --------------------
(*
 * PURPOSE: Model a 4-node cyclic dataflow with streaming fan-out and fan-in.
 * Verify correct scheduling, stream cancellation, and termination
 * when any node reaches generation (2,).
 *
 * TOPOLOGY:
 *
 *                      ┌─────────────────────────────────────────┐
 *                      │                                         │
 *                      v                                         │
 *                  Counter                                       │
 *                 /       \                                      │
 *           (stream)    (stream)   <- fan-out                    │
 *               /           \                                    │
 *              v             v                                   │
 *         WordGenEN     WordGenSP                                │
 *               \           /                                    │
 *           (stream)    (stream)   <- fan-in via azip            │
 *                 \       /                                      │
 *                  v     v                                       │
 *                 Accumulator                                    │
 *                      │                                         │
 *                      └─────────────────────────────────────────┘
 *
 * EVENTUAL PYTHON CODE:
 *
 * > from flowno import FlowHDL, node, Stream, azip
 * >
 * > @node
 * > async def Counter(feedback: str = "") -> AsyncGenerator[int, None]:
 * >     """Yields integers 0..len(feedback). Streaming producer."""
 * >     for i in range(len(feedback) + 1):
 * >         yield i
 * >
 * > @node(stream_in=["numbers"])
 * > async def WordGen(numbers: Stream[int], lang: str = "en") -> AsyncGenerator[str, None]:
 * >     """Converts each streamed int to a word. Streaming consumer & producer."""
 * >     en_words = ["zero", "one", "two", "three", "four"]
 * >     sp_words = ["cero", "uno", "dos", "tres", "cuatro"]
 * >     words = sp_words if lang == "sp" else en_words
 * >     async for n in numbers:
 * >         yield words[n % len(words)]
 * >
 * > @node(stream_in=["words_en", "words_sp"])
 * > async def Accumulator(words_en: Stream[str], words_sp: Stream[str]) -> str:
 * >     """Zips EN and SP streams, collects pairs into a sentence."""
 * >     parts: list[str] = []
 * >     async for en, sp in azip(words_en, words_sp):
 * >         parts.append(f"{en}/{sp}")
 * >     return " ".join(parts)
 * >
 * > def main():
 * >     with FlowHDL() as f:
 * >         f.counter = Counter(f.accumulator)              # cycle: feedback from accumulator
 * >         f.wordgen_en = WordGen(f.counter, lang="en")    # stream fan-out
 * >         f.wordgen_sp = WordGen(f.counter, lang="sp")    # stream fan-out
 * >         f.accumulator = Accumulator(f.wordgen_en, f.wordgen_sp)  # stream fan-in
 * >
 * >     f.run_until_complete(stop_at_generation=(2,))
 * >
 *
 *
 * ACTUAL PYTHON CODE (graph construction only, node behavior TBD):
 * 
 * > from flowno import FlowHDL, node, Stream
 * > from typing import AsyncGenerator
 * > 
 * > # Node type definitions (behavior not yet implemented)
 * > @node
 * > async def Counter(feedback: str = "") -> AsyncGenerator[int, None]:
 * >     """Mono input (defaulted), stream output."""
 * >     ...
 * > 
 * > @node(stream_in=["numbers"])
 * > async def WordGen(numbers: Stream[int], lang: str = "en") -> AsyncGenerator[str, None]:
 * >     """Stream input, mono input (defaulted), stream output."""
 * >     ...
 * > 
 * > @node(stream_in=["words_en", "words_sp"])
 * > async def Accumulator(words_en: Stream[str], words_sp: Stream[str]) -> str:
 * >     """Two stream inputs, mono output."""
 * >     ...
 * > 
 * > # Graph construction matching TLA+ Main process
 * > def main():
 * >     with FlowHDL() as f:
 * >         # Add nodes (l1-l6 in TLA+)
 * >         f.counter = Counter(f.accumulator)           # feedback cycle
 * >         f.wordgen_en = WordGen(f.counter, lang="en") # Constant node implicit
 * >         f.wordgen_sp = WordGen(f.counter, lang="sp") # Constant node implicit
 * >         f.accumulator = Accumulator(f.wordgen_en, f.wordgen_sp)
 * >     
 * >     # Graph finalized on context exit (finalize_graph in TLA+)
 *)

EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS 
    NoTask,
    NoLock,
    NoEvent,
    NoNode

Tasks == {
    0,    \* main task
    1, 2, 3, 4, 5, 6, \* node persistent tasks
    7 \* demonstration of an unused task
}

\* These are not actually used yet.
Events == {
    0  \* latch 0 uses event 0
}
Locks == {
    0, \* latch 0 uses lock 0
    1, \* condition 0 uses lock 1 (not shared)
    2  \* queue 0 shares lock 2 with conditions 1 and 2
}
Conditions == {
    0, \* standalone condition 0
    1, \* queue 0's _not_empty condition
    2  \* queue 0's _not_full condition
}
Queues == {
    0
}
Latches == {
    0
}
NodeTypes == [
    \* Counter accepts a (defaultable) mono input (from Accumulator feedback) and produces a streamed output (to WordGenEN and WordGenSP)
    Counter |-> [defaulted_inputs |-> {0}, run_level_inputs |-> <<0>> , run_level_outputs |-> <<1>>],
    \* WordGen takes a stream input and a mono constant input (lang), produces stream output
    WordGen |-> [defaulted_inputs |-> {1}, run_level_inputs |-> <<1, 0>>, run_level_outputs |-> <<1>>],
    Accumulator |-> [run_level_inputs |-> <<1, 1>>, run_level_outputs |-> <<0>>],

    \* Node literals. Implementation detail for flowno internals. Direct literal assignment uses a "Constant[Type]" node type.
    Constant |-> [run_level_inputs |-> <<>>, run_level_outputs |-> <<0>>]
]
DefaultedInputs(type) == 
    IF "defaulted_inputs" \in DOMAIN type THEN type.defaulted_inputs ELSE {}

\* Object graph using nested records to mirror Python attribute access.
\* Python: latch._lock, queue._not_empty._lock
\* TLA+:   Latch[l].lock.id, Queue[q].not_empty.lock.id
\*
\* Key insight: Lock 2 is SHARED - it appears in Queue[0].lock.id,
\* Queue[0].not_empty.lock.id, Queue[0].not_full.lock.id, and
\* Condition[1].lock.id and Condition[2].lock.id (intentional duplication).

Condition ==
    [c \in Conditions |-> CASE c = 0 -> [lock |-> [id |-> 1]]
                               [] c = 1 -> [lock |-> [id |-> 2]]  \* _not_empty shares queue's lock
                               [] c = 2 -> [lock |-> [id |-> 2]]  \* _not_full shares queue's lock
                               [] OTHER -> [lock |-> [id |-> NoLock]]]

Latch ==
    [l \in Latches |-> CASE l = 0 -> [lock |-> [id |-> 0], event |-> [id |-> 0]]
                            [] OTHER -> [lock |-> [id |-> NoLock], event |-> [id |-> NoEvent]]]

Queue ==
    [q \in Queues |-> CASE q = 0 -> [
                                lock |-> [id |-> 2],
                                not_empty |-> [
                                    id |-> 1,
                                    lock |-> [id |-> 2]
                                ],
                                not_full |-> [
                                    id |-> 2,
                                    lock |-> [id |-> 2]
                                ]
                            ]
                           [] OTHER -> [
                                lock |-> [id |-> NoLock],
                                not_empty |-> [id |-> -1, lock |-> [id |-> NoLock]],
                                not_full |-> [id |-> -1, lock |-> [id |-> NoLock]]
                            ]]

\* Queue configuration: maxsize for each queue (NoTask represents None/unbounded)
QueueMaxSize == [q \in Queues |-> CASE q = 0 -> 2  \* bounded queue with maxsize=2
                                       [] OTHER -> 0]


\* -- Basic task state options --
\* Only states the event loop can actually observe
Ready == "Ready"
ReadyResuming == "ReadyResuming"
Running == "Running"
NonExistent == "NonExistent"
Sleeping == "Sleeping"
WaitingLock == "WaitingLock"
WaitingEvent == "WaitingEvent"
WaitingCondition == "WaitingCondition"
WaitingJoin == "WaitingJoin"
Done == "Done"
WaitingForStartNextGeneration == "WaitingForStartNextGeneration"


(* --algorithm EventLoopExample {
variables
\* === Core event loop state ===
runningTask = NoTask,
taskState = [t \in Tasks |->
    IF t = 0
    THEN [state |-> Ready]
    ELSE [state |-> NonExistent]
],

\* === CountdownLatch state (Event + Lock) ===
latchCount = [latch \in Latches |-> 2],
lock = [latch \in Locks |-> NoTask],
\* Python semantics: FIFO wait queue (event loop uses deque).
lockWaiters = [latch \in Locks |-> << >>],
eventFired = [latch \in Events |-> FALSE],
eventWaiters = [latch \in Events |-> {}],

\* === Condition state (ConditionWaitCommand / ConditionNotifyCommand) ===
\* conditionWaiters[cond] is a set (Python: self.condition_waiters[cond] is a set)
conditionWaiters = [c \in Conditions |-> {}],
conditionFlag = [c \in Conditions |-> FALSE],

\* === AsyncQueue state ===
\* queueItems[q] is a sequence representing the queue contents
queueItems = [q \in Queues |-> << >>],
\* queueClosed[q] tracks if queue q is closed
queueClosed = [q \in Queues |-> FALSE],

\* === Join state (JoinCommand / watching_task) ===
\* joinWaiters[t] is the set of tasks waiting for task t to complete
joinWaiters = [t \in Tasks |-> {}],

\* === DYNAMIC FLOW GRAPH STATE ===
\* nodes: set of node records [id |-> <string>, type |-> <string>]
\* Example: {[id |-> "counter", type |-> "Counter"], [id |-> "wordgen_en", type |-> "WordGen"]}
nodes = {},
\* edges: set of edge records [src |-> [node |-> <node_record>, port |-> <int>], dst |-> [node |-> <node_record>, port |-> <int>]]
edges = {},
finalizedFlag = FALSE,

\* === TASK-NODE MAPPING ===
\* Maps task IDs (1..6) to their assigned node records
taskNode = [t \in 1..6 |-> NoNode],
\* Counter for which task ID to assign to the next added node
nextTaskId = 1,

\* === DYNAMIC FLOW GRAPH RUNNING STATE ===
generation = [x \in {} |-> <<>>],     \* node -> <<run_level_0_value, run_level_1_value, ...>>
stitchCounter = [x \in {} |-> 0],  \* edge -> int
resolutionQueue = {},  \* set of nodes to process

primed = [x \in {} |-> FALSE],    \* node -> BOOLEAN (whether node has been primed)


\* === Tracking ===
workersCompleted = 0,
itemsProduced = 0,
itemsConsumed = 0,
lastAction = <<"Init">>;

define {
IsReady(t) == taskState[t].state = Ready
IsWaitingJoin(t) == taskState[t].state = WaitingJoin
IsRunning(t) == taskState[t].state = Running
IsWaitingLock(t) == taskState[t].state = WaitingLock
IsWaitingEvent(t) == taskState[t].state = WaitingEvent
IsWaitingCondition(t) == taskState[t].state = WaitingCondition
IsSleeping(t) == taskState[t].state = Sleeping
IsDone(t) == taskState[t].state = Done
IsWaitingForStartNextGeneration(t) == taskState[t].state = WaitingForStartNextGeneration

IsSchedulable(t) == IsReady(t)

\* === Queue helper functions ===
QueueLen(q) == Len(queueItems[q])
QueueIsFull(q) == QueueMaxSize[q] # NoTask /\ QueueLen(q) >= QueueMaxSize[q]
QueueIsEmpty(q) == QueueLen(q) = 0

\* === Flow Graph helper functions ===
\* nodes: set of node records [id |-> <string>, type |-> <string>]
\* edges: set of edge records [src |-> [node |-> <node_record>, port |-> <int>], dst |-> [node |-> <node_record>, port |-> <int>]]

\* Get all nodes that feed INTO this node (upstream producers)
UpstreamNodes(node) == 
    {e.src.node : e \in {edge \in edges : edge.dst.node = node}}

\* Get all nodes that this node feeds INTO (downstream consumers)
DownstreamNodes(node) == 
    {e.dst.node : e \in {edge \in edges : edge.src.node = node}}

\* Get all edges from a specific node (any port)
OutgoingEdgesFromNode(node) ==
    {e \in edges : e.src.node = node}

\* Get all edges to a specific node (any port)
IncomingEdgesToNode(node) ==
    {e \in edges : e.dst.node = node}

\* === Invariants ===
AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1
LatchCountNonNegative == \A l \in Latches : latchCount[l] >= 0
LatchLockMutex == \A l \in Locks : Cardinality({t \in Tasks : lock[l] = t}) <= 1
EventSetWhenZero == \A l \in Latches : (latchCount[l] = 0) => eventFired[Latch[l].event.id]
MainWaitsUntilZero == IsWaitingEvent(0) => latchCount[0] > 0
QueueBoundsRespected == \A q \in Queues : QueueMaxSize[q] # NoTask => QueueLen(q) <= QueueMaxSize[q]
EventuallyAllDone == <>(taskState = [t \in Tasks |-> [state |-> Done]])
Eventually2WorkersDone == <>(workersCompleted = 2)
Eventually2ItemsProduced == <>(itemsProduced = 2)
Eventually2ItemsConsumed == <>(itemsConsumed = 2)

\* Debug: Verify nodes never execute (since resolutionQueue is never seeded)
NodesNeverExecute == 
    \A n \in DOMAIN generation : generation[n] = <<>>

\* Debug: Resolution queue should always be empty
ResolutionQueueEmpty == resolutionQueue = {}

\* === Flow Graph Helpers ===

\* Find a node by id (returns the node record or NoNode)
NodeById(id) == 
    LET matches == {n \in nodes : n.id = id}
    IN IF matches = {} THEN NoNode ELSE CHOOSE n \in matches : TRUE

\* Get the node record assigned to a task (returns NoNode if unassigned)
NodeForTask(t) == taskNode[t]

\* Check if a task has been assigned to a node
TaskHasNode(t) == taskNode[t] # NoNode

\* Get the type schema for a node record (node.type -> NodeTypes lookup)
TypeSchema(node) == NodeTypes[node.type]

\* Get all edges targeting a specific node's input port
IncomingEdges(node, port) == {e \in edges : e.dst.node = node /\ e.dst.port = port}

\* Get all edges from a specific node's output port  
OutgoingEdges(node, port) == {e \in edges : e.src.node = node /\ e.src.port = port}

\* Check if input port idx is defaulted for this node
\* Use "defaulted_inputs" field if present, otherwise assume no defaults
IsDefaultedInput(node, idx) == 
    LET schema == TypeSchema(node)
    IN IF "defaulted_inputs" \in DOMAIN schema 
       THEN idx \in schema.defaulted_inputs
       ELSE FALSE

\* Get run level for an input port (0-indexed, sequences are 1-indexed)
InputRunLevel(node, idx) == TypeSchema(node).run_level_inputs[idx + 1]

\* Get run level for an output port
OutputRunLevel(node, idx) == TypeSchema(node).run_level_outputs[idx + 1]

\* Number of input/output ports
NumInputs(node) == Len(TypeSchema(node).run_level_inputs)
NumOutputs(node) == Len(TypeSchema(node).run_level_outputs)

\* === GENERATION COMPARISON ===
\* Generations are sequences: <<>>, <<0>>, <<0, 0>>, <<1, 2, 3>>, etc.
\* <<>> represents None (never run) = smallest value
\*
\* Ordering (counterintuitive!):
\*   <<>> < <<0, 0>> < <<0, 1>> < <<0>> < <<1, 0>> < <<1>> < <<2>>
\*   None   partial    partial    final   partial    final   final
\*
\* Rule: lexicographic first, then SHORTER = GREATER (more final)

\* Compare two generations: -1 if a < b, 0 if equal, 1 if a > b
\* Using iterative approach with bounded length (max 5 levels should be plenty)
CmpGeneration(genA, genB) ==
    IF genA = <<>> /\ genB = <<>> THEN 0
    ELSE IF genA = <<>> THEN -1  \* None < anything
    ELSE IF genB = <<>> THEN 1   \* anything > None
    ELSE
        LET lenA == Len(genA)
            lenB == Len(genB)
            minLen == IF lenA < lenB THEN lenA ELSE lenB
            \* Find first differing position (check up to 5 positions)
            diff1 == IF minLen >= 1 /\ genA[1] # genB[1] THEN 1 ELSE 0
            diff2 == IF minLen >= 2 /\ diff1 = 0 /\ genA[2] # genB[2] THEN 2 ELSE 0
            diff3 == IF minLen >= 3 /\ diff1 = 0 /\ diff2 = 0 /\ genA[3] # genB[3] THEN 3 ELSE 0
            diff4 == IF minLen >= 4 /\ diff1 = 0 /\ diff2 = 0 /\ diff3 = 0 /\ genA[4] # genB[4] THEN 4 ELSE 0
            diff5 == IF minLen >= 5 /\ diff1 = 0 /\ diff2 = 0 /\ diff3 = 0 /\ diff4 = 0 /\ genA[5] # genB[5] THEN 5 ELSE 0
            firstDiff == diff1 + diff2 + diff3 + diff4 + diff5
        IN
        IF firstDiff > 0 THEN
            IF genA[firstDiff] < genB[firstDiff] THEN -1 ELSE 1
        ELSE
            \* Common prefix is identical, shorter = greater (more final)
            IF lenA < lenB THEN 1      \* (0,) > (0, 0)
            ELSE IF lenA > lenB THEN -1 \* (0, 0) < (0,)
            ELSE 0

\* Convenience predicates
GenLE(a, b) == CmpGeneration(a, b) <= 0
GenLT(a, b) == CmpGeneration(a, b) < 0
GenGE(a, b) == CmpGeneration(a, b) >= 0
GenGT(a, b) == CmpGeneration(a, b) > 0

\* === STITCH GENERATION (cycle breaking) ===
\* Adds stitch value to first element of generation
StitchedGeneration(gen, stitch0) ==
    IF gen = <<>> THEN
        IF stitch0 > 0 THEN <<stitch0 - 1>>
        ELSE <<>>
    ELSE IF Len(gen) = 0 THEN gen
    ELSE [gen EXCEPT ![1] = gen[1] + stitch0]

\* === CLIP GENERATION ===
\* Returns highest gen <= input with length <= runLevel + 1
\* Simplified version: just truncate (works for most cases)
ClipGeneration(gen, runLevel) ==
    IF gen = <<>> THEN <<>>
    ELSE
        LET maxLen == runLevel + 1 IN
        IF Len(gen) <= maxLen THEN gen
        ELSE SubSeq(gen, 1, maxLen)

\* === INCREMENT GENERATION ===
\* Returns minimal generation > input at specified run level
IncGeneration(gen, runLevel) ==
    LET targetLen == runLevel + 1 IN
    IF gen = <<>> THEN
        [i \in 1..targetLen |-> 0]  \* <<0, 0, ...>> of length runLevel+1
    ELSE
        LET extended == 
            IF Len(gen) >= targetLen THEN SubSeq(gen, 1, targetLen)
            ELSE gen \o [i \in 1..(targetLen - Len(gen)) |-> 0]
        IN
        \* If extended > gen, we're done (this happens when extending with zeros)
        IF CmpGeneration(extended, gen) > 0 THEN extended
        ELSE [extended EXCEPT ![targetLen] = extended[targetLen] + 1]

\* === STALENESS (for cyclic flows) ===
\* An edge is stale if the source's (clipped + stitched) generation <= destination's generation
\* This means the destination has already consumed this edge's data
IsEdgeStale(edge) == 
    LET 
        srcNode == edge.src.node
        dstNode == edge.dst.node
        dstPort == edge.dst.port
        
        \* Get the input port's run level
        inputRunLevel == InputRunLevel(dstNode, dstPort)
        
        \* Get stitch value (stored per-edge, defaults to 0)
        stitch0 == IF edge \in DOMAIN stitchCounter THEN stitchCounter[edge] ELSE 0
        
        \* Apply clipping and stitching to source generation
        srcGen == IF srcNode \in DOMAIN generation THEN generation[srcNode] ELSE <<>>
        clippedGen == ClipGeneration(srcGen, inputRunLevel)
        stitchedGen == StitchedGeneration(clippedGen, stitch0)
        
        \* Get destination generation
        dstGen == IF dstNode \in DOMAIN generation THEN generation[dstNode] ELSE <<>>
    IN
    GenLE(stitchedGen, dstGen)

\* The subgraph of currently stale edges
StaleSubgraph == {e \in edges : IsEdgeStale(e)}

\* Stale dependency edges (reversed direction for backward reachability)
\* Original edge: src -> dst (data flows src to dst)
\* Dependency: dst depends on src, so we flip to dst -> src
StaleDependencyEdges == 
    {[src |-> e.dst, dst |-> e.src] : e \in StaleSubgraph}

\* === DIRECTED REACHABILITY ===
\* Compute nodes reachable from 'startNode' following edges in relation R
\* R is a set of edge records with src.node and dst.node
ReachableFrom(startNode, R) ==
    LET Step(S) == S \union {e.dst.node : e \in {edge \in R : edge.src.node \in S}}
    IN Step(Step(Step(Step(Step({startNode})))))  \* 5 iterations for paths up to length 5

\* Nodes reachable from node following stale data-flow edges (downstream)
ForwardReach(node) == ReachableFrom(node, StaleSubgraph)

\* Nodes reachable from node following stale dependency edges (upstream)  
BackwardReach(node) == ReachableFrom(node, StaleDependencyEdges)

\* The SCC containing node: nodes that can reach node AND node can reach them
LocalSCC(node) == ForwardReach(node) \cap BackwardReach(node)

\* Stale inputs for a specific node (edges where this node is the destination and the edge is stale)
StaleInputsFor(node) ==
    {e \in edges : e.dst.node = node /\ IsEdgeStale(e)}

\* === BREAK EDGES (cycle breaking) ===
\* Break edges are edges where cycles can be broken.
\* In Python flowno, these are edges connecting to defaulted inputs (the cycle's "entry point").
\* For now, we define them as edges to inputs with defaults.
BreakEdges == 
    {e \in edges : IsDefaultedInput(e.dst.node, e.dst.port)}

\* === SOLUTION ALGORITHM (from CyclicConcurrentPlusCalFlow) ===

\* Is this SCC cyclic? Either multiple nodes, or self-loop
IsLocalCyclic(n) ==
    LET scc == LocalSCC(n)
    IN Cardinality(scc) > 1 \/
       \E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc

\* External dependencies of an SCC: nodes outside the SCC that the SCC depends on
ExternalDeps(scc) ==
    {e.dst.node : e \in {edge \in StaleDependencyEdges : edge.src.node \in scc /\ edge.dst.node \notin scc}}

\* Is this SCC a leaf? No external stale dependencies
IsLeafSCC(scc) == ExternalDeps(scc) = {}

\* Find all leaf SCCs reachable backward from demanded node
\* Uses bounded iteration to explore the dependency DAG
LeafSCCsFrom(demanded) ==
    LET \* Start with the SCC containing demanded
        startSCC == LocalSCC(demanded)

        \* Explore one level: given a set of SCCs, find their upstream SCCs
        UpstreamSCCs(sccs) ==
            LET allExternalDeps == UNION {ExternalDeps(scc) : scc \in sccs}
            IN {LocalSCC(n) : n \in allExternalDeps}

        \* Iteratively find all reachable SCCs (bounded iterations)
        Step(sccs) == sccs \cup UpstreamSCCs(sccs)
        AllReachableSCCs == Step(Step(Step(Step(Step({startSCC})))))

    IN {scc \in AllReachableSCCs : IsLeafSCC(scc)}

\* Pick the break node from an SCC
\* For non-cyclic singleton: just return the node
\* For cyclic SCC: pick node that is destination of a break edge within the SCC
BreakNodeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc)
    THEN CHOOSE n \in scc : TRUE  \* Non-cyclic singleton
    ELSE CHOOSE n \in scc : \E e \in BreakEdges : e.dst.node = n /\ e.src.node \in scc

\* Pick the break edge from an SCC (empty set if non-cyclic)
BreakEdgeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc)
    THEN {}  \* Non-cyclic singleton
    ELSE LET candidates == {e \in BreakEdges : e.dst.node \in scc /\ e.src.node \in scc}
         IN IF candidates = {} THEN {} ELSE {CHOOSE e \in candidates : TRUE}

\* Final solution operators
SolutionNodes(demanded) == {BreakNodeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}

\* === Flow Graph Invariants ===

\* INV1: All non-defaulted inputs must have exactly one incoming edge
AllRequiredInputsConnected == 
    finalizedFlag => 
        \A node \in nodes: 
            \A idx \in 0..(NumInputs(node) - 1) :
                ~IsDefaultedInput(node, idx) =>
                    Cardinality(IncomingEdges(node, idx)) = 1

\* INV2: All inputs connected to at most one output
InputsHaveAtMostOneSource ==
    finalizedFlag =>
        \A node \in nodes: 
            \A idx \in 0..(NumInputs(node) - 1) :
                Cardinality(IncomingEdges(node, idx)) <= 1

\* INV3: No duplicate node IDs
UniqueNodeIds ==
    \A n1, n2 \in nodes : n1.id = n2.id => n1 = n2

\* INV4: Run level compatibility
RunLevelCompatibility ==
    finalizedFlag =>
        \A e \in edges :
            LET srcRL == OutputRunLevel(e.src.node, e.src.port)
                dstRL == InputRunLevel(e.dst.node, e.dst.port)
            IN
                (srcRL = 0 => dstRL = 0) /\
                (srcRL = 1 => dstRL \in {0, 1})

\* INV5: All edge endpoints reference nodes that exist
EdgesReferenceValidNodes ==
    \A e \in edges : e.src.node \in nodes /\ e.dst.node \in nodes

\* Combined invariant
FinalizedGraphWellFormed ==
    UniqueNodeIds /\
    EdgesReferenceValidNodes /\
    (finalizedFlag => (
        AllRequiredInputsConnected /\
        InputsHaveAtMostOneSource /\
        RunLevelCompatibility
    ))

\* === Cyclic Dataflow Invariants ===

\* Stitch count never exceeds 1 per edge (one cycle break per resolution)
StitchAtMostOnce == \A e \in DOMAIN stitchCounter : stitchCounter[e] <= 1

\* === Generation Helper Operators ===

\* Nodes that have started (have a non-empty generation)
StartedNodes == {n \in nodes : n \in DOMAIN generation /\ generation[n] # <<>>}

\* Maximum generation among started nodes (using tuple comparison)
\* Returns <<>> if no nodes have started
MaxGenStarted ==
    IF StartedNodes = {} THEN <<>>
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} :
         \A n \in StartedNodes : GenLE(generation[n], g)

\* Minimum generation among started nodes (using tuple comparison)
\* Returns <<>> if no nodes have started
MinGenStarted ==
    IF StartedNodes = {} THEN <<>>
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} :
         \A n \in StartedNodes : GenGE(generation[n], g)

\* Wavefront tightness for tuple generations
\* For run-level-0 (mono) generations, the first element should differ by at most 1
\* This is a simplified check on the "outer" generation dimension
WavefrontTight ==
    StartedNodes # {} =>
        LET maxGen == MaxGenStarted
            minGen == MinGenStarted
            \* Extract first element (run-level-0 generation)
            maxRL0 == IF maxGen = <<>> THEN 0 ELSE Head(maxGen)
            minRL0 == IF minGen = <<>> THEN 0 ELSE Head(minGen)
        IN maxRL0 - minRL0 <= 1

\* All nodes have primed (yielded WaitForNextGen at least once)
\* Only meaningful after graph is finalized and nodes exist in primed domain
AllPrimed == 
    finalizedFlag /\ 
    nodes # {} /\ 
    \A n \in nodes : n \in DOMAIN primed /\ primed[n]

\* === State Constraint ===
\* Bound state space for cyclic flows (generations can grow unbounded)
\* Limit the first element of generation to 2 (allows generations up to (2,))
StateConstraint == 
    \A n \in nodes : 
        n \notin DOMAIN generation \/ 
        generation[n] = <<>> \/ 
        Head(generation[n]) <= 2

\* === Liveness Properties ===

\* Every node eventually runs at least once (gets a non-empty generation)
AllNodesEventuallyStart == 
    finalizedFlag => \A n \in nodes : <>(n \in DOMAIN generation /\ generation[n] # <<>>)

\* Generations always eventually advance beyond initial (strong liveness for cyclic flows)
\* Once a node has started, it will eventually reach generation > <<0>>
\* (i.e., it will complete at least one full iteration and start another)
GenerationsAdvance ==
    finalizedFlag => \A n \in nodes : 
        [](n \in DOMAIN generation /\ generation[n] # <<>> => 
           <>(GenGT(generation[n], <<0>>)))
}

\* === Yield macros ===

macro yield_spawn(t) {
taskState := [taskState EXCEPT ![t]    = [state |-> Ready], 
                                ![self] = [state |-> Ready]];
runningTask := NoTask;
lastAction := <<"Spawn", t, self>>;
}

macro yield_sleep() {
taskState[self] := [state |-> Sleeping];
runningTask := NoTask;
lastAction := <<"Sleep", self>>;
}

macro yield_wait_for_next_generation() {
\* Node yields waiting for resolver to tell it to start next generation
\* Also marks the node as primed (has yielded at least once)
with (myNode = taskNode[self]) {
    taskState[self] := [state |-> WaitingForStartNextGeneration];
    primed := [primed EXCEPT ![myNode] = TRUE];
    runningTask := NoTask;
    lastAction := <<"WaitForNextGen", self, myNode.id>>;
}
}

macro yield_complete() {
\* Wake all tasks waiting to join this task
taskState := [t \in Tasks |->
    CASE t = self                -> [state |-> Done]
        [] t \in joinWaiters[self] -> [state |-> Ready]
        [] OTHER                   -> taskState[t]
];
joinWaiters[self] := {};
runningTask := NoTask;
lastAction := <<"Complete", self>>;
}

macro yield_join(t) {
\* Wait for task t to complete (matches JoinCommand)
if (IsDone(t)) {
    \* Task already done, return immediately
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"Join", "Immediate", t, self>>;
} else {
    \* Task not done, wait for it
    taskState[self] := [state |-> WaitingJoin];
    joinWaiters[t] := joinWaiters[t] \union {self};
    runningTask := NoTask;
    lastAction := <<"Join", "Waiting", t, self>>;
}
}

\* === Lock operations ===

macro yield_acquire_lock(l) {
if (lock[l] = NoTask) {
    lock[l] := self;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"AcquireLock", "Immediate", l, self>>;
} else {
    taskState[self] := [state |-> WaitingLock];
    \* FIFO enqueue (matches event loop: lock_waiters[lock].append(task)).
    lockWaiters[l] := Append(lockWaiters[l], self);
    runningTask := NoTask;
    lastAction := <<"AcquireLock", "Waiting", l, self>>;
}
}

macro yield_release_lock(l) {
\* Python semantics: only owner may release.
assert lock[l] = self;

if (lockWaiters[l] = << >>) {
    \* No waiters -> unlock.
    lock[l] := NoTask;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"ReleaseLock", l, self>>;
} else {
    \* Waiters -> transfer ownership to FIFO head, wake it.
    with (nextOwner = Head(lockWaiters[l])) {
        lock[l] := nextOwner;
        lockWaiters[l] := Tail(lockWaiters[l]);
        taskState := [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                        ![self] = [state |-> Ready]];
        runningTask := NoTask;
        lastAction := <<"ReleaseLock", l, self>>;
    }
}
}

\* === Event operations ===

macro yield_event_wait(e) {
taskState[self] := [state |-> IF eventFired[e] THEN Ready ELSE WaitingEvent];
eventWaiters[e] := IF eventFired[e] THEN eventWaiters[e] ELSE eventWaiters[e] \union {self};
runningTask := NoTask;
lastAction := <<"EventWait", e, self>>;
}

macro yield_event_set(e) {
taskState := LET wasFired == eventFired[e] IN
    IF ~wasFired THEN
        [t \in Tasks |->
            IF t \in eventWaiters[e] THEN [state |-> Ready]
            ELSE IF t = self THEN [state |-> Ready]
            ELSE taskState[t]]
    ELSE
        [taskState EXCEPT ![self] = [state |-> Ready]];
eventWaiters[e] := LET wasFired == eventFired[e] IN IF ~wasFired THEN {} ELSE eventWaiters[e];
eventFired[e] := TRUE;
runningTask := NoTask;
lastAction := <<"EventSet", e, self>>;
}

\* === Condition operations ===

macro yield_condition_wait(c) {
    \* Matches event_loop.py ConditionWaitCommand:
    \* - assert caller owns lock
    \* - atomically: add to condition waiters, release lock  
    \* - if lock had waiters, wake next waiter and transfer ownership

    \* TODO: mimic the actual python implementation more closely and call the release_lock macro?

    assert lock[Condition[c].lock.id] = self;

    \* Capture values before any modifications
    with (hasWaiters = lockWaiters[Condition[c].lock.id] # << >>,
            nextOwner = IF lockWaiters[Condition[c].lock.id] # << >>
                        THEN Head(lockWaiters[Condition[c].lock.id])
                        ELSE NoTask) {
                        
        conditionWaiters[c] := conditionWaiters[c] \union {self};
        lock[Condition[c].lock.id] := nextOwner;
        lockWaiters[Condition[c].lock.id] := IF hasWaiters
                                                THEN Tail(lockWaiters[Condition[c].lock.id])
                                                ELSE << >>;
        taskState := IF hasWaiters
                        THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                ![nextOwner] = [state |-> Ready]]
                        ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]];
        runningTask := NoTask;
        lastAction := <<"ConditionWait", c, self>>;
    };
}

macro yield_condition_notify(c) {
    \* Matches event_loop.py ConditionNotifyCommand(all=False):
    \* - assert caller owns lock
    \* - pop one arbitrary waiter from condition set
        \* - append it to lock's FIFO waiter queue
    assert lock[Condition[c].lock.id] = self;

    \* Capture values before modifications
    with (hasWaiters = conditionWaiters[c] # {},
            waiter = IF conditionWaiters[c] # {}
                    THEN CHOOSE t \in conditionWaiters[c] : TRUE
                    ELSE NoTask) {
                    
        conditionWaiters[c] := IF hasWaiters
                                THEN conditionWaiters[c] \ {waiter}
                                ELSE conditionWaiters[c];
        lockWaiters[Condition[c].lock.id] := IF hasWaiters
                                                THEN Append(lockWaiters[Condition[c].lock.id], waiter)
                                                ELSE lockWaiters[Condition[c].lock.id];
        taskState := IF hasWaiters
                        THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                ![self] = [state |-> Ready]]
                        ELSE [taskState EXCEPT ![self] = [state |-> Ready]];
        runningTask := NoTask;
        lastAction := <<"ConditionNotify", c, self>>;
    };
}

macro yield_latch_countdown(l) {
    latchCount[l]                   := latchCount[l] - 1;
    eventFired[Latch[l].event.id] := IF   latchCount[l] = 0
                                       THEN TRUE
                                       ELSE eventFired[Latch[l].event.id];
    taskState := IF   latchCount[l] = 0
                 THEN [t \in Tasks |->
                    IF   (t = self) \/ (t \in eventWaiters[Latch[l].event.id])
                    THEN [state |-> Ready]
                    ELSE taskState[t]]
                 ELSE [taskState EXCEPT ![self] = [state |-> Ready]];
    eventWaiters[Latch[l].event.id] := IF   latchCount[l] = 0
                                         THEN {}
                                         ELSE eventWaiters[Latch[l].event.id];
    runningTask := NoTask;
    lastAction  := <<"LatchCountdown", l, self>>;
}



\* === Flow modification macros ===

macro flow_add_node(node_id, node_type) {
    \* Create a new node record and add to nodes set
    \* Precondition: node_type must exist in NodeTypes
    assert node_type \in DOMAIN NodeTypes;
    \* Precondition: no duplicate IDs
    assert ~(\E n \in nodes : n.id = node_id);
    \* Precondition: have available task ID
    assert nextTaskId <= 6;
    
    with (newNode = [id |-> node_id, type |-> node_type]) {
        nodes := nodes \union {newNode};
        \* Assign this node to the next available task
        taskNode[nextTaskId] := newNode;
        \* Initialize generation and primed for this node
        generation := generation @@ (newNode :> <<>>);
        primed := primed @@ (newNode :> FALSE);
        \* Set the task to Ready so scheduler can pick it up
        taskState[nextTaskId] := [state |-> Ready];
    };
    nextTaskId := nextTaskId + 1;
}

macro flow_connect(src_id, src_port, dst_id, dst_port) {
    \* Connect output port of src node to input port of dst node
    \* Uses node records directly in the edge
    with (srcNode = CHOOSE n \in nodes : n.id = src_id;
          dstNode = CHOOSE n \in nodes : n.id = dst_id) {
        edges := edges \union {[
            src |-> [node |-> srcNode, port |-> src_port],
            dst |-> [node |-> dstNode, port |-> dst_port]
        ]};
    }
}

macro flow_finalize() {
    finalizedFlag := TRUE;
}

\* === Procedures ===
\* Note: AsyncQueue operations (put, get, close) are implemented as procedures below,
\* not macros, because they need while loops with label breakpoints for proper
\* event loop scheduling. They compose Lock and Condition primitives.

procedure latch_countdown(latch_id)
{
lcd_acquire:  \* await latch.__aenter__()
    await runningTask = self;
            yield_acquire_lock(Latch[latch_id].lock.id);

lcd_atomic:  \* await latch.count_down()
    await runningTask = self;
    yield_latch_countdown(latch_id);

lcd_release:  \* await latch.__aexit__()
    await runningTask = self;
            yield_release_lock(Latch[latch_id].lock.id);

lcd_return:
    return;
}

\* === Queue procedures ===
\* Python: await queue.put(item)
procedure queue_put(queue_id, item_to_put)
variable item_put_done = FALSE;
{
qput_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qput_wait_loop:  \* while maxsize and len(items) >= maxsize: await _not_full.wait()
    await runningTask = self;
    if (QueueIsFull(queue_id) /\ ~queueClosed[queue_id]) {
        \* Queue is full, wait on _not_full condition
        yield_condition_wait(Queue[queue_id].not_full.id);
        goto qput_wait_loop;  \* Loop back after being woken
    } else if (queueClosed[queue_id]) {
        \* Queue closed while waiting
        item_put_done := TRUE;  \* Error case
        goto qput_release;
    } else {
        \* Queue has space, proceed to put
        goto qput_do_put;
    };

qput_do_put:  \* items.append(item); await _not_empty.notify()
    await runningTask = self;
    queueItems[queue_id] := Append(queueItems[queue_id], item_to_put);
    yield_condition_notify(Queue[queue_id].not_empty.id);

qput_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qput_return:
    return;
}

\* Python: item = await queue.get()
procedure queue_get(queue_id)
variable item_got = NoTask;
{
qget_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qget_wait_loop:  \* while not items: await _not_empty.wait()
    await runningTask = self;
    if (QueueIsEmpty(queue_id) /\ ~queueClosed[queue_id]) {
        \* Queue is empty, wait on _not_empty condition
        yield_condition_wait(Queue[queue_id].not_empty.id);
        goto qget_wait_loop;  \* Loop back after being woken
    } else if (queueClosed[queue_id] /\ QueueIsEmpty(queue_id)) {
        \* Queue closed and empty
        item_got := NoTask;  \* Error case
        goto qget_release;
    } else {
        \* Queue has items, proceed to get
        goto qget_do_get;
    };

qget_do_get:  \* item = items.popleft(); await _not_full.notify()
    await runningTask = self;
    item_got := Head(queueItems[queue_id]);
    queueItems[queue_id] := Tail(queueItems[queue_id]);
    yield_condition_notify(Queue[queue_id].not_full.id);

qget_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qget_return:
    return;
}

\* Python: await queue.close()
procedure queue_close(queue_id)
{
qclose_acquire:  \* await queue._lock.__aenter__()
    await runningTask = self;
    yield_acquire_lock(Queue[queue_id].lock.id);

qclose_do_close:  \* closed = True; await _not_empty.notify_all(); await _not_full.notify_all()
    await runningTask = self;
    queueClosed[queue_id] := TRUE;
    taskState[self] := [state |-> Ready];
    runningTask := NoTask;
    lastAction := <<"QueueClose", queue_id, self>>;

qclose_release:  \* await queue._lock.__aexit__()
    await runningTask = self;
    yield_release_lock(Queue[queue_id].lock.id);

qclose_return:
    return;
}

\* === Scheduler ===
fair process (Scheduler = 99)
{
sched:
while (TRUE) {
    await runningTask = NoTask /\ \E t \in Tasks : IsSchedulable(t);
    with (t \in {t \in Tasks : IsSchedulable(t)}) {
        runningTask := t;
        taskState[t] := [state |-> Running];
        lastAction := <<"Scheduler", "pick", t>>;
    }
}
}

\* === Resolver Process ===
\* Uses SolutionNodes to resolve demands, updates stitchCounter for cycle breaks
fair process (Resolver = 98)
{
resolve:
while (TRUE) {
    \* Block until all nodes have primed AND there's something to resolve
    await AllPrimed /\ resolutionQueue # {};
    
    with (demanded \in resolutionQueue) {
        \* Find solution nodes that are waiting and not already in queue
        with (sol \in {s \in SolutionNodes(demanded) :
                       IsWaitingForStartNextGeneration(s) /\ 
                       (s = demanded \/ s \notin resolutionQueue)}) {
            taskState[sol] := [state |-> Ready];
            resolutionQueue := resolutionQueue \ {demanded};
            \* Increment stitch counter for broken edges
            stitchCounter := [e \in DOMAIN stitchCounter |-> 
                IF e \in EdgesToStitch(demanded)
                THEN stitchCounter[e] + 1
                ELSE stitchCounter[e]];
            lastAction := <<"Resolver", "demanded", demanded, "sol", sol>>;
        }
    }
}
}

\* === External Wake ===
fair process (ExternalWake = 97)
{
wake:
while (TRUE) {
    await \E t \in Tasks : IsSleeping(t);
    with (t \in {u \in Tasks : IsSleeping(u)}) {
        taskState[t] := [state |-> Ready];
        lastAction := <<"ExternalWake", t>>;
    }
}
}

\* === Main task ===
fair process (Main \in {0})
{

\* Build the 4-node flow from the docstring
build_graph:
    await runningTask = self;
    
    \* Add nodes
l1:
    flow_add_node("counter", "Counter");
l2:
    flow_add_node("wordgen_en", "WordGen");
l3:
    flow_add_node("wordgen_sp", "WordGen");  \* Same type, different id!
l4:
    flow_add_node("accumulator", "Accumulator");
l5:
    flow_add_node("const_en", "Constant");  \* For lang="en" argument
l6:
    flow_add_node("const_sp", "Constant");  \* For lang="sp" argument
    
connect_edges:
    await runningTask = self;
    
l7:
    \* Counter -> WordGenEN (stream fan-out)
    flow_connect("counter", 0, "wordgen_en", 0);
l8:
    \* Counter -> WordGenSP (stream fan-out)  
    flow_connect("counter", 0, "wordgen_sp", 0);
l9:
    \* WordGenEN -> Accumulator input 0
    flow_connect("wordgen_en", 0, "accumulator", 0);
l10:
    \* WordGenSP -> Accumulator input 1
    flow_connect("wordgen_sp", 0, "accumulator", 1);
l11:
    \* Accumulator -> Counter (cycle, mono to mono)
    flow_connect("accumulator", 0, "counter", 0);
l12:
    \* ConstantEN -> WordGenEN input 1
    flow_connect("const_en", 0, "wordgen_en", 1);
l13:
    \* ConstantSP -> WordGenSP input 1
    flow_connect("const_sp", 0, "wordgen_sp", 1);

finalize_graph:
    await runningTask = self;
    flow_finalize();
    runningTask := NoTask; \* manually yield after flow building
    taskState[self] := [state |-> Ready]; \* mark as ready for scheduler

wait_all_primed:
    \* Block until all node tasks have primed (reached WaitingForStartNextGeneration)
    \* Must yield control so scheduler can run other tasks
    await runningTask = self;
    await AllPrimed;


\* main_dummy_pc: \* uncomment to check that the state graph passes through a single state here (total states only 1 greater than without)
\*     skip;



main_done:  \* (implicit task completion)
    await runningTask = self;
    yield_complete();
}

\* === Node Task Processes ===
\* Each node gets a persistent task that waits for resolution and executes
fair process (NodeTask \in 1..6)
{
node_init:
    \* Wait until this task is assigned to a node
    await TaskHasNode(self) /\ finalizedFlag;
    
node_loop:
  while (TRUE) {
    node_wait_for_next_gen:
        await runningTask = self;
        yield_wait_for_next_generation();
        
    node_execute:
        await runningTask = self;
        \* Increment generation and queue downstream nodes
        with (myNode = taskNode[self];
              newGen = IncGeneration(generation[myNode], 0)) {
            \* Use IncGeneration to compute next generation at run level 0
            generation := [generation EXCEPT ![myNode] = newGen];
            \* Queue downstream nodes for resolution (set union)
            resolutionQueue := resolutionQueue \union 
                {e.dst.node : e \in {edge \in edges : edge.src.node = myNode}};
            lastAction := <<"NodeExecute", self, myNode.id, newGen>>;
        };
  }
}

} *)
\* BEGIN TRANSLATION (chksum(pcal) = "4448b303" /\ chksum(tla) = "d4ee6b8a")
\* Parameter queue_id of procedure queue_put at line 921 col 21 changed to queue_id_
\* Parameter queue_id of procedure queue_get at line 957 col 21 changed to queue_id_q
CONSTANT defaultInitValue
VARIABLES runningTask, taskState, latchCount, lock, lockWaiters, eventFired, 
          eventWaiters, conditionWaiters, conditionFlag, queueItems, 
          queueClosed, joinWaiters, nodes, edges, finalizedFlag, taskNode, 
          nextTaskId, generation, stitchCounter, resolutionQueue, primed, 
          workersCompleted, itemsProduced, itemsConsumed, lastAction, pc, 
          stack

(* define statement *)
IsReady(t) == taskState[t].state = Ready
IsWaitingJoin(t) == taskState[t].state = WaitingJoin
IsRunning(t) == taskState[t].state = Running
IsWaitingLock(t) == taskState[t].state = WaitingLock
IsWaitingEvent(t) == taskState[t].state = WaitingEvent
IsWaitingCondition(t) == taskState[t].state = WaitingCondition
IsSleeping(t) == taskState[t].state = Sleeping
IsDone(t) == taskState[t].state = Done
IsWaitingForStartNextGeneration(t) == taskState[t].state = WaitingForStartNextGeneration

IsSchedulable(t) == IsReady(t)


QueueLen(q) == Len(queueItems[q])
QueueIsFull(q) == QueueMaxSize[q] # NoTask /\ QueueLen(q) >= QueueMaxSize[q]
QueueIsEmpty(q) == QueueLen(q) = 0






UpstreamNodes(node) ==
    {e.src.node : e \in {edge \in edges : edge.dst.node = node}}


DownstreamNodes(node) ==
    {e.dst.node : e \in {edge \in edges : edge.src.node = node}}


OutgoingEdgesFromNode(node) ==
    {e \in edges : e.src.node = node}


IncomingEdgesToNode(node) ==
    {e \in edges : e.dst.node = node}


AtMostOneRunning == Cardinality({t \in Tasks : IsRunning(t)}) <= 1
LatchCountNonNegative == \A l \in Latches : latchCount[l] >= 0
LatchLockMutex == \A l \in Locks : Cardinality({t \in Tasks : lock[l] = t}) <= 1
EventSetWhenZero == \A l \in Latches : (latchCount[l] = 0) => eventFired[Latch[l].event.id]
MainWaitsUntilZero == IsWaitingEvent(0) => latchCount[0] > 0
QueueBoundsRespected == \A q \in Queues : QueueMaxSize[q] # NoTask => QueueLen(q) <= QueueMaxSize[q]
EventuallyAllDone == <>(taskState = [t \in Tasks |-> [state |-> Done]])
Eventually2WorkersDone == <>(workersCompleted = 2)
Eventually2ItemsProduced == <>(itemsProduced = 2)
Eventually2ItemsConsumed == <>(itemsConsumed = 2)


NodesNeverExecute ==
    \A n \in DOMAIN generation : generation[n] = <<>>


ResolutionQueueEmpty == resolutionQueue = {}




NodeById(id) ==
    LET matches == {n \in nodes : n.id = id}
    IN IF matches = {} THEN NoNode ELSE CHOOSE n \in matches : TRUE


NodeForTask(t) == taskNode[t]


TaskHasNode(t) == taskNode[t] # NoNode


TypeSchema(node) == NodeTypes[node.type]


IncomingEdges(node, port) == {e \in edges : e.dst.node = node /\ e.dst.port = port}


OutgoingEdges(node, port) == {e \in edges : e.src.node = node /\ e.src.port = port}



IsDefaultedInput(node, idx) ==
    LET schema == TypeSchema(node)
    IN IF "defaulted_inputs" \in DOMAIN schema
       THEN idx \in schema.defaulted_inputs
       ELSE FALSE


InputRunLevel(node, idx) == TypeSchema(node).run_level_inputs[idx + 1]


OutputRunLevel(node, idx) == TypeSchema(node).run_level_outputs[idx + 1]


NumInputs(node) == Len(TypeSchema(node).run_level_inputs)
NumOutputs(node) == Len(TypeSchema(node).run_level_outputs)













CmpGeneration(genA, genB) ==
    IF genA = <<>> /\ genB = <<>> THEN 0
    ELSE IF genA = <<>> THEN -1
    ELSE IF genB = <<>> THEN 1
    ELSE
        LET lenA == Len(genA)
            lenB == Len(genB)
            minLen == IF lenA < lenB THEN lenA ELSE lenB

            diff1 == IF minLen >= 1 /\ genA[1] # genB[1] THEN 1 ELSE 0
            diff2 == IF minLen >= 2 /\ diff1 = 0 /\ genA[2] # genB[2] THEN 2 ELSE 0
            diff3 == IF minLen >= 3 /\ diff1 = 0 /\ diff2 = 0 /\ genA[3] # genB[3] THEN 3 ELSE 0
            diff4 == IF minLen >= 4 /\ diff1 = 0 /\ diff2 = 0 /\ diff3 = 0 /\ genA[4] # genB[4] THEN 4 ELSE 0
            diff5 == IF minLen >= 5 /\ diff1 = 0 /\ diff2 = 0 /\ diff3 = 0 /\ diff4 = 0 /\ genA[5] # genB[5] THEN 5 ELSE 0
            firstDiff == diff1 + diff2 + diff3 + diff4 + diff5
        IN
        IF firstDiff > 0 THEN
            IF genA[firstDiff] < genB[firstDiff] THEN -1 ELSE 1
        ELSE

            IF lenA < lenB THEN 1
            ELSE IF lenA > lenB THEN -1
            ELSE 0


GenLE(a, b) == CmpGeneration(a, b) <= 0
GenLT(a, b) == CmpGeneration(a, b) < 0
GenGE(a, b) == CmpGeneration(a, b) >= 0
GenGT(a, b) == CmpGeneration(a, b) > 0



StitchedGeneration(gen, stitch0) ==
    IF gen = <<>> THEN
        IF stitch0 > 0 THEN <<stitch0 - 1>>
        ELSE <<>>
    ELSE IF Len(gen) = 0 THEN gen
    ELSE [gen EXCEPT ![1] = gen[1] + stitch0]




ClipGeneration(gen, runLevel) ==
    IF gen = <<>> THEN <<>>
    ELSE
        LET maxLen == runLevel + 1 IN
        IF Len(gen) <= maxLen THEN gen
        ELSE SubSeq(gen, 1, maxLen)



IncGeneration(gen, runLevel) ==
    LET targetLen == runLevel + 1 IN
    IF gen = <<>> THEN
        [i \in 1..targetLen |-> 0]
    ELSE
        LET extended ==
            IF Len(gen) >= targetLen THEN SubSeq(gen, 1, targetLen)
            ELSE gen \o [i \in 1..(targetLen - Len(gen)) |-> 0]
        IN

        IF CmpGeneration(extended, gen) > 0 THEN extended
        ELSE [extended EXCEPT ![targetLen] = extended[targetLen] + 1]




IsEdgeStale(edge) ==
    LET
        srcNode == edge.src.node
        dstNode == edge.dst.node
        dstPort == edge.dst.port


        inputRunLevel == InputRunLevel(dstNode, dstPort)


        stitch0 == IF edge \in DOMAIN stitchCounter THEN stitchCounter[edge] ELSE 0


        srcGen == IF srcNode \in DOMAIN generation THEN generation[srcNode] ELSE <<>>
        clippedGen == ClipGeneration(srcGen, inputRunLevel)
        stitchedGen == StitchedGeneration(clippedGen, stitch0)


        dstGen == IF dstNode \in DOMAIN generation THEN generation[dstNode] ELSE <<>>
    IN
    GenLE(stitchedGen, dstGen)


StaleSubgraph == {e \in edges : IsEdgeStale(e)}




StaleDependencyEdges ==
    {[src |-> e.dst, dst |-> e.src] : e \in StaleSubgraph}




ReachableFrom(startNode, R) ==
    LET Step(S) == S \union {e.dst.node : e \in {edge \in R : edge.src.node \in S}}
    IN Step(Step(Step(Step(Step({startNode})))))


ForwardReach(node) == ReachableFrom(node, StaleSubgraph)


BackwardReach(node) == ReachableFrom(node, StaleDependencyEdges)


LocalSCC(node) == ForwardReach(node) \cap BackwardReach(node)


StaleInputsFor(node) ==
    {e \in edges : e.dst.node = node /\ IsEdgeStale(e)}





BreakEdges ==
    {e \in edges : IsDefaultedInput(e.dst.node, e.dst.port)}




IsLocalCyclic(n) ==
    LET scc == LocalSCC(n)
    IN Cardinality(scc) > 1 \/
       \E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc


ExternalDeps(scc) ==
    {e.dst.node : e \in {edge \in StaleDependencyEdges : edge.src.node \in scc /\ edge.dst.node \notin scc}}


IsLeafSCC(scc) == ExternalDeps(scc) = {}



LeafSCCsFrom(demanded) ==
    LET
        startSCC == LocalSCC(demanded)


        UpstreamSCCs(sccs) ==
            LET allExternalDeps == UNION {ExternalDeps(scc) : scc \in sccs}
            IN {LocalSCC(n) : n \in allExternalDeps}


        Step(sccs) == sccs \cup UpstreamSCCs(sccs)
        AllReachableSCCs == Step(Step(Step(Step(Step({startSCC})))))

    IN {scc \in AllReachableSCCs : IsLeafSCC(scc)}




BreakNodeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc)
    THEN CHOOSE n \in scc : TRUE
    ELSE CHOOSE n \in scc : \E e \in BreakEdges : e.dst.node = n /\ e.src.node \in scc


BreakEdgeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e.src.node \in scc /\ e.dst.node \in scc)
    THEN {}
    ELSE LET candidates == {e \in BreakEdges : e.dst.node \in scc /\ e.src.node \in scc}
         IN IF candidates = {} THEN {} ELSE {CHOOSE e \in candidates : TRUE}


SolutionNodes(demanded) == {BreakNodeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}




AllRequiredInputsConnected ==
    finalizedFlag =>
        \A node \in nodes:
            \A idx \in 0..(NumInputs(node) - 1) :
                ~IsDefaultedInput(node, idx) =>
                    Cardinality(IncomingEdges(node, idx)) = 1


InputsHaveAtMostOneSource ==
    finalizedFlag =>
        \A node \in nodes:
            \A idx \in 0..(NumInputs(node) - 1) :
                Cardinality(IncomingEdges(node, idx)) <= 1


UniqueNodeIds ==
    \A n1, n2 \in nodes : n1.id = n2.id => n1 = n2


RunLevelCompatibility ==
    finalizedFlag =>
        \A e \in edges :
            LET srcRL == OutputRunLevel(e.src.node, e.src.port)
                dstRL == InputRunLevel(e.dst.node, e.dst.port)
            IN
                (srcRL = 0 => dstRL = 0) /\
                (srcRL = 1 => dstRL \in {0, 1})


EdgesReferenceValidNodes ==
    \A e \in edges : e.src.node \in nodes /\ e.dst.node \in nodes


FinalizedGraphWellFormed ==
    UniqueNodeIds /\
    EdgesReferenceValidNodes /\
    (finalizedFlag => (
        AllRequiredInputsConnected /\
        InputsHaveAtMostOneSource /\
        RunLevelCompatibility
    ))




StitchAtMostOnce == \A e \in DOMAIN stitchCounter : stitchCounter[e] <= 1




StartedNodes == {n \in nodes : n \in DOMAIN generation /\ generation[n] # <<>>}



MaxGenStarted ==
    IF StartedNodes = {} THEN <<>>
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} :
         \A n \in StartedNodes : GenLE(generation[n], g)



MinGenStarted ==
    IF StartedNodes = {} THEN <<>>
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} :
         \A n \in StartedNodes : GenGE(generation[n], g)




WavefrontTight ==
    StartedNodes # {} =>
        LET maxGen == MaxGenStarted
            minGen == MinGenStarted

            maxRL0 == IF maxGen = <<>> THEN 0 ELSE Head(maxGen)
            minRL0 == IF minGen = <<>> THEN 0 ELSE Head(minGen)
        IN maxRL0 - minRL0 <= 1



AllPrimed ==
    finalizedFlag /\
    nodes # {} /\
    \A n \in nodes : n \in DOMAIN primed /\ primed[n]




StateConstraint ==
    \A n \in nodes :
        n \notin DOMAIN generation \/
        generation[n] = <<>> \/
        Head(generation[n]) <= 2




AllNodesEventuallyStart ==
    finalizedFlag => \A n \in nodes : <>(n \in DOMAIN generation /\ generation[n] # <<>>)




GenerationsAdvance ==
    finalizedFlag => \A n \in nodes :
        [](n \in DOMAIN generation /\ generation[n] # <<>> =>
           <>(GenGT(generation[n], <<0>>)))

VARIABLES latch_id, queue_id_, item_to_put, item_put_done, queue_id_q, 
          item_got, queue_id

vars == << runningTask, taskState, latchCount, lock, lockWaiters, eventFired, 
           eventWaiters, conditionWaiters, conditionFlag, queueItems, 
           queueClosed, joinWaiters, nodes, edges, finalizedFlag, taskNode, 
           nextTaskId, generation, stitchCounter, resolutionQueue, primed, 
           workersCompleted, itemsProduced, itemsConsumed, lastAction, pc, 
           stack, latch_id, queue_id_, item_to_put, item_put_done, queue_id_q, 
           item_got, queue_id >>

ProcSet == {99} \cup {98} \cup {97} \cup ({0}) \cup (1..6)

Init == (* Global variables *)
        /\ runningTask = NoTask
        /\ taskState =             [t \in Tasks |->
                           IF t = 0
                           THEN [state |-> Ready]
                           ELSE [state |-> NonExistent]
                       ]
        /\ latchCount = [latch \in Latches |-> 2]
        /\ lock = [latch \in Locks |-> NoTask]
        /\ lockWaiters = [latch \in Locks |-> << >>]
        /\ eventFired = [latch \in Events |-> FALSE]
        /\ eventWaiters = [latch \in Events |-> {}]
        /\ conditionWaiters = [c \in Conditions |-> {}]
        /\ conditionFlag = [c \in Conditions |-> FALSE]
        /\ queueItems = [q \in Queues |-> << >>]
        /\ queueClosed = [q \in Queues |-> FALSE]
        /\ joinWaiters = [t \in Tasks |-> {}]
        /\ nodes = {}
        /\ edges = {}
        /\ finalizedFlag = FALSE
        /\ taskNode = [t \in 1..6 |-> NoNode]
        /\ nextTaskId = 1
        /\ generation = [x \in {} |-> <<>>]
        /\ stitchCounter = [x \in {} |-> 0]
        /\ resolutionQueue = {}
        /\ primed = [x \in {} |-> FALSE]
        /\ workersCompleted = 0
        /\ itemsProduced = 0
        /\ itemsConsumed = 0
        /\ lastAction = <<"Init">>
        (* Procedure latch_countdown *)
        /\ latch_id = [ self \in ProcSet |-> defaultInitValue]
        (* Procedure queue_put *)
        /\ queue_id_ = [ self \in ProcSet |-> defaultInitValue]
        /\ item_to_put = [ self \in ProcSet |-> defaultInitValue]
        /\ item_put_done = [ self \in ProcSet |-> FALSE]
        (* Procedure queue_get *)
        /\ queue_id_q = [ self \in ProcSet |-> defaultInitValue]
        /\ item_got = [ self \in ProcSet |-> NoTask]
        (* Procedure queue_close *)
        /\ queue_id = [ self \in ProcSet |-> defaultInitValue]
        /\ stack = [self \in ProcSet |-> << >>]
        /\ pc = [self \in ProcSet |-> CASE self = 99 -> "sched"
                                        [] self = 98 -> "resolve"
                                        [] self = 97 -> "wake"
                                        [] self \in {0} -> "build_graph"
                                        [] self \in 1..6 -> "node_init"]

lcd_acquire(self) == /\ pc[self] = "lcd_acquire"
                     /\ runningTask = self
                     /\ IF lock[(Latch[latch_id[self]].lock.id)] = NoTask
                           THEN /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = self]
                                /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"AcquireLock", "Immediate", (Latch[latch_id[self]].lock.id), self>>
                                /\ UNCHANGED lockWaiters
                           ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                /\ lockWaiters' = [lockWaiters EXCEPT ![(Latch[latch_id[self]].lock.id)] = Append(lockWaiters[(Latch[latch_id[self]].lock.id)], self)]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"AcquireLock", "Waiting", (Latch[latch_id[self]].lock.id), self>>
                                /\ lock' = lock
                     /\ pc' = [pc EXCEPT ![self] = "lcd_atomic"]
                     /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     nodes, edges, finalizedFlag, taskNode, 
                                     nextTaskId, generation, stitchCounter, 
                                     resolutionQueue, primed, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

lcd_atomic(self) == /\ pc[self] = "lcd_atomic"
                    /\ runningTask = self
                    /\ latchCount' = [latchCount EXCEPT ![latch_id[self]] = latchCount[latch_id[self]] - 1]
                    /\ eventFired' = [eventFired EXCEPT ![Latch[latch_id[self]].event.id] = IF   latchCount'[latch_id[self]] = 0
                                                                                              THEN TRUE
                                                                                              ELSE eventFired[Latch[latch_id[self]].event.id]]
                    /\ taskState' = (IF   latchCount'[latch_id[self]] = 0
                                     THEN [t \in Tasks |->
                                        IF   (t = self) \/ (t \in eventWaiters[Latch[latch_id[self]].event.id])
                                        THEN [state |-> Ready]
                                        ELSE taskState[t]]
                                     ELSE [taskState EXCEPT ![self] = [state |-> Ready]])
                    /\ eventWaiters' = [eventWaiters EXCEPT ![Latch[latch_id[self]].event.id] = IF   latchCount'[latch_id[self]] = 0
                                                                                                  THEN {}
                                                                                                  ELSE eventWaiters[Latch[latch_id[self]].event.id]]
                    /\ runningTask' = NoTask
                    /\ lastAction' = <<"LatchCountdown", latch_id[self], self>>
                    /\ pc' = [pc EXCEPT ![self] = "lcd_release"]
                    /\ UNCHANGED << lock, lockWaiters, conditionWaiters, 
                                    conditionFlag, queueItems, queueClosed, 
                                    joinWaiters, nodes, edges, finalizedFlag, 
                                    taskNode, nextTaskId, generation, 
                                    stitchCounter, resolutionQueue, primed, 
                                    workersCompleted, itemsProduced, 
                                    itemsConsumed, stack, latch_id, queue_id_, 
                                    item_to_put, item_put_done, queue_id_q, 
                                    item_got, queue_id >>

lcd_release(self) == /\ pc[self] = "lcd_release"
                     /\ runningTask = self
                     /\ Assert(lock[(Latch[latch_id[self]].lock.id)] = self, 
                               "Failure of assertion at line 731, column 1 of macro called at line 913, column 13.")
                     /\ IF lockWaiters[(Latch[latch_id[self]].lock.id)] = << >>
                           THEN /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = NoTask]
                                /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                /\ runningTask' = NoTask
                                /\ lastAction' = <<"ReleaseLock", (Latch[latch_id[self]].lock.id), self>>
                                /\ UNCHANGED lockWaiters
                           ELSE /\ LET nextOwner == Head(lockWaiters[(Latch[latch_id[self]].lock.id)]) IN
                                     /\ lock' = [lock EXCEPT ![(Latch[latch_id[self]].lock.id)] = nextOwner]
                                     /\ lockWaiters' = [lockWaiters EXCEPT ![(Latch[latch_id[self]].lock.id)] = Tail(lockWaiters[(Latch[latch_id[self]].lock.id)])]
                                     /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                        ![self] = [state |-> Ready]]
                                     /\ runningTask' = NoTask
                                     /\ lastAction' = <<"ReleaseLock", (Latch[latch_id[self]].lock.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "lcd_return"]
                     /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     nodes, edges, finalizedFlag, taskNode, 
                                     nextTaskId, generation, stitchCounter, 
                                     resolutionQueue, primed, workersCompleted, 
                                     itemsProduced, itemsConsumed, stack, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

lcd_return(self) == /\ pc[self] = "lcd_return"
                    /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                    /\ latch_id' = [latch_id EXCEPT ![self] = Head(stack[self]).latch_id]
                    /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                    /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                    lockWaiters, eventFired, eventWaiters, 
                                    conditionWaiters, conditionFlag, 
                                    queueItems, queueClosed, joinWaiters, 
                                    nodes, edges, finalizedFlag, taskNode, 
                                    nextTaskId, generation, stitchCounter, 
                                    resolutionQueue, primed, workersCompleted, 
                                    itemsProduced, itemsConsumed, lastAction, 
                                    queue_id_, item_to_put, item_put_done, 
                                    queue_id_q, item_got, queue_id >>

latch_countdown(self) == lcd_acquire(self) \/ lcd_atomic(self)
                            \/ lcd_release(self) \/ lcd_return(self)

qput_acquire(self) == /\ pc[self] = "qput_acquire"
                      /\ runningTask = self
                      /\ IF lock[(Queue[queue_id_[self]].lock.id)] = NoTask
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = self]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                 /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id_[self]].lock.id)], self)]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ lock' = lock
                      /\ pc' = [pc EXCEPT ![self] = "qput_wait_loop"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      nodes, edges, finalizedFlag, taskNode, 
                                      nextTaskId, generation, stitchCounter, 
                                      resolutionQueue, primed, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qput_wait_loop(self) == /\ pc[self] = "qput_wait_loop"
                        /\ runningTask = self
                        /\ IF QueueIsFull(queue_id_[self]) /\ ~queueClosed[queue_id_[self]]
                              THEN /\ Assert(lock[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = self, 
                                             "Failure of assertion at line 786, column 5 of macro called at line 932, column 9.")
                                   /\ LET hasWaiters == lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] # << >> IN
                                        LET nextOwner == IF lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] # << >>
                                                         THEN Head(lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id])
                                                         ELSE NoTask IN
                                          /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_[self]].not_full.id)] = conditionWaiters[(Queue[queue_id_[self]].not_full.id)] \union {self}]
                                          /\ lock' = [lock EXCEPT ![Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = nextOwner]
                                          /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_[self]].not_full.id)].lock.id] = IF hasWaiters
                                                                                                                                                THEN Tail(lockWaiters[Condition[(Queue[queue_id_[self]].not_full.id)].lock.id])
                                                                                                                                                ELSE << >>]
                                          /\ taskState' = IF hasWaiters
                                                             THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                                                     ![nextOwner] = [state |-> Ready]]
                                                             ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]]
                                          /\ runningTask' = NoTask
                                          /\ lastAction' = <<"ConditionWait", (Queue[queue_id_[self]].not_full.id), self>>
                                   /\ pc' = [pc EXCEPT ![self] = "qput_wait_loop"]
                                   /\ UNCHANGED item_put_done
                              ELSE /\ IF queueClosed[queue_id_[self]]
                                         THEN /\ item_put_done' = [item_put_done EXCEPT ![self] = TRUE]
                                              /\ pc' = [pc EXCEPT ![self] = "qput_release"]
                                         ELSE /\ pc' = [pc EXCEPT ![self] = "qput_do_put"]
                                              /\ UNCHANGED item_put_done
                                   /\ UNCHANGED << runningTask, taskState, 
                                                   lock, lockWaiters, 
                                                   conditionWaiters, 
                                                   lastAction >>
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionFlag, queueItems, queueClosed, 
                                        joinWaiters, nodes, edges, 
                                        finalizedFlag, taskNode, nextTaskId, 
                                        generation, stitchCounter, 
                                        resolutionQueue, primed, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, queue_id_q, 
                                        item_got, queue_id >>

qput_do_put(self) == /\ pc[self] = "qput_do_put"
                     /\ runningTask = self
                     /\ queueItems' = [queueItems EXCEPT ![queue_id_[self]] = Append(queueItems[queue_id_[self]], item_to_put[self])]
                     /\ Assert(lock[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id] = self, 
                               "Failure of assertion at line 813, column 5 of macro called at line 946, column 5.")
                     /\ LET hasWaiters == conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] # {} IN
                          LET waiter ==  IF conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] # {}
                                        THEN CHOOSE t \in conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] : TRUE
                                        ELSE NoTask IN
                            /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_[self]].not_empty.id)] = IF hasWaiters
                                                                                                                        THEN conditionWaiters[(Queue[queue_id_[self]].not_empty.id)] \ {waiter}
                                                                                                                        ELSE conditionWaiters[(Queue[queue_id_[self]].not_empty.id)]]
                            /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id] = IF hasWaiters
                                                                                                                                   THEN Append(lockWaiters[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id], waiter)
                                                                                                                                   ELSE lockWaiters[Condition[(Queue[queue_id_[self]].not_empty.id)].lock.id]]
                            /\ taskState' = IF hasWaiters
                                               THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                                       ![self] = [state |-> Ready]]
                                               ELSE [taskState EXCEPT ![self] = [state |-> Ready]]
                            /\ runningTask' = NoTask
                            /\ lastAction' = <<"ConditionNotify", (Queue[queue_id_[self]].not_empty.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "qput_release"]
                     /\ UNCHANGED << latchCount, lock, eventFired, 
                                     eventWaiters, conditionFlag, queueClosed, 
                                     joinWaiters, nodes, edges, finalizedFlag, 
                                     taskNode, nextTaskId, generation, 
                                     stitchCounter, resolutionQueue, primed, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, stack, latch_id, queue_id_, 
                                     item_to_put, item_put_done, queue_id_q, 
                                     item_got, queue_id >>

qput_release(self) == /\ pc[self] = "qput_release"
                      /\ runningTask = self
                      /\ Assert(lock[(Queue[queue_id_[self]].lock.id)] = self, 
                                "Failure of assertion at line 731, column 1 of macro called at line 950, column 5.")
                      /\ IF lockWaiters[(Queue[queue_id_[self]].lock.id)] = << >>
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = NoTask]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id_[self]].lock.id)]) IN
                                      /\ lock' = [lock EXCEPT ![(Queue[queue_id_[self]].lock.id)] = nextOwner]
                                      /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id_[self]].lock.id)])]
                                      /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                         ![self] = [state |-> Ready]]
                                      /\ runningTask' = NoTask
                                      /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_[self]].lock.id), self>>
                      /\ pc' = [pc EXCEPT ![self] = "qput_return"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      nodes, edges, finalizedFlag, taskNode, 
                                      nextTaskId, generation, stitchCounter, 
                                      resolutionQueue, primed, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qput_return(self) == /\ pc[self] = "qput_return"
                     /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                     /\ item_put_done' = [item_put_done EXCEPT ![self] = Head(stack[self]).item_put_done]
                     /\ queue_id_' = [queue_id_ EXCEPT ![self] = Head(stack[self]).queue_id_]
                     /\ item_to_put' = [item_to_put EXCEPT ![self] = Head(stack[self]).item_to_put]
                     /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                     /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                     lockWaiters, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     nodes, edges, finalizedFlag, taskNode, 
                                     nextTaskId, generation, stitchCounter, 
                                     resolutionQueue, primed, workersCompleted, 
                                     itemsProduced, itemsConsumed, lastAction, 
                                     latch_id, queue_id_q, item_got, queue_id >>

queue_put(self) == qput_acquire(self) \/ qput_wait_loop(self)
                      \/ qput_do_put(self) \/ qput_release(self)
                      \/ qput_return(self)

qget_acquire(self) == /\ pc[self] = "qget_acquire"
                      /\ runningTask = self
                      /\ IF lock[(Queue[queue_id_q[self]].lock.id)] = NoTask
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = self]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                 /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id_q[self]].lock.id)], self)]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ lock' = lock
                      /\ pc' = [pc EXCEPT ![self] = "qget_wait_loop"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      nodes, edges, finalizedFlag, taskNode, 
                                      nextTaskId, generation, stitchCounter, 
                                      resolutionQueue, primed, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qget_wait_loop(self) == /\ pc[self] = "qget_wait_loop"
                        /\ runningTask = self
                        /\ IF QueueIsEmpty(queue_id_q[self]) /\ ~queueClosed[queue_id_q[self]]
                              THEN /\ Assert(lock[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = self, 
                                             "Failure of assertion at line 786, column 5 of macro called at line 968, column 9.")
                                   /\ LET hasWaiters == lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] # << >> IN
                                        LET nextOwner == IF lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] # << >>
                                                         THEN Head(lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id])
                                                         ELSE NoTask IN
                                          /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_q[self]].not_empty.id)] = conditionWaiters[(Queue[queue_id_q[self]].not_empty.id)] \union {self}]
                                          /\ lock' = [lock EXCEPT ![Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = nextOwner]
                                          /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id] = IF hasWaiters
                                                                                                                                                  THEN Tail(lockWaiters[Condition[(Queue[queue_id_q[self]].not_empty.id)].lock.id])
                                                                                                                                                  ELSE << >>]
                                          /\ taskState' = IF hasWaiters
                                                             THEN [taskState EXCEPT ![self] = [state |-> WaitingCondition],
                                                                                     ![nextOwner] = [state |-> Ready]]
                                                             ELSE [taskState EXCEPT ![self] = [state |-> WaitingCondition]]
                                          /\ runningTask' = NoTask
                                          /\ lastAction' = <<"ConditionWait", (Queue[queue_id_q[self]].not_empty.id), self>>
                                   /\ pc' = [pc EXCEPT ![self] = "qget_wait_loop"]
                                   /\ UNCHANGED item_got
                              ELSE /\ IF queueClosed[queue_id_q[self]] /\ QueueIsEmpty(queue_id_q[self])
                                         THEN /\ item_got' = [item_got EXCEPT ![self] = NoTask]
                                              /\ pc' = [pc EXCEPT ![self] = "qget_release"]
                                         ELSE /\ pc' = [pc EXCEPT ![self] = "qget_do_get"]
                                              /\ UNCHANGED item_got
                                   /\ UNCHANGED << runningTask, taskState, 
                                                   lock, lockWaiters, 
                                                   conditionWaiters, 
                                                   lastAction >>
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionFlag, queueItems, queueClosed, 
                                        joinWaiters, nodes, edges, 
                                        finalizedFlag, taskNode, nextTaskId, 
                                        generation, stitchCounter, 
                                        resolutionQueue, primed, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, item_put_done, 
                                        queue_id_q, queue_id >>

qget_do_get(self) == /\ pc[self] = "qget_do_get"
                     /\ runningTask = self
                     /\ item_got' = [item_got EXCEPT ![self] = Head(queueItems[queue_id_q[self]])]
                     /\ queueItems' = [queueItems EXCEPT ![queue_id_q[self]] = Tail(queueItems[queue_id_q[self]])]
                     /\ Assert(lock[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id] = self, 
                               "Failure of assertion at line 813, column 5 of macro called at line 983, column 5.")
                     /\ LET hasWaiters == conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] # {} IN
                          LET waiter ==  IF conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] # {}
                                        THEN CHOOSE t \in conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] : TRUE
                                        ELSE NoTask IN
                            /\ conditionWaiters' = [conditionWaiters EXCEPT ![(Queue[queue_id_q[self]].not_full.id)] = IF hasWaiters
                                                                                                                        THEN conditionWaiters[(Queue[queue_id_q[self]].not_full.id)] \ {waiter}
                                                                                                                        ELSE conditionWaiters[(Queue[queue_id_q[self]].not_full.id)]]
                            /\ lockWaiters' = [lockWaiters EXCEPT ![Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id] = IF hasWaiters
                                                                                                                                   THEN Append(lockWaiters[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id], waiter)
                                                                                                                                   ELSE lockWaiters[Condition[(Queue[queue_id_q[self]].not_full.id)].lock.id]]
                            /\ taskState' = IF hasWaiters
                                               THEN [taskState EXCEPT ![waiter] = [state |-> WaitingLock],
                                                                       ![self] = [state |-> Ready]]
                                               ELSE [taskState EXCEPT ![self] = [state |-> Ready]]
                            /\ runningTask' = NoTask
                            /\ lastAction' = <<"ConditionNotify", (Queue[queue_id_q[self]].not_full.id), self>>
                     /\ pc' = [pc EXCEPT ![self] = "qget_release"]
                     /\ UNCHANGED << latchCount, lock, eventFired, 
                                     eventWaiters, conditionFlag, queueClosed, 
                                     joinWaiters, nodes, edges, finalizedFlag, 
                                     taskNode, nextTaskId, generation, 
                                     stitchCounter, resolutionQueue, primed, 
                                     workersCompleted, itemsProduced, 
                                     itemsConsumed, stack, latch_id, queue_id_, 
                                     item_to_put, item_put_done, queue_id_q, 
                                     queue_id >>

qget_release(self) == /\ pc[self] = "qget_release"
                      /\ runningTask = self
                      /\ Assert(lock[(Queue[queue_id_q[self]].lock.id)] = self, 
                                "Failure of assertion at line 731, column 1 of macro called at line 987, column 5.")
                      /\ IF lockWaiters[(Queue[queue_id_q[self]].lock.id)] = << >>
                            THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = NoTask]
                                 /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                 /\ runningTask' = NoTask
                                 /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_q[self]].lock.id), self>>
                                 /\ UNCHANGED lockWaiters
                            ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id_q[self]].lock.id)]) IN
                                      /\ lock' = [lock EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = nextOwner]
                                      /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id_q[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id_q[self]].lock.id)])]
                                      /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                         ![self] = [state |-> Ready]]
                                      /\ runningTask' = NoTask
                                      /\ lastAction' = <<"ReleaseLock", (Queue[queue_id_q[self]].lock.id), self>>
                      /\ pc' = [pc EXCEPT ![self] = "qget_return"]
                      /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      nodes, edges, finalizedFlag, taskNode, 
                                      nextTaskId, generation, stitchCounter, 
                                      resolutionQueue, primed, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

qget_return(self) == /\ pc[self] = "qget_return"
                     /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                     /\ item_got' = [item_got EXCEPT ![self] = Head(stack[self]).item_got]
                     /\ queue_id_q' = [queue_id_q EXCEPT ![self] = Head(stack[self]).queue_id_q]
                     /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                     /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                     lockWaiters, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     nodes, edges, finalizedFlag, taskNode, 
                                     nextTaskId, generation, stitchCounter, 
                                     resolutionQueue, primed, workersCompleted, 
                                     itemsProduced, itemsConsumed, lastAction, 
                                     latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id >>

queue_get(self) == qget_acquire(self) \/ qget_wait_loop(self)
                      \/ qget_do_get(self) \/ qget_release(self)
                      \/ qget_return(self)

qclose_acquire(self) == /\ pc[self] = "qclose_acquire"
                        /\ runningTask = self
                        /\ IF lock[(Queue[queue_id[self]].lock.id)] = NoTask
                              THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = self]
                                   /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"AcquireLock", "Immediate", (Queue[queue_id[self]].lock.id), self>>
                                   /\ UNCHANGED lockWaiters
                              ELSE /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingLock]]
                                   /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id[self]].lock.id)] = Append(lockWaiters[(Queue[queue_id[self]].lock.id)], self)]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"AcquireLock", "Waiting", (Queue[queue_id[self]].lock.id), self>>
                                   /\ lock' = lock
                        /\ pc' = [pc EXCEPT ![self] = "qclose_do_close"]
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionWaiters, conditionFlag, 
                                        queueItems, queueClosed, joinWaiters, 
                                        nodes, edges, finalizedFlag, taskNode, 
                                        nextTaskId, generation, stitchCounter, 
                                        resolutionQueue, primed, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, item_put_done, 
                                        queue_id_q, item_got, queue_id >>

qclose_do_close(self) == /\ pc[self] = "qclose_do_close"
                         /\ runningTask = self
                         /\ queueClosed' = [queueClosed EXCEPT ![queue_id[self]] = TRUE]
                         /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                         /\ runningTask' = NoTask
                         /\ lastAction' = <<"QueueClose", queue_id[self], self>>
                         /\ pc' = [pc EXCEPT ![self] = "qclose_release"]
                         /\ UNCHANGED << latchCount, lock, lockWaiters, 
                                         eventFired, eventWaiters, 
                                         conditionWaiters, conditionFlag, 
                                         queueItems, joinWaiters, nodes, edges, 
                                         finalizedFlag, taskNode, nextTaskId, 
                                         generation, stitchCounter, 
                                         resolutionQueue, primed, 
                                         workersCompleted, itemsProduced, 
                                         itemsConsumed, stack, latch_id, 
                                         queue_id_, item_to_put, item_put_done, 
                                         queue_id_q, item_got, queue_id >>

qclose_release(self) == /\ pc[self] = "qclose_release"
                        /\ runningTask = self
                        /\ Assert(lock[(Queue[queue_id[self]].lock.id)] = self, 
                                  "Failure of assertion at line 731, column 1 of macro called at line 1009, column 5.")
                        /\ IF lockWaiters[(Queue[queue_id[self]].lock.id)] = << >>
                              THEN /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = NoTask]
                                   /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                                   /\ runningTask' = NoTask
                                   /\ lastAction' = <<"ReleaseLock", (Queue[queue_id[self]].lock.id), self>>
                                   /\ UNCHANGED lockWaiters
                              ELSE /\ LET nextOwner == Head(lockWaiters[(Queue[queue_id[self]].lock.id)]) IN
                                        /\ lock' = [lock EXCEPT ![(Queue[queue_id[self]].lock.id)] = nextOwner]
                                        /\ lockWaiters' = [lockWaiters EXCEPT ![(Queue[queue_id[self]].lock.id)] = Tail(lockWaiters[(Queue[queue_id[self]].lock.id)])]
                                        /\ taskState' = [taskState EXCEPT ![nextOwner] = [state |-> Ready],
                                                                           ![self] = [state |-> Ready]]
                                        /\ runningTask' = NoTask
                                        /\ lastAction' = <<"ReleaseLock", (Queue[queue_id[self]].lock.id), self>>
                        /\ pc' = [pc EXCEPT ![self] = "qclose_return"]
                        /\ UNCHANGED << latchCount, eventFired, eventWaiters, 
                                        conditionWaiters, conditionFlag, 
                                        queueItems, queueClosed, joinWaiters, 
                                        nodes, edges, finalizedFlag, taskNode, 
                                        nextTaskId, generation, stitchCounter, 
                                        resolutionQueue, primed, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, stack, latch_id, 
                                        queue_id_, item_to_put, item_put_done, 
                                        queue_id_q, item_got, queue_id >>

qclose_return(self) == /\ pc[self] = "qclose_return"
                       /\ pc' = [pc EXCEPT ![self] = Head(stack[self]).pc]
                       /\ queue_id' = [queue_id EXCEPT ![self] = Head(stack[self]).queue_id]
                       /\ stack' = [stack EXCEPT ![self] = Tail(stack[self])]
                       /\ UNCHANGED << runningTask, taskState, latchCount, 
                                       lock, lockWaiters, eventFired, 
                                       eventWaiters, conditionWaiters, 
                                       conditionFlag, queueItems, queueClosed, 
                                       joinWaiters, nodes, edges, 
                                       finalizedFlag, taskNode, nextTaskId, 
                                       generation, stitchCounter, 
                                       resolutionQueue, primed, 
                                       workersCompleted, itemsProduced, 
                                       itemsConsumed, lastAction, latch_id, 
                                       queue_id_, item_to_put, item_put_done, 
                                       queue_id_q, item_got >>

queue_close(self) == qclose_acquire(self) \/ qclose_do_close(self)
                        \/ qclose_release(self) \/ qclose_return(self)

sched == /\ pc[99] = "sched"
         /\ runningTask = NoTask /\ \E t \in Tasks : IsSchedulable(t)
         /\ \E t \in {t \in Tasks : IsSchedulable(t)}:
              /\ runningTask' = t
              /\ taskState' = [taskState EXCEPT ![t] = [state |-> Running]]
              /\ lastAction' = <<"Scheduler", "pick", t>>
         /\ pc' = [pc EXCEPT ![99] = "sched"]
         /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                         eventWaiters, conditionWaiters, conditionFlag, 
                         queueItems, queueClosed, joinWaiters, nodes, edges, 
                         finalizedFlag, taskNode, nextTaskId, generation, 
                         stitchCounter, resolutionQueue, primed, 
                         workersCompleted, itemsProduced, itemsConsumed, stack, 
                         latch_id, queue_id_, item_to_put, item_put_done, 
                         queue_id_q, item_got, queue_id >>

Scheduler == sched

resolve == /\ pc[98] = "resolve"
           /\ AllPrimed /\ resolutionQueue # {}
           /\ \E demanded \in resolutionQueue:
                \E sol \in {s \in SolutionNodes(demanded) :
                            IsWaitingForStartNextGeneration(s) /\
                            (s = demanded \/ s \notin resolutionQueue)}:
                  /\ taskState' = [taskState EXCEPT ![sol] = [state |-> Ready]]
                  /\ resolutionQueue' = resolutionQueue \ {demanded}
                  /\ stitchCounter' =              [e \in DOMAIN stitchCounter |->
                                      IF e \in EdgesToStitch(demanded)
                                      THEN stitchCounter[e] + 1
                                      ELSE stitchCounter[e]]
                  /\ lastAction' = <<"Resolver", "demanded", demanded, "sol", sol>>
           /\ pc' = [pc EXCEPT ![98] = "resolve"]
           /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                           eventFired, eventWaiters, conditionWaiters, 
                           conditionFlag, queueItems, queueClosed, joinWaiters, 
                           nodes, edges, finalizedFlag, taskNode, nextTaskId, 
                           generation, primed, workersCompleted, itemsProduced, 
                           itemsConsumed, stack, latch_id, queue_id_, 
                           item_to_put, item_put_done, queue_id_q, item_got, 
                           queue_id >>

Resolver == resolve

wake == /\ pc[97] = "wake"
        /\ \E t \in Tasks : IsSleeping(t)
        /\ \E t \in {u \in Tasks : IsSleeping(u)}:
             /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
             /\ lastAction' = <<"ExternalWake", t>>
        /\ pc' = [pc EXCEPT ![97] = "wake"]
        /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, eventFired, 
                        eventWaiters, conditionWaiters, conditionFlag, 
                        queueItems, queueClosed, joinWaiters, nodes, edges, 
                        finalizedFlag, taskNode, nextTaskId, generation, 
                        stitchCounter, resolutionQueue, primed, 
                        workersCompleted, itemsProduced, itemsConsumed, stack, 
                        latch_id, queue_id_, item_to_put, item_put_done, 
                        queue_id_q, item_got, queue_id >>

ExternalWake == wake

build_graph(self) == /\ pc[self] = "build_graph"
                     /\ runningTask = self
                     /\ pc' = [pc EXCEPT ![self] = "l1"]
                     /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                     lockWaiters, eventFired, eventWaiters, 
                                     conditionWaiters, conditionFlag, 
                                     queueItems, queueClosed, joinWaiters, 
                                     nodes, edges, finalizedFlag, taskNode, 
                                     nextTaskId, generation, stitchCounter, 
                                     resolutionQueue, primed, workersCompleted, 
                                     itemsProduced, itemsConsumed, lastAction, 
                                     stack, latch_id, queue_id_, item_to_put, 
                                     item_put_done, queue_id_q, item_got, 
                                     queue_id >>

l1(self) == /\ pc[self] = "l1"
            /\ Assert("Counter" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1079, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "counter"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1079, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1079, column 5.")
            /\ LET newNode == [id |-> "counter", type |-> "Counter"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "l2"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

l2(self) == /\ pc[self] = "l2"
            /\ Assert("WordGen" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1081, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "wordgen_en"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1081, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1081, column 5.")
            /\ LET newNode == [id |-> "wordgen_en", type |-> "WordGen"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "l3"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

l3(self) == /\ pc[self] = "l3"
            /\ Assert("WordGen" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1083, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "wordgen_sp"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1083, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1083, column 5.")
            /\ LET newNode == [id |-> "wordgen_sp", type |-> "WordGen"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "l4"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

l4(self) == /\ pc[self] = "l4"
            /\ Assert("Accumulator" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1085, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "accumulator"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1085, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1085, column 5.")
            /\ LET newNode == [id |-> "accumulator", type |-> "Accumulator"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "l5"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

l5(self) == /\ pc[self] = "l5"
            /\ Assert("Constant" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1087, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "const_en"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1087, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1087, column 5.")
            /\ LET newNode == [id |-> "const_en", type |-> "Constant"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "l6"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

l6(self) == /\ pc[self] = "l6"
            /\ Assert("Constant" \in DOMAIN NodeTypes, 
                      "Failure of assertion at line 861, column 5 of macro called at line 1089, column 5.")
            /\ Assert(~(\E n \in nodes : n.id = "const_sp"), 
                      "Failure of assertion at line 863, column 5 of macro called at line 1089, column 5.")
            /\ Assert(nextTaskId <= 6, 
                      "Failure of assertion at line 865, column 5 of macro called at line 1089, column 5.")
            /\ LET newNode == [id |-> "const_sp", type |-> "Constant"] IN
                 /\ nodes' = (nodes \union {newNode})
                 /\ taskNode' = [taskNode EXCEPT ![nextTaskId] = newNode]
                 /\ generation' = generation @@ (newNode :> <<>>)
                 /\ primed' = primed @@ (newNode :> FALSE)
                 /\ taskState' = [taskState EXCEPT ![nextTaskId] = [state |-> Ready]]
            /\ nextTaskId' = nextTaskId + 1
            /\ pc' = [pc EXCEPT ![self] = "connect_edges"]
            /\ UNCHANGED << runningTask, latchCount, lock, lockWaiters, 
                            eventFired, eventWaiters, conditionWaiters, 
                            conditionFlag, queueItems, queueClosed, 
                            joinWaiters, edges, finalizedFlag, stitchCounter, 
                            resolutionQueue, workersCompleted, itemsProduced, 
                            itemsConsumed, lastAction, stack, latch_id, 
                            queue_id_, item_to_put, item_put_done, queue_id_q, 
                            item_got, queue_id >>

connect_edges(self) == /\ pc[self] = "connect_edges"
                       /\ runningTask = self
                       /\ pc' = [pc EXCEPT ![self] = "l7"]
                       /\ UNCHANGED << runningTask, taskState, latchCount, 
                                       lock, lockWaiters, eventFired, 
                                       eventWaiters, conditionWaiters, 
                                       conditionFlag, queueItems, queueClosed, 
                                       joinWaiters, nodes, edges, 
                                       finalizedFlag, taskNode, nextTaskId, 
                                       generation, stitchCounter, 
                                       resolutionQueue, primed, 
                                       workersCompleted, itemsProduced, 
                                       itemsConsumed, lastAction, stack, 
                                       latch_id, queue_id_, item_to_put, 
                                       item_put_done, queue_id_q, item_got, 
                                       queue_id >>

l7(self) == /\ pc[self] = "l7"
            /\ LET srcNode == CHOOSE n \in nodes : n.id = "counter" IN
                 LET dstNode == CHOOSE n \in nodes : n.id = "wordgen_en" IN
                   edges' = (         edges \union {[
                                 src |-> [node |-> srcNode, port |-> 0],
                                 dst |-> [node |-> dstNode, port |-> 0]
                             ]})
            /\ pc' = [pc EXCEPT ![self] = "l8"]
            /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                            lockWaiters, eventFired, eventWaiters, 
                            conditionWaiters, conditionFlag, queueItems, 
                            queueClosed, joinWaiters, nodes, finalizedFlag, 
                            taskNode, nextTaskId, generation, stitchCounter, 
                            resolutionQueue, primed, workersCompleted, 
                            itemsProduced, itemsConsumed, lastAction, stack, 
                            latch_id, queue_id_, item_to_put, item_put_done, 
                            queue_id_q, item_got, queue_id >>

l8(self) == /\ pc[self] = "l8"
            /\ LET srcNode == CHOOSE n \in nodes : n.id = "counter" IN
                 LET dstNode == CHOOSE n \in nodes : n.id = "wordgen_sp" IN
                   edges' = (         edges \union {[
                                 src |-> [node |-> srcNode, port |-> 0],
                                 dst |-> [node |-> dstNode, port |-> 0]
                             ]})
            /\ pc' = [pc EXCEPT ![self] = "l9"]
            /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                            lockWaiters, eventFired, eventWaiters, 
                            conditionWaiters, conditionFlag, queueItems, 
                            queueClosed, joinWaiters, nodes, finalizedFlag, 
                            taskNode, nextTaskId, generation, stitchCounter, 
                            resolutionQueue, primed, workersCompleted, 
                            itemsProduced, itemsConsumed, lastAction, stack, 
                            latch_id, queue_id_, item_to_put, item_put_done, 
                            queue_id_q, item_got, queue_id >>

l9(self) == /\ pc[self] = "l9"
            /\ LET srcNode == CHOOSE n \in nodes : n.id = "wordgen_en" IN
                 LET dstNode == CHOOSE n \in nodes : n.id = "accumulator" IN
                   edges' = (         edges \union {[
                                 src |-> [node |-> srcNode, port |-> 0],
                                 dst |-> [node |-> dstNode, port |-> 0]
                             ]})
            /\ pc' = [pc EXCEPT ![self] = "l10"]
            /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                            lockWaiters, eventFired, eventWaiters, 
                            conditionWaiters, conditionFlag, queueItems, 
                            queueClosed, joinWaiters, nodes, finalizedFlag, 
                            taskNode, nextTaskId, generation, stitchCounter, 
                            resolutionQueue, primed, workersCompleted, 
                            itemsProduced, itemsConsumed, lastAction, stack, 
                            latch_id, queue_id_, item_to_put, item_put_done, 
                            queue_id_q, item_got, queue_id >>

l10(self) == /\ pc[self] = "l10"
             /\ LET srcNode == CHOOSE n \in nodes : n.id = "wordgen_sp" IN
                  LET dstNode == CHOOSE n \in nodes : n.id = "accumulator" IN
                    edges' = (         edges \union {[
                                  src |-> [node |-> srcNode, port |-> 0],
                                  dst |-> [node |-> dstNode, port |-> 1]
                              ]})
             /\ pc' = [pc EXCEPT ![self] = "l11"]
             /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                             lockWaiters, eventFired, eventWaiters, 
                             conditionWaiters, conditionFlag, queueItems, 
                             queueClosed, joinWaiters, nodes, finalizedFlag, 
                             taskNode, nextTaskId, generation, stitchCounter, 
                             resolutionQueue, primed, workersCompleted, 
                             itemsProduced, itemsConsumed, lastAction, stack, 
                             latch_id, queue_id_, item_to_put, item_put_done, 
                             queue_id_q, item_got, queue_id >>

l11(self) == /\ pc[self] = "l11"
             /\ LET srcNode == CHOOSE n \in nodes : n.id = "accumulator" IN
                  LET dstNode == CHOOSE n \in nodes : n.id = "counter" IN
                    edges' = (         edges \union {[
                                  src |-> [node |-> srcNode, port |-> 0],
                                  dst |-> [node |-> dstNode, port |-> 0]
                              ]})
             /\ pc' = [pc EXCEPT ![self] = "l12"]
             /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                             lockWaiters, eventFired, eventWaiters, 
                             conditionWaiters, conditionFlag, queueItems, 
                             queueClosed, joinWaiters, nodes, finalizedFlag, 
                             taskNode, nextTaskId, generation, stitchCounter, 
                             resolutionQueue, primed, workersCompleted, 
                             itemsProduced, itemsConsumed, lastAction, stack, 
                             latch_id, queue_id_, item_to_put, item_put_done, 
                             queue_id_q, item_got, queue_id >>

l12(self) == /\ pc[self] = "l12"
             /\ LET srcNode == CHOOSE n \in nodes : n.id = "const_en" IN
                  LET dstNode == CHOOSE n \in nodes : n.id = "wordgen_en" IN
                    edges' = (         edges \union {[
                                  src |-> [node |-> srcNode, port |-> 0],
                                  dst |-> [node |-> dstNode, port |-> 1]
                              ]})
             /\ pc' = [pc EXCEPT ![self] = "l13"]
             /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                             lockWaiters, eventFired, eventWaiters, 
                             conditionWaiters, conditionFlag, queueItems, 
                             queueClosed, joinWaiters, nodes, finalizedFlag, 
                             taskNode, nextTaskId, generation, stitchCounter, 
                             resolutionQueue, primed, workersCompleted, 
                             itemsProduced, itemsConsumed, lastAction, stack, 
                             latch_id, queue_id_, item_to_put, item_put_done, 
                             queue_id_q, item_got, queue_id >>

l13(self) == /\ pc[self] = "l13"
             /\ LET srcNode == CHOOSE n \in nodes : n.id = "const_sp" IN
                  LET dstNode == CHOOSE n \in nodes : n.id = "wordgen_sp" IN
                    edges' = (         edges \union {[
                                  src |-> [node |-> srcNode, port |-> 0],
                                  dst |-> [node |-> dstNode, port |-> 1]
                              ]})
             /\ pc' = [pc EXCEPT ![self] = "finalize_graph"]
             /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                             lockWaiters, eventFired, eventWaiters, 
                             conditionWaiters, conditionFlag, queueItems, 
                             queueClosed, joinWaiters, nodes, finalizedFlag, 
                             taskNode, nextTaskId, generation, stitchCounter, 
                             resolutionQueue, primed, workersCompleted, 
                             itemsProduced, itemsConsumed, lastAction, stack, 
                             latch_id, queue_id_, item_to_put, item_put_done, 
                             queue_id_q, item_got, queue_id >>

finalize_graph(self) == /\ pc[self] = "finalize_graph"
                        /\ runningTask = self
                        /\ finalizedFlag' = TRUE
                        /\ runningTask' = NoTask
                        /\ taskState' = [taskState EXCEPT ![self] = [state |-> Ready]]
                        /\ pc' = [pc EXCEPT ![self] = "wait_all_primed"]
                        /\ UNCHANGED << latchCount, lock, lockWaiters, 
                                        eventFired, eventWaiters, 
                                        conditionWaiters, conditionFlag, 
                                        queueItems, queueClosed, joinWaiters, 
                                        nodes, edges, taskNode, nextTaskId, 
                                        generation, stitchCounter, 
                                        resolutionQueue, primed, 
                                        workersCompleted, itemsProduced, 
                                        itemsConsumed, lastAction, stack, 
                                        latch_id, queue_id_, item_to_put, 
                                        item_put_done, queue_id_q, item_got, 
                                        queue_id >>

wait_all_primed(self) == /\ pc[self] = "wait_all_primed"
                         /\ runningTask = self
                         /\ AllPrimed
                         /\ pc' = [pc EXCEPT ![self] = "main_done"]
                         /\ UNCHANGED << runningTask, taskState, latchCount, 
                                         lock, lockWaiters, eventFired, 
                                         eventWaiters, conditionWaiters, 
                                         conditionFlag, queueItems, 
                                         queueClosed, joinWaiters, nodes, 
                                         edges, finalizedFlag, taskNode, 
                                         nextTaskId, generation, stitchCounter, 
                                         resolutionQueue, primed, 
                                         workersCompleted, itemsProduced, 
                                         itemsConsumed, lastAction, stack, 
                                         latch_id, queue_id_, item_to_put, 
                                         item_put_done, queue_id_q, item_got, 
                                         queue_id >>

main_done(self) == /\ pc[self] = "main_done"
                   /\ runningTask = self
                   /\ taskState' =              [t \in Tasks |->
                                       CASE t = self                -> [state |-> Done]
                                           [] t \in joinWaiters[self] -> [state |-> Ready]
                                           [] OTHER                   -> taskState[t]
                                   ]
                   /\ joinWaiters' = [joinWaiters EXCEPT ![self] = {}]
                   /\ runningTask' = NoTask
                   /\ lastAction' = <<"Complete", self>>
                   /\ pc' = [pc EXCEPT ![self] = "main_dummy_pc"]
                   /\ UNCHANGED << latchCount, lock, lockWaiters, eventFired, 
                                   eventWaiters, conditionWaiters, 
                                   conditionFlag, queueItems, queueClosed, 
                                   nodes, edges, finalizedFlag, taskNode, 
                                   nextTaskId, generation, stitchCounter, 
                                   resolutionQueue, primed, workersCompleted, 
                                   itemsProduced, itemsConsumed, stack, 
                                   latch_id, queue_id_, item_to_put, 
                                   item_put_done, queue_id_q, item_got, 
                                   queue_id >>

main_dummy_pc(self) == /\ pc[self] = "main_dummy_pc"
                       /\ TRUE
                       /\ pc' = [pc EXCEPT ![self] = "Done"]
                       /\ UNCHANGED << runningTask, taskState, latchCount, 
                                       lock, lockWaiters, eventFired, 
                                       eventWaiters, conditionWaiters, 
                                       conditionFlag, queueItems, queueClosed, 
                                       joinWaiters, nodes, edges, 
                                       finalizedFlag, taskNode, nextTaskId, 
                                       generation, stitchCounter, 
                                       resolutionQueue, primed, 
                                       workersCompleted, itemsProduced, 
                                       itemsConsumed, lastAction, stack, 
                                       latch_id, queue_id_, item_to_put, 
                                       item_put_done, queue_id_q, item_got, 
                                       queue_id >>

Main(self) == build_graph(self) \/ l1(self) \/ l2(self) \/ l3(self)
                 \/ l4(self) \/ l5(self) \/ l6(self) \/ connect_edges(self)
                 \/ l7(self) \/ l8(self) \/ l9(self) \/ l10(self)
                 \/ l11(self) \/ l12(self) \/ l13(self)
                 \/ finalize_graph(self) \/ wait_all_primed(self)
                 \/ main_done(self) \/ main_dummy_pc(self)

node_init(self) == /\ pc[self] = "node_init"
                   /\ TaskHasNode(self) /\ finalizedFlag
                   /\ pc' = [pc EXCEPT ![self] = "node_loop"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, nodes, edges, 
                                   finalizedFlag, taskNode, nextTaskId, 
                                   generation, stitchCounter, resolutionQueue, 
                                   primed, workersCompleted, itemsProduced, 
                                   itemsConsumed, lastAction, stack, latch_id, 
                                   queue_id_, item_to_put, item_put_done, 
                                   queue_id_q, item_got, queue_id >>

node_loop(self) == /\ pc[self] = "node_loop"
                   /\ pc' = [pc EXCEPT ![self] = "node_wait_for_next_gen"]
                   /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                   lockWaiters, eventFired, eventWaiters, 
                                   conditionWaiters, conditionFlag, queueItems, 
                                   queueClosed, joinWaiters, nodes, edges, 
                                   finalizedFlag, taskNode, nextTaskId, 
                                   generation, stitchCounter, resolutionQueue, 
                                   primed, workersCompleted, itemsProduced, 
                                   itemsConsumed, lastAction, stack, latch_id, 
                                   queue_id_, item_to_put, item_put_done, 
                                   queue_id_q, item_got, queue_id >>

node_wait_for_next_gen(self) == /\ pc[self] = "node_wait_for_next_gen"
                                /\ runningTask = self
                                /\ LET myNode == taskNode[self] IN
                                     /\ taskState' = [taskState EXCEPT ![self] = [state |-> WaitingForStartNextGeneration]]
                                     /\ primed' = [primed EXCEPT ![myNode] = TRUE]
                                     /\ runningTask' = NoTask
                                     /\ lastAction' = <<"WaitForNextGen", self, myNode.id>>
                                /\ pc' = [pc EXCEPT ![self] = "node_execute"]
                                /\ UNCHANGED << latchCount, lock, lockWaiters, 
                                                eventFired, eventWaiters, 
                                                conditionWaiters, 
                                                conditionFlag, queueItems, 
                                                queueClosed, joinWaiters, 
                                                nodes, edges, finalizedFlag, 
                                                taskNode, nextTaskId, 
                                                generation, stitchCounter, 
                                                resolutionQueue, 
                                                workersCompleted, 
                                                itemsProduced, itemsConsumed, 
                                                stack, latch_id, queue_id_, 
                                                item_to_put, item_put_done, 
                                                queue_id_q, item_got, queue_id >>

node_execute(self) == /\ pc[self] = "node_execute"
                      /\ runningTask = self
                      /\ LET myNode == taskNode[self] IN
                           LET newGen == IncGeneration(generation[myNode], 0) IN
                             /\ generation' = [generation EXCEPT ![myNode] = newGen]
                             /\ resolutionQueue' = (               resolutionQueue \union
                                                    {e.dst.node : e \in {edge \in edges : edge.src.node = myNode}})
                             /\ lastAction' = <<"NodeExecute", self, myNode.id, newGen>>
                      /\ pc' = [pc EXCEPT ![self] = "node_loop"]
                      /\ UNCHANGED << runningTask, taskState, latchCount, lock, 
                                      lockWaiters, eventFired, eventWaiters, 
                                      conditionWaiters, conditionFlag, 
                                      queueItems, queueClosed, joinWaiters, 
                                      nodes, edges, finalizedFlag, taskNode, 
                                      nextTaskId, stitchCounter, primed, 
                                      workersCompleted, itemsProduced, 
                                      itemsConsumed, stack, latch_id, 
                                      queue_id_, item_to_put, item_put_done, 
                                      queue_id_q, item_got, queue_id >>

NodeTask(self) == node_init(self) \/ node_loop(self)
                     \/ node_wait_for_next_gen(self) \/ node_execute(self)

Next == Scheduler \/ Resolver \/ ExternalWake
           \/ (\E self \in ProcSet:  \/ latch_countdown(self) \/ queue_put(self)
                                     \/ queue_get(self) \/ queue_close(self))
           \/ (\E self \in {0}: Main(self))
           \/ (\E self \in 1..6: NodeTask(self))

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Scheduler)
        /\ WF_vars(Resolver)
        /\ WF_vars(ExternalWake)
        /\ \A self \in {0} : WF_vars(Main(self))
        /\ \A self \in 1..6 : WF_vars(NodeTask(self))

\* END TRANSLATION 
======================
