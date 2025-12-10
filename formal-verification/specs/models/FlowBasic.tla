---------------------------- MODULE FlowSpec ----------------------------
EXTENDS Naturals

CONSTANTS Nodes, Edges, BreakEdge

\* One task per node, queues for barriers
NumTasks == Cardinality(Nodes)
NumQueues == NumTasks * 2  \* barrier0 and barrier1 per node

ConstQueueSize(q) == 10

\* Instantiate event loop - tasks are 0..NumTasks-1, queues 0..NumQueues-1  
EL == INSTANCE EventLoop WITH
    MaxTaskId <- NumTasks - 1,
    MaxQueueId <- NumQueues - 1,
    MaxQueueSize <- ConstQueueSize

\* Map nodes to tasks and barrier queues
TaskOf(n) == n  \* or some bijection
Barrier0Queue(n) == n * 2
Barrier1Queue(n) == n * 2 + 1

\* Flow-specific state
VARIABLES
    pc,              \* pc[n] \in {"wait_gen", "gather", "execute", "wait_barrier", "push", "enqueue"}
    generation,      \* generation[n] = int (simplified from tuple)
    lastSeen,        \* lastSeen[n][u] = generation of u when n last ran
    resolutionQueue  \* set of demanded nodes

flowVars == <<pc, generation, lastSeen, resolutionQueue>>
allVars == <<EL!allVars, flowVars>>  \* combines event loop vars with flow vars

\* ===== NODE TASK ACTIONS =====
\* Each action: precondition on pc AND event loop state, updates both

\* Node yields "wait for next generation" - becomes sleeping
NodeYieldsWait(n) ==
    /\ pc[n] = "wait_gen"
    /\ EL!IsRunning(TaskOf(n))
    /\ EL!taskState' = [EL!taskState EXCEPT ![TaskOf(n)] = [state |-> EL!Sleeping]]
    /\ UNCHANGED <<pc, flowVars>>  \* pc stays, will advance when woken by resolver

\* Node is woken by resolver, advances to gather
NodeWokenByResolver(n) ==
    /\ pc[n] = "wait_gen"
    /\ EL!IsSleeping(TaskOf(n))
    /\ n \in SolutionSet(CHOOSE d \in resolutionQueue : TRUE)  \* n is in some solution
    /\ EL!taskState' = [EL!taskState EXCEPT ![TaskOf(n)] = [state |-> EL!Ready]]
    /\ pc' = [pc EXCEPT ![n] = "gather"]
    /\ UNCHANGED <<generation, lastSeen, resolutionQueue>>

\* Node does barrier wait - BLOCKS (get on empty queue)
NodeBarrierBlocks(n) ==
    /\ pc[n] = "wait_barrier"
    /\ EL!YieldGetBlocks(TaskOf(n), Barrier0Queue(n))
    /\ UNCHANGED flowVars  \* stuck here until queue has item

\* Node does barrier wait - SUCCEEDS (get from non-empty queue)
NodeBarrierSucceeds(n) ==
    /\ pc[n] = "wait_barrier"
    /\ EL!YieldGetImmediate(TaskOf(n), Barrier0Queue(n))
    /\ pc' = [pc EXCEPT ![n] = "push"]
    /\ UNCHANGED <<generation, lastSeen, resolutionQueue>>

\* Node pushes data, sets barrier count (puts N items for N consumers)
NodePushesData(n) ==
    /\ pc[n] = "push"
    /\ EL!IsRunning(TaskOf(n))
    /\ LET newGen == generation[n] + 1
           consumers == Downstream(n)
       IN /\ generation' = [generation EXCEPT ![n] = newGen]
          /\ \* Set barrier count = put N items into queue
             \* This is awkward - might need multiple steps or abstract it
          /\ pc' = [pc EXCEPT ![n] = "enqueue"]
    /\ UNCHANGED <<lastSeen, resolutionQueue, EL!taskState, ...>>